"""Stage 4 offline planner: all windows/lanes budgeted, no transport or persistent writes."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import Base, get_db
from app.main import app
from app.models import IngestRun, IngestState, SourceProfile
from app.pipeline.catchup import config_hash
from app.sources import keyword_translation as kt

AT = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)


class CatchUpPreviewTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        app.dependency_overrides[get_db] = lambda: self.db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        clock = patch('app.main.now', return_value=AT); clock.start(); self.addCleanup(clock.stop)
        settings = Settings(_env_file=None, app_environment='development', anthropic_api_key='', newscatcher_api_key='',
                            keyword_translation_allow_live=False)
        for module in ('app.main', 'app.sources.newscatcher', 'app.sources.newscatcher_filters', 'app.sources.keyword_translation'):
            p = patch(module + '.get_settings', return_value=settings); p.start(); self.addCleanup(p.stop)
        self.params = {
            'endpoint': 'articles', 'keywords': ['Baltic Sea'], 'event_presets': ['cyber'], 'coverage_countries': ['DK'],
            'exclude_keywords': ['sport'], 'languages': ['en', 'da'], 'source_countries': ['DK'], 'max_records': 100,
            'max_requests_per_poll': 8, 'max_credits_per_poll': 40,
            'native_filters': {'sources': ['example.com'], 'not_languages': ['ru'], 'not_countries': ['US'],
                               'exclude_duplicates': False, 'word_count_min': 0, 'sort_by': 'published_at'},
        }
        self.profile = SourceProfile(name='Disposable Articles', source='newscatcher', params=copy.deepcopy(self.params),
                                     enabled=False, interval_minutes=60, last_run_at=AT-timedelta(days=1))
        self.db.add(self.profile); self.db.flush()
        self.profile.ingest_state = IngestState(last_success_at=AT-timedelta(days=1), last_attempt_at=AT,
                                               failures=1, run_requested=True, retry_at=AT+timedelta(minutes=5))
        self.run = IngestRun(profile_id=self.profile.id, source='newscatcher', status='success',
                             started_at=AT-timedelta(seconds=1), finished_at=AT, window_since=AT-timedelta(hours=2),
                             window_until=AT, config_hash=config_hash(self.params),
                             request_metrics=[{'endpoint': 'articles', 'cap_hit': True, 'history_clamped': False}])
        self.db.add(self.run); self.db.commit()
        self.body = {
            'evidence_run_id': self.run.id, 'window_start': (AT-timedelta(hours=2)).isoformat(), 'window_end': AT.isoformat(),
            'window_minutes': 60, 'max_requests': 16, 'max_credits': 80,
            'entitlement': {'confirmed': True, 'reference': 'Offline fixture subscription note; no credentials',
                            'observed_at': AT.isoformat(), 'history_start': (AT-timedelta(days=30)).isoformat(),
                            'max_articles_per_page': 20},
        }

    def update_params(self, **changes):
        self.params = {**self.params, **changes}
        self.profile.params = copy.deepcopy(self.params)
        self.run.config_hash = config_hash(self.params)
        self.db.commit()

    def snapshot(self):
        return {t.name: copy.deepcopy([dict(r) for r in self.db.execute(select(t)).mappings()])
                for t in Base.metadata.sorted_tables}

    def request(self, body=None):
        before = self.snapshot()
        with patch('requests.sessions.Session.request', side_effect=AssertionError('provider transport')), \
             patch('httpx.HTTPTransport.handle_request', side_effect=AssertionError('provider transport')), \
             patch('app.sources.newscatcher.NewsCatcherSource._plan', side_effect=AssertionError('subscription lookup')), \
             patch.object(kt, '_model_candidates', side_effect=AssertionError('translation model')), \
             patch.object(self.db, 'commit', wraps=self.db.commit) as commit:
            result = self.client.post(f'/api/profiles/{self.profile.id}/catch-up-preview', json=body or self.body)
            commit.assert_not_called()
        self.assertEqual(self.snapshot(), before, 'preview changed database state')
        return result

    def refused(self, code, body=None):
        response = self.request(body)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn(code, response.json()['detail'])

    def test_complete_plan_preserves_all_filters_and_every_boundary(self):
        response = self.request()
        self.assertEqual(response.status_code, 200, response.text)
        plan = response.json()
        self.assertTrue(plan['preview_only']); self.assertFalse(plan['executable'])
        self.assertEqual((plan['window_count'], plan['request_count'], plan['estimated_credits']), (2, 2, 10))
        self.assertEqual(plan['budget']['max_requests'], 8)
        self.assertEqual(plan['budget']['max_credits'], 40)
        self.assertEqual(plan['coverage'], 'uncertain')
        self.assertEqual(plan['indexing_delay'], 'not measured')
        self.assertIn('not live-verified', plan['entitlement']['status'])
        self.assertEqual(plan['evidence']['reasons'], ['result_cap'])
        self.assertEqual(plan['windows'][0]['to_date'], plan['windows'][1]['from_date'])
        self.assertEqual(plan['windows'][0]['from_date'], self.body['window_start'])
        self.assertEqual(plan['windows'][-1]['to_date'], self.body['window_end'])
        for request in plan['requests']:
            payload = request['parameters']
            self.assertTrue(request['endpoint'].endswith('/articles'))
            self.assertEqual(request['method'], 'POST')
            self.assertEqual((payload['page'], payload['page_size']), (1, 20))
            self.assertLessEqual(len(payload['q']), 1000)
            for term in ['Baltic Sea', 'cyberattack', 'ransomware', 'data breach', 'Denmark', 'NOT sport']:
                self.assertIn(term, payload['q'])
            for name, value in self.params['native_filters'].items():
                self.assertEqual(payload[name], value)
            self.assertEqual(payload['countries'], ['DK']); self.assertEqual(payload['languages'], ['en', 'da'])
            self.assertEqual(request['translation_language'], 'original')
        self.assertIsNone(self.profile.last_status)

    def test_unknown_unconfirmed_or_stale_entitlement_never_guessed(self):
        self.refused('ENTITLEMENT_UNKNOWN', {**self.body, 'entitlement': None})
        for observed in (AT-timedelta(hours=24, seconds=1), AT+timedelta(seconds=1)):
            self.refused('ENTITLEMENT_STALE', {**self.body, 'entitlement': {**self.body['entitlement'], 'observed_at': observed.isoformat()}})
        self.refused('HISTORY_UNAVAILABLE', {**self.body, 'entitlement': {**self.body['entitlement'], 'history_start': AT.isoformat()}})
        for change in ({'confirmed': False}, {'confirmed': 1}, {'reference': ' '}, {'max_articles_per_page': 0},
                       {'max_articles_per_page': True}, {'max_articles_per_page': 101}, {'pages': 2}):
            with self.subTest(change=change):
                response = self.request({**self.body, 'entitlement': {**self.body['entitlement'], **change}})
                self.assertEqual(response.status_code, 422, response.text)

    def test_search_v3_and_gdelt_are_not_implicitly_converted(self):
        self.update_params(endpoint='search', native_filters={})
        self.refused('UNSUPPORTED_ENDPOINT')
        # Current deployment only supports news endpoints; v3 configuration must still fail locally.
        self.update_params(endpoint='v3', native_filters={})
        self.assertEqual(self.request().status_code, 409)
        self.profile.source = 'gdelt'; self.db.commit()
        self.refused('UNSUPPORTED_ENDPOINT')

    def test_saved_explicit_dates_or_paging_cannot_be_overwritten(self):
        for native in ({'from_date': '2026-11-18T10:00:00Z'}, {'to_date': '2026-11-18T12:00:00Z'}, {'page': 1}, {'page': 2}):
            with self.subTest(native=native):
                self.update_params(native_filters=native)
                self.refused('EXPLICIT_WINDOW_FILTER')

    def test_missing_wrong_unfinished_changed_or_healthy_poll_is_refused(self):
        self.assertEqual(self.request({**self.body, 'evidence_run_id': 99999}).status_code, 404)
        other = SourceProfile(name='Other', source='newscatcher', params={})
        self.db.add(other); self.db.flush()
        self.run.profile_id = other.id; self.db.commit()
        self.assertEqual(self.request().status_code, 404)
        self.run.profile_id = self.profile.id; self.run.finished_at = None; self.db.commit()
        self.refused('UNFINISHED_EVIDENCE')
        self.run.finished_at = AT; self.run.config_hash = 'old revision'; self.db.commit()
        self.refused('STALE_EVIDENCE')
        self.run.config_hash = config_hash(self.params); self.run.request_metrics = []; self.db.commit()
        self.refused('NO_COMPLETENESS_EVIDENCE')

    def test_partial_failed_and_clamped_evidence_is_visible_not_a_coverage_promise(self):
        for status, metrics, reason in [('partial', [], 'incomplete_poll'), ('error', [], 'incomplete_poll'),
                                        ('success', [{'history_clamped': True}], 'history_clamped')]:
            with self.subTest(status=status):
                self.run.status, self.run.request_metrics = status, metrics; self.db.commit()
                response = self.request()
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['evidence']['reasons'], [reason])
                self.assertEqual(response.json()['coverage'], 'uncertain')

    def test_invalid_naive_future_and_outside_intervals_are_refused(self):
        for start, end, code in [(AT, AT, 'INVALID_WINDOW'), (AT, AT+timedelta(seconds=1), 'INVALID_WINDOW'),
                                  (AT-timedelta(hours=3), AT, 'OUTSIDE_EVIDENCE_WINDOW')]:
            self.refused(code, {**self.body, 'window_start': start.isoformat(), 'window_end': end.isoformat()})
        response = self.request({**self.body, 'window_start': '2026-11-18T10:00:00'})
        self.assertEqual(response.status_code, 422)
        # Fractional last windows retain the exact end; no trailing interval is silently dropped.
        response = self.request({**self.body, 'window_minutes': 45})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['window_count'], 3)
        self.assertEqual(response.json()['windows'][-1]['to_date'], self.body['window_end'])

    def test_window_and_global_budgets_reject_without_truncation(self):
        for changes in ({'max_requests': 1}, {'max_credits': 5}, {'window_minutes': 1}):
            self.refused('CATCHUP_BUDGET_EXCEEDED', {**self.body, **changes})
        for changes in ({'max_requests': 17}, {'max_requests': True}, {'window_minutes': 0}, {'max_credits': 0},
                        {'execute': True}, {'page': 2}):
            self.assertEqual(self.request({**self.body, **changes}).status_code, 422)
        self.update_params(max_requests_per_poll=1)
        self.refused('CATCHUP_BUDGET_EXCEEDED')
        self.update_params(max_requests_per_poll=8, max_credits_per_poll=5)
        self.refused('CATCHUP_BUDGET_EXCEEDED')

    def test_query_splits_share_total_budget_and_retain_all_terms(self):
        keywords = [f'phrase {n} ' + 'x' * 80 for n in range(16)]
        self.update_params(keywords=keywords)
        response = self.request()
        self.assertEqual(response.status_code, 200, response.text)
        plan = response.json()
        self.assertGreater(plan['request_count'], plan['window_count'])
        for window in plan['windows']:
            parts = [r['parameters']['q'] for r in plan['requests'] if r['window'] == window['index']]
            for keyword in keywords:
                self.assertTrue(any(keyword in query for query in parts), keyword)
            for query in parts:
                self.assertLessEqual(len(query), 1000)
                self.assertIn('Denmark', query); self.assertIn('NOT sport', query)
        self.refused('CATCHUP_BUDGET_EXCEEDED', {**self.body, 'max_requests': 3})
        self.refused('CATCHUP_BUDGET_EXCEEDED', {**self.body, 'max_credits': 15})

    def test_approved_languages_share_one_budget_no_translation_or_reapproval(self):
        params = {**self.params, 'multilingual_enabled': True, 'translation_auto_languages': True}
        review = kt.create_review(self.db, params)
        self.db.commit()
        decisions = [{'id': r['id'], 'translations': r['candidates'], 'keep_original': False} for r in review.payload['rows']]
        kt.approve_review(self.db, review.id, params, decisions); self.db.commit()
        self.update_params(**params, translation_review_id=review.id)
        response = self.request()
        self.assertEqual(response.status_code, 200, response.text)
        plan = response.json()
        self.assertEqual((plan['request_count'], plan['estimated_credits']), (4, 20))
        self.assertEqual([r['translation_language'] for r in plan['requests']], ['original', 'da', 'original', 'da'])
        for r in plan['requests']:
            self.assertEqual(r['translation_review_id'], review.id)
            if r['translation_language'] == 'da':
                self.assertIn('Østersøen', r['parameters']['q'])
                self.assertEqual(r['parameters']['languages'], ['da'])
        self.refused('CATCHUP_BUDGET_EXCEEDED', {**self.body, 'max_requests': 3})
        self.refused('CATCHUP_BUDGET_EXCEEDED', {**self.body, 'max_credits': 15})
        self.update_params(translation_review_id='unknown')
        self.assertEqual(self.request().status_code, 409)

    def test_advanced_text_is_retained_and_indivisible_overflow_is_refused(self):
        query = '(ports OR shipping) AND NOT marketing'
        self.update_params(query=query)
        response = self.request()
        self.assertEqual(response.status_code, 200, response.text)
        for r in response.json()['requests']:
            self.assertIn(query, r['parameters']['q'])
        self.update_params(query='x' * 1100)
        self.assertEqual(self.request().status_code, 409)

    def test_unknown_cost_is_not_assumed_free(self):
        with patch('app.pipeline.catchup.request_credit_estimate', return_value=None):
            self.refused('CREDIT_ESTIMATE_UNAVAILABLE')
