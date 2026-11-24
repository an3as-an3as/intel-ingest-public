"""Provider contract and multi-value regression tests; no API credentials/calls."""
import os
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['APP_PASSWORD'] = ''

import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import utcnow
from app.sources.newscatcher import build_request, build_requests, NewsCatcherSource, NEWS_API, V3_API
from app.sources.options import EVENT_QUERIES
from app.sources.newscatcher_filters import SCHEMAS, MANAGED, validate_native_filters, filter_metadata
from app.sources.options import ingestion_options


class FilterContractTests(unittest.TestCase):
    def build(self, mode='search', filters=None, **params):
        now = utcnow()
        return build_request({'keywords': ['shipping'], 'endpoint': mode, 'native_filters': filters or {}, **params},
                             now-timedelta(hours=1), now, api_version='v3' if mode == 'v3' else 'news',
                             plan={'max_articles_per_page': 50, 'articles': {'max_articles_per_page': 50}}, effort='low')[1]

    def test_every_documented_parameter_is_exposed_and_forwarded(self):
        self.assertEqual(len(SCHEMAS['search']), 15)
        self.assertEqual(len(SCHEMAS['articles']), 20)
        self.assertEqual(len(SCHEMAS['v3']), 59)
        # Each field's sample is validated and forwarded independently. Managed controls
        # (query, inclusions and size) are supplied by their dedicated form controls.
        for mode, properties in SCHEMAS.items():
            for key, schema in properties.items():
                if key in MANAGED:
                    continue
                array = next((s for s in schema.get('anyOf', schema.get('oneOf', [])) if s.get('type') == 'array'), None)
                if key in ('not_countries',): value = 'SE' if mode == 'v3' else ['SE']
                elif key in ('not_lang', 'not_languages'): value = 'fr' if mode == 'v3' else ['fr']
                elif key == 'search_in': value = 'title' if mode == 'v3' else ['title']
                elif schema.get('enum'): value = schema['enum'][0]
                elif array: value = array.get('examples', [[array.get('items', {}).get('enum', ['example.com'])[0]]])[0]
                elif schema.get('type') == 'boolean': value = False
                elif schema.get('type') in ('integer', 'number'): value = schema.get('minimum', 0.5 if 'exclusiveMinimum' in schema else 1)
                else: value = schema.get('example', schema.get('examples', ['example.com'])[0])
                with self.subTest(mode=mode, field=key):
                    body = self.build(mode, {key: value})
                    expected = str(value).lower() if isinstance(value, bool) and mode == 'v3' else ','.join(value) if isinstance(value, list) and mode == 'v3' else value
                    self.assertEqual(body[key], expected)

    def test_multi_value_filters_and_false_zero_survive(self):
        body = self.build(filters={'not_countries': ['US','CA'], 'not_languages': ['fr','de'],
                                   'sources': ['bbc.co.uk','reuters.com'], 'not_sources': ['example.com'],
                                   'min_newsrooms': 0, 'content_type': 'all', 'collapse': 'story', 'effort': 'high'},
                          source_countries=['FI','SE','GB'], languages=['en','fi','sv'])
        self.assertEqual(body['countries'], ['FI','SE','GB'])
        self.assertEqual(body['languages'], ['en','fi','sv'])
        self.assertEqual(body['not_countries'], ['US','CA'])
        self.assertEqual(body['min_newsrooms'], 0)
        self.assertEqual(body['effort'], 'high')
        self.assertFalse(self.build('articles', {'ranked_only': False})['ranked_only'])
        legacy = self.build('v3', {'not_lang': 'fr,de', 'is_opinion': False, 'theme': 'Tech,Science'}, languages=['en','fi'], source_countries=['FI','SE'])
        self.assertEqual(legacy['countries'], 'FI,SE')
        self.assertEqual(legacy['lang'], 'en,fi')
        self.assertEqual(legacy['is_opinion'], 'false')

    def test_unsupported_invalid_and_conflicting_values_are_rejected(self):
        invalid = [dict(theme='Tech'), dict(min_newsrooms=-1), dict(min_newsrooms=True), dict(collapse='random'),
                   dict(not_countries=['ZZ']), dict(not_languages=['bogus']), dict(search_window='0m'),
                   dict(search_window='2years'), dict(not_countries=['FI']), dict(not_languages=['en']),
                   dict(countries=['US']), dict(include=['unsupported']), dict(from_rank=1)]
        for filters in invalid:
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                self.build(filters=filters, source_countries=['FI'], languages=['en'])
        for filters in ({'from_rank': 20, 'to_rank': 10}, {'search_in': ['title','body','summary']}, {'page': 11}):
            with self.assertRaises(ValueError): self.build('articles', filters)
        with self.assertRaises(ValueError): self.build(filters={'sources': ['example.com'], 'not_sources': ['example.com']})
        with self.assertRaises(ValueError): self.build(query='x'*501)
        with self.assertRaises(ValueError): build_request({'keywords': ['x'], 'endpoint': 'v3'}, utcnow(), utcnow(), api_version='news')

    def test_articles_and_v3_use_correct_endpoints_and_response_parsing(self):
        source = NewsCatcherSource()
        response = SimpleNamespace(status_code=200, json=lambda: {'results': [{'url': 'https://example.com/a', 'title': 'A', 'published_at': utcnow().isoformat(), 'image_url': 'https://example.com/image'}]})
        with patch.object(source, '_plan', return_value={'articles': {'max_articles_per_page': 20}}), patch('app.sources.newscatcher._throttle'), patch('app.sources.newscatcher.requests.post', return_value=response) as post:
            result = source._fetch_news(SimpleNamespace(newscatcher_api_key='fake', newscatcher_effort='low'),
                                        {'keywords': ['x'], 'endpoint': 'articles', 'native_filters': {'ranked_only': False}}, utcnow()-timedelta(hours=1), utcnow())
        self.assertEqual(post.call_args.args[0], f'{NEWS_API}/articles')
        self.assertNotIn('effort', post.call_args.kwargs['json'])
        self.assertFalse(post.call_args.kwargs['json']['ranked_only'])
        self.assertEqual(len(result), 1)
        cluster = SimpleNamespace(status_code=200, json=lambda: {'clusters': [{'articles': [{'link': 'https://example.com/a', 'title': 'A'}]}]})
        with patch('app.sources.newscatcher._throttle'), patch('app.sources.newscatcher.requests.get', return_value=cluster) as get:
            result = source._fetch_v3('fake', {'keywords': ['x'], 'native_filters': {'clustering_enabled': True}}, utcnow(), utcnow())
        self.assertEqual(get.call_args.args[0], V3_API)
        self.assertEqual(get.call_args.kwargs['params']['clustering_enabled'], 'true')
        self.assertEqual(len(result), 1)

    def test_oversized_presets_are_split_without_losing_scope(self):
        params = {'event_presets': list(EVENT_QUERIES), 'coverage_countries': ['EE','LV','LT'],
                  'source_countries': ['EE','LV'], 'languages': ['en','et'], 'exclude_keywords': ['sport'],
                  'native_filters': {'min_newsrooms': 3, 'not_sources': ['example.com']}}
        batches = build_requests(params, utcnow()-timedelta(hours=1), utcnow(), api_version='news')
        self.assertGreater(len(batches), 1)
        self.assertLessEqual(len(batches), 16)
        combined = ' '.join(body['q'] for _, body in batches)
        for terms in EVENT_QUERIES.values():
            for term in terms:
                self.assertIn(term, combined)
        for _, body in batches:
            self.assertLessEqual(len(body['q']), 500)
            for country in ('Estonia','Latvia','Lithuania'):
                self.assertIn(country, body['q'])
            self.assertIn(' NOT sport', body['q'])
            self.assertEqual(body['countries'], ['EE','LV'])
            self.assertEqual(body['languages'], ['en','et'])
            self.assertEqual(body['min_newsrooms'], 3)
            self.assertEqual(body['not_sources'], ['example.com'])
        raw = '(ports OR shipping) NOT tourism'
        batches = build_requests({**params, 'query': raw}, utcnow(), utcnow(), api_version='news')
        self.assertTrue(all(raw in body['q'] for _, body in batches))
        with self.assertRaisesRegex(ValueError, 'Shorten the advanced query'):
            build_requests({'query': 'x'*501}, utcnow(), utcnow(), api_version='news')
        with self.assertRaisesRegex(ValueError, 'more than 16'):
            build_requests({'keywords': [f'{i}_' + 'x'*280 for i in range(64)]}, utcnow(), utcnow(), api_version='news')

    def test_split_requests_are_fetched_and_deduplicated(self):
        params = {'event_presets': list(EVENT_QUERIES), 'coverage_countries': ['EE','LV','LT']}
        responses = []
        def response(*args, **kwargs):
            index = len(responses)
            responses.append(kwargs['json'])
            return SimpleNamespace(status_code=200, json=lambda: {'results': [
                {'url': 'https://example.com/shared', 'title': 'Shared'},
                {'url': f'https://example.com/part{index}', 'title': f'Part {index}'}]})
        source = NewsCatcherSource()
        with patch.object(source, '_plan', return_value={}), patch('app.sources.newscatcher._throttle'), patch('app.sources.newscatcher.requests.post', side_effect=response):
            articles = source._fetch_news(SimpleNamespace(newscatcher_api_key='fake', newscatcher_effort='low'), params, utcnow(), utcnow())
        self.assertGreater(len(responses), 1)
        self.assertTrue(all(len(body['q']) <= 500 for body in responses))
        self.assertEqual(len(articles), 1 + len(responses))
        self.assertEqual(len({a.url for a in articles}), len(articles))

    def test_languages_and_endpoint_metadata(self):
        options = ingestion_options()
        for language in ('en','fi','sw','zu','cn','tw'):
            self.assertIn(language, options['languages'])
        with patch('app.sources.newscatcher_filters.get_settings', return_value=SimpleNamespace(newscatcher_api='v3')):
            self.assertEqual(list(filter_metadata()['modes']), ['v3'])


class FilterProfileTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close(); self.db.close(); self.engine.dispose()

    def test_large_baltic_stream_can_be_created_and_previewed(self):
        payload = {'name': 'Baltic developments', 'source': 'newscatcher', 'params': {
            'event_presets': ['armed_conflict','military_activity','terrorism','civil_unrest','political',
                              'diplomacy','crime','economic_sanctions','energy','maritime','infrastructure',
                              'disaster_environment','migration'],
            'coverage_countries': ['EE','LV','LT']}}
        saved = self.client.post('/api/profiles', json=payload)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()['params'], payload['params'])
        preview = self.client.post('/api/profiles/preview-query', json=payload)
        self.assertEqual(preview.status_code, 200, preview.text)
        data = preview.json()
        self.assertGreater(data['request_count'], 1)
        self.assertEqual(data['request_count'], len(data['requests']))
        self.assertTrue(all(len(r['parameters']['q']) <= 500 for r in data['requests']))
        self.assertIn('Each request consumes API quota/credits', data['note'])

    def test_roundtrip_and_full_request_preview_without_network(self):
        payload = dict(name='Multiple choices', source='newscatcher', params={
            'keywords': ['shipping'], 'source_countries': ['FI','SE','GB'], 'languages': ['en','fi','sv'],
            'event_presets': ['maritime','energy'], 'native_filters': {'not_countries': ['US','CA'],
                'not_languages': ['fr','de'], 'min_newsrooms': 3, 'sources': ['bbc.co.uk','reuters.com'], 'include': ['entities','sentiment']}})
        response = self.client.post('/api/profiles', json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        profile = response.json()
        saved = self.client.get('/api/profiles').json()[0]
        self.assertEqual(saved['params'], payload['params'])
        response = self.client.put(f'/api/profiles/{profile["id"]}', json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        with patch('requests.post', side_effect=AssertionError('Preview must not consume API credits')):
            preview = self.client.post('/api/profiles/preview-query', json=payload)
        self.assertEqual(preview.status_code, 200, preview.text)
        request = preview.json()
        self.assertEqual(request['endpoint'], f'{NEWS_API}/search')
        self.assertEqual(request['parameters']['countries'], ['FI','SE','GB'])
        self.assertEqual(request['parameters']['languages'], ['en','fi','sv'])
        self.assertEqual(request['parameters']['include'], ['entities','sentiment'])
        self.assertEqual(request['parameters']['min_newsrooms'], 3)
        self.assertNotIn('api_key', str(request))
        payload['params']['native_filters']['theme'] = 'Tech'
        self.assertEqual(self.client.post('/api/profiles', json=payload).status_code, 422)


if __name__ == '__main__':
    unittest.main()
