"""Phase-one regression tests: SQLite, synthetic articles, mocked providers only."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db, init_db
from app.main import app
from app.models import Article, ArticleFingerprint, ArticleProfile, IngestRun, IngestRunArticle, SourceProfile
from app.pipeline.deduplication import legacy_title_hash, title_hash
from app.pipeline.ingest import is_due, run_profile
from app.sources.base import FetchResult, RawArticle, SourceError
from app.sources.gdelt import GdeltRateLimited
from app.sources.newscatcher import NewsCatcherSource

NOW = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)


def article(name, title, **kwargs):
    return RawArticle(url=f'https://example.test/{name}', title=title, published_at=NOW, **kwargs)


def response(rows=None, status=200, headers=None):
    return SimpleNamespace(status_code=status, headers=headers or {}, json=lambda: {'results': rows or []})


class CollectionReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        @event.listens_for(self.engine, 'connect')
        def foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.profile = SourceProfile(name='Offline test', source='newscatcher', enabled=True,
                                     interval_minutes=60, params={'keywords': ['shipping']})
        self.db.add(self.profile)
        self.db.commit()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def poll(self, value, at=NOW):
        fetch = Mock(side_effect=value) if isinstance(value, Exception) else Mock(return_value=value)
        with patch('app.pipeline.ingest.SOURCES', {'newscatcher': SimpleNamespace(fetch=fetch)}), \
                patch('app.pipeline.ingest.datetime', wraps=datetime) as clock:
            clock.now.return_value = at
            count = run_profile(self.db, self.profile)
            self.db.commit()
        return count, fetch

    def latest(self):
        return self.db.scalar(select(IngestRun).order_by(IngestRun.id.desc()))

    def test_unicode_titles_do_not_collapse(self):
        titles = ['波罗的海海底电缆发生故障', '赫尔辛基港口出现交通中断',
                  'В Балтийском море повреждён кабель', 'В порту начались военные учения',
                  'انقطاع الكهرباء في المدينة', 'إغلاق الميناء بسبب العاصفة']
        self.assertEqual(len({title_hash(t) for t in titles}), len(titles))
        self.assertEqual(self.poll([article(str(i), t) for i,t in enumerate(titles)])[0], len(titles))

    def test_unicode_normalization_and_weak_titles(self):
        self.assertEqual(title_hash('CAFÉ harbour disruption'), title_hash('Cafe\u0301 harbour disruption'))
        self.assertEqual(title_hash('ＦＵＬＬＷＩＤＴＨ report'), title_hash('fullwidth report'))
        for title in ('!!!', '2026', '速報', 'Breaking news'):
            self.assertIsNone(title_hash(title))
        raws = [article(str(i), t) for i,t in enumerate(['!!!','!!!','2026','2026','速報','速報'])]
        self.assertEqual(self.poll(raws)[0], 6)
        self.assertEqual(self.poll(raws)[0], 0)

    def test_legacy_collision_is_verified_and_old_hashes_preserved(self):
        title = 'В Балтийском море повреждён кабель'
        legacy = Article(url='https://example.test/legacy', title=title, title_hash=legacy_title_hash(title),
                         published_at=NOW, ingested_at=NOW, profile_id=self.profile.id)
        self.db.add(legacy); self.db.commit()
        original = legacy.title_hash
        self.assertEqual(self.poll([article('different', 'В порту начались военные учения')])[0], 1)
        self.assertEqual(self.poll([article('copy', title)])[0], 0)
        self.assertEqual(legacy.title_hash, original)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Article)), 2)
        self.assertEqual(self.db.get(ArticleFingerprint, legacy.id).digest, title_hash(title))

    def test_legacy_canonical_equivalence_is_indexed(self):
        old = Article(url='https://example.test/old', title='Cafe\u0301 harbour disruption',
                      title_hash=legacy_title_hash('Cafe\u0301 harbour disruption'), published_at=NOW, ingested_at=NOW)
        self.db.add(old); self.db.commit()
        self.assertEqual(self.poll([article('new-url', 'CAFÉ harbour disruption')])[0], 0)

    def test_failures_preserve_watermark_and_retry_window(self):
        last = NOW - timedelta(hours=3)
        self.profile.last_run_at = last
        self.db.commit()
        count, failed = self.poll(SourceError('provider failure'))
        self.assertEqual(count, 0)
        self.assertEqual(self.profile.last_run_at, last)
        state = self.profile.ingest_state
        self.assertEqual(state.last_attempt_at, NOW)
        self.assertEqual(state.last_success_at, last)
        self.assertEqual(state.retry_at, NOW + timedelta(seconds=60))
        self.assertFalse(is_due(self.profile, NOW + timedelta(seconds=59)))
        self.assertTrue(is_due(self.profile, NOW + timedelta(seconds=60)))
        _, recovered = self.poll([], at=NOW + timedelta(minutes=2))
        self.assertEqual(failed.call_args.args[1], last - timedelta(minutes=15))
        self.assertEqual(recovered.call_args.args[1], last - timedelta(minutes=15))
        self.assertIsNone(state.retry_at)
        self.assertEqual(state.failures, 0)
        self.assertEqual(state.last_success_at, NOW + timedelta(minutes=2))

    def test_first_poll_window_is_pinned_across_outage(self):
        _, first = self.poll(SourceError('offline'))
        _, retry = self.poll([], at=NOW + timedelta(days=2))
        self.assertEqual(first.call_args.args[1], NOW - timedelta(hours=24))
        self.assertEqual(retry.call_args.args[1], first.call_args.args[1])

    def test_backoff_is_bounded_and_provider_cooldown_is_respected(self):
        for index in range(9):
            self.poll(SourceError('offline'))
            self.assertEqual(self.profile.ingest_state.retry_at, NOW + timedelta(seconds=min(3600,60*2**index)))
        future = NOW + timedelta(hours=3)
        self.poll(SourceError('limited', retry_at=future))
        self.assertEqual(self.profile.ingest_state.retry_at, future)
        queued = self.client.post(f'/api/profiles/{self.profile.id}/run')
        self.assertEqual(queued.status_code, 200)
        self.assertFalse(is_due(self.profile, NOW + timedelta(hours=2)))

    def test_manual_run_never_rewinds_success_timestamp(self):
        self.profile.last_run_at = NOW
        self.db.commit()
        result = self.client.post(f'/api/profiles/{self.profile.id}/run')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.profile.last_run_at, NOW)
        self.assertTrue(self.profile.ingest_state.run_requested)
        self.assertTrue(is_due(self.profile, NOW))

    def test_gdelt_cooldown_survives_source_error_constructor(self):
        retry = NOW + timedelta(minutes=20)
        error = GdeltRateLimited(retry)
        self.assertEqual(error.retry_at, retry)

    def test_outcome_counts_and_cross_stream_membership(self):
        self.profile.params = {'keywords': ['shipping'], 'exclude_keywords': ['sports']}
        raws = [article('a', 'Shipping report from Baltic ports'),
                article('a?utm_source=x', 'Shipping report from Baltic ports'),
                article('copy', 'Shipping report from Baltic ports'),
                article('sports', 'Sports shipping report'), article('empty', ' ')]
        self.assertEqual(self.poll(raws)[0], 1)
        run = self.latest()
        self.assertEqual((run.returned_articles,run.new_articles,run.duplicate_urls,run.duplicate_titles,
                          run.excluded_articles,run.invalid_articles), (5,1,1,1,1,1))
        second = SourceProfile(name='Second stream', source='newscatcher', enabled=True, params={'keywords':['shipping']})
        self.db.add(second); self.db.commit()
        self.profile = second
        self.assertEqual(self.poll([raws[0]])[0], 0)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ArticleProfile)), 2)
        self.assertIsNone(self.latest().estimated_credits)  # uninstrumented adapter is not zero-cost

    def native_poll(self, responses, at=NOW):
        source = NewsCatcherSource()
        settings = SimpleNamespace(newscatcher_api='news', newscatcher_api_key='fixture-only-secret', newscatcher_effort='low')
        batches = [('search',{'q':'private query one','effort':'low','limit':2}),
                   ('search',{'q':'private query two','effort':'low','limit':2})]
        with patch('app.pipeline.ingest.SOURCES', {'newscatcher': source}), \
                patch('app.sources.newscatcher.get_settings', return_value=settings), \
                patch.object(source, '_plan', return_value={}), \
                patch('app.sources.newscatcher.build_requests', return_value=batches), \
                patch('app.sources.newscatcher._throttle'), \
                patch('app.sources.newscatcher.requests.post', side_effect=responses) as post, \
                patch('app.pipeline.ingest.datetime', wraps=datetime) as clock, \
                patch('app.sources.newscatcher.datetime', wraps=datetime) as source_clock:
            clock.now.return_value = at
            source_clock.now.return_value = at
            count = run_profile(self.db, self.profile)
            self.db.commit()
        return count, post

    def test_partial_parts_are_saved_then_replayed_without_double_classification(self):
        rows = [{'url': f'https://example.test/{i}', 'title': f'Baltic shipping disruption number {i}'} for i in range(3)]
        old = NOW - timedelta(hours=2)
        self.profile.last_run_at = old
        self.db.commit()
        count, post = self.native_poll([response(rows[:2]), response(status=503)])
        self.assertEqual((count,post.call_count), (2,2))
        run = self.latest()
        self.assertEqual(run.status,'partial')
        self.assertEqual(self.profile.last_run_at,old)
        self.assertEqual(run.planned_requests,2)
        self.assertEqual(run.request_metrics[0]['estimated_credits'],1)
        self.assertIsNone(run.estimated_credits)
        self.assertTrue(run.request_metrics[0]['cap_hit'])
        self.assertEqual(self.db.scalar(select(func.count()).select_from(IngestRunArticle)),2)
        self.assertEqual(self.native_poll([response(rows[:2]),response(rows[2:])], at=NOW+timedelta(minutes=2))[0],1)
        self.assertEqual(self.latest().estimated_credits,2)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Article)),3)

    def test_query_provenance_and_safe_metrics_api(self):
        a={'url':'https://example.test/a','title':'Shipping report from Baltic ports'}
        b={'url':'https://example.test/b','title':'Energy supply interrupted across region'}
        c={'url':'https://example.test/c','title':'Cyber incident affects public services'}
        self.assertEqual(self.native_poll([response([a,b]),response([a,c])])[0],3)
        run = self.latest()
        self.assertEqual(run.returned_articles,4)
        self.assertEqual(run.duplicate_urls,1)
        saved = self.db.scalar(select(Article).where(Article.url==a['url']))
        link = self.db.get(IngestRunArticle,(run.id,saved.id))
        self.assertEqual(link.query_parts,[1,2])
        saved.status='enriched'; self.db.commit()
        result=self.client.get(f'/api/profiles/{self.profile.id}/ingest-runs').json()[0]
        self.assertEqual(result['new_article_statuses'], {'pending':2,'enriched':1})
        self.assertEqual(result['new_articles_per_estimated_credit'],1.5)
        self.assertEqual(result['cap_warnings'],2)
        serialized=json.dumps(result)
        self.assertNotIn('fixture-only-secret',serialized)
        self.assertNotIn('private query',serialized)
        self.assertEqual(self.client.get(f'/api/profiles/{self.profile.id}/ingest-runs?limit=101').status_code,422)
        self.assertEqual(self.client.get('/api/profiles/99999/ingest-runs').status_code,404)

    def test_failed_empty_result_retains_telemetry_and_does_not_call_later_parts(self):
        count, post = self.native_poll([response(status=429,headers={'Retry-After':'600'})])
        self.assertEqual((count,post.call_count),(0,1))
        self.assertEqual(len(self.latest().request_metrics),1)
        self.assertIsNone(self.profile.last_run_at)
        self.assertEqual(self.latest().error_code,'HTTP_429')
        self.assertEqual(self.profile.ingest_state.retry_at,NOW+timedelta(minutes=10))

    def test_malformed_200_response_is_not_success(self):
        invalid=SimpleNamespace(status_code=200,headers={},json=lambda:{'unexpected':'payload'})
        self.native_poll([invalid])
        self.assertEqual(self.latest().status,'error')
        self.assertIsNone(self.profile.last_run_at)
        self.assertEqual(self.latest().estimated_credits,1)

    def test_delete_stream_preserves_articles_and_run_history(self):
        self.poll([article('a','Shipping report from Baltic ports')])
        run_id=self.latest().id
        result=self.client.delete(f'/api/profiles/{self.profile.id}')
        self.assertEqual(result.status_code,200,result.text)
        self.db.expire_all()
        self.assertIsNone(self.db.get(IngestRun,run_id).profile_id)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Article)),1)

    def test_invalid_urls_do_not_discard_other_articles(self):
        raws=[RawArticle(url=url,title='Synthetic shipping report',published_at=NOW)
              for url in ('/relative','ftp://example.test/a','http://[bad','https://user:password@example.test/a')]
        raws.append(article('valid','Valid shipping report from port'))
        self.assertEqual(self.poll(raws)[0],1)
        self.assertEqual(self.latest().invalid_articles,4)
        self.assertEqual(self.latest().status,'success')

    def test_expired_titles_are_not_merged_but_exact_urls_still_are(self):
        raw=article('same-url','Shipping report from Baltic ports')
        self.assertEqual(self.poll([raw])[0],1)
        self.assertEqual(self.poll([article('different-url',raw.title)],at=NOW+timedelta(hours=73))[0],1)
        self.assertEqual(self.poll([raw],at=NOW+timedelta(hours=74))[0],0)

    def test_retry_after_http_date_is_respected(self):
        self.native_poll([response(status=429,headers={'Retry-After':'Sat, 10 Jan 2026 12:30:00 GMT'})])
        self.assertEqual(self.profile.ingest_state.retry_at,NOW+timedelta(minutes=30))

    def test_history_clamp_and_explicit_window_are_visible(self):
        source=NewsCatcherSource()
        settings=SimpleNamespace(newscatcher_api_key='fixture-only',newscatcher_effort='low')
        with patch.object(source,'_plan',return_value={'historical_days':1}), \
                patch('app.sources.newscatcher._throttle'), \
                patch('app.sources.newscatcher.requests.post',return_value=response()):
            result=source._fetch_news(settings,{'keywords':['shipping']},NOW-timedelta(days=3),NOW)
            metric=result.request_metrics[0]
            self.assertTrue(metric['history_clamped'])
            self.assertEqual(metric['time_parameters'],{'search_window':'1440m'})
            result=source._fetch_news(settings,{'keywords':['shipping'],'native_filters':{'search_window':'60m'}},NOW-timedelta(days=3),NOW)
            self.assertTrue(result.request_metrics[0]['window_overridden'])
            self.assertFalse(result.request_metrics[0]['history_clamped'])

    def test_additive_upgrade_does_not_rewrite_legacy_rows(self):
        old_engine=create_engine('sqlite://')
        with old_engine.begin() as connection:
            connection.execute(text('CREATE TABLE source_profiles (id INTEGER PRIMARY KEY, name TEXT)'))
            connection.execute(text("INSERT INTO source_profiles VALUES (1, 'Preserve me')"))
        with patch('app.db.engine',old_engine):
            init_db()
            init_db()
        with old_engine.connect() as connection:
            self.assertEqual(connection.execute(text('SELECT name FROM source_profiles')).scalar(),'Preserve me')
        self.assertIn('ingest_states',inspect(old_engine).get_table_names())
        self.assertIn('article_fingerprints',inspect(old_engine).get_table_names())
        self.assertEqual([c['name'] for c in inspect(old_engine).get_columns('source_profiles')],['id','name'])
        old_engine.dispose()


if __name__=='__main__':
    unittest.main()
