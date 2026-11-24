"""English translated-content mode is explicit; old request defaults stay frozen."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app, ProfileIn
from app.models import KeywordTranslationReview, SourceProfile
from app.sources.newscatcher import build_requests, SCHEMAS

NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)
PARAMS = {'endpoint':'articles', 'event_presets':['cyber'], 'languages':['de'],
          'content_matching':'english-translated-v1'}
FIELDS = ['title_body', 'title_body_translated']


class ContentMatchingTests(unittest.TestCase):
    def test_english_queries_cover_original_and_translated_fields_without_widening_languages(self):
        with patch('requests.post') as provider, patch('anthropic.Anthropic') as model:
            plans = build_requests({**PARAMS, 'native_filters':{'not_languages':['en']}}, NOW-timedelta(hours=1), NOW)
            for endpoint, body in plans:
                self.assertEqual(endpoint, 'articles')
                self.assertEqual(body['search_in'], FIELDS)
                self.assertEqual(body['languages'], ['de'])
                self.assertEqual(body['not_languages'], ['en'])
                self.assertIn('cyberattack', body['q'])
                self.assertNotIn('include', body)
            self.assertEqual(plans.lanes, ['original'])
            provider.assert_not_called(); model.assert_not_called()

    def test_saved_default_profiles_do_not_gain_translated_fields(self):
        for endpoint in ('articles','search'):
            plans = build_requests({'endpoint':endpoint, 'event_presets':['cyber']}, NOW, NOW)
            for _, body in plans:
                self.assertNotIn('search_in', body)

    def test_incompatible_settings_are_rejected_not_silently_rewritten(self):
        for extra in ({'endpoint':'search'}, {'multilingual_enabled':True},
                      {'native_filters':{'search_in':['title']}},
                      {'content_matching':'unknown'}, {'content_matching':[]},
                      {'query_planner_version':'legacy-v1'}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                ProfileIn(name='Invalid mode', params={**PARAMS, **extra})
        with self.assertRaises(ValueError):
            ProfileIn(name='Wrong provider', source='gdelt', params=PARAMS)
        ProfileIn(name='Matching explicit fields', params={**PARAMS, 'native_filters':{'search_in':FIELDS}})

    def test_fields_repeat_on_every_part_and_request_ceiling_still_applies(self):
        params = {**PARAMS, 'keywords':['network compromise','critical systems'], 'coverage_countries':['DK','DE']}
        with patch.dict(SCHEMAS['articles']['q'], {'maxLength':100}):
            parts = build_requests(params, NOW, NOW)
            self.assertGreater(len(parts), 1)
            for _, body in parts:
                self.assertEqual(body['search_in'], FIELDS)
            with self.assertRaises(ValueError):
                build_requests({**params, 'max_requests_per_poll':1}, NOW, NOW)

    def test_preview_save_reload_requires_no_translation_review(self):
        engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread':False})
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as db:
            app.dependency_overrides[get_db] = lambda: db
            try:
                with TestClient(app) as client, patch('requests.post') as provider, patch('anthropic.Anthropic') as model:
                    payload = {'name':'English across languages', 'params':PARAMS}
                    preview = client.post('/api/profiles/preview-query', json=payload)
                    self.assertEqual(preview.status_code, 200, preview.text)
                    data = preview.json()
                    self.assertEqual(data['content_matching']['search_in'], FIELDS)
                    self.assertEqual(data['content_matching']['mode'], 'english-translated-v1')
                    self.assertFalse(data['translations']['enabled'])
                    self.assertEqual(data['estimated_credits_per_poll'], 5)
                    saved = client.post('/api/profiles', json=payload)
                    self.assertEqual(saved.status_code, 200, saved.text)
                    self.assertFalse(saved.json()['enabled'])
                    loaded = client.get('/api/profiles').json()[0]
                    self.assertEqual(loaded['params'], PARAMS)
                    self.assertEqual(db.scalar(select(func.count()).select_from(KeywordTranslationReview)), 0)
                    self.assertEqual(db.scalar(select(func.count()).select_from(SourceProfile)), 1)
                    provider.assert_not_called(); model.assert_not_called()
            finally:
                app.dependency_overrides.clear()
        engine.dispose()
