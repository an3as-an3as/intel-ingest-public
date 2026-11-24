"""Offline reliability tests. Optional PostgreSQL tests exercise actual row locking."""
import os
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['APP_PASSWORD'] = ''

import tempfile
import threading
import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import Base, get_db
from app.main import app
from app.models import Article, PirSet, Summary, WorkerState
from app.pipeline.summarize import next_pending_ids, run_summary
from app.worker import tick
from app.worker_health import WorkerMonitor, pipeline_health


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f'sqlite:///{self.tmp.name}/test.db')
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.engine.dispose)
        for module in ('app.pipeline.summarize', 'app.worker', 'app.worker_health'):
            p = patch(f'{module}.session_scope', self.session_scope)
            p.start(); self.addCleanup(p.stop)
        self.settings = get_settings().model_copy(update={'anthropic_api_key': 'offline-test', 'fetch_article_text': False})
        for module in ('app.main', 'app.worker', 'app.pipeline.summarize'):
            p = patch(f'{module}.get_settings', return_value=self.settings)
            p.start(); self.addCleanup(p.stop)
        def request_db():
            with self.sessions() as s:
                yield s
        app.dependency_overrides[get_db] = request_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        with self.session_scope() as s:
            dashboard = PirSet(name='Offline dashboard')
            s.add(dashboard); s.flush()
            self.dashboard_id = dashboard.id

    @contextmanager
    def session_scope(self):
        with self.sessions.begin() as s:
            yield s

    def enqueue(self):
        response = self.client.post(f'/api/pir-sets/{self.dashboard_id}/summaries', json={'period': '7d'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'pending')
        return response.json()['id']

    def status(self, sid):
        with self.sessions() as s:
            row = s.get(Summary, sid)
            return row.status, row.error, row.content

    def test_enqueue_does_not_run_in_api_and_worker_consumes_existing_queue(self):
        with patch('app.pipeline.summarize.llm.call', return_value='Offline report') as model:
            sid = self.enqueue()
            model.assert_not_called()
            self.assertEqual(next_pending_ids(), [sid])
            tick()
            self.assertEqual(self.status(sid), ('done', None, 'Offline report'))
            self.assertFalse(run_summary(sid))
            model.assert_called_once()

    def test_process_death_rolls_back_and_next_worker_recovers(self):
        sid = self.enqueue()
        # SystemExit bypasses Exception handlers like a process interruption.
        with patch('app.pipeline.summarize.llm.call', side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                run_summary(sid)
        self.assertEqual(self.status(sid), ('pending', None, None))
        with patch('app.pipeline.summarize.llm.call', return_value='Recovered'):
            self.assertTrue(run_summary(sid))
        self.assertEqual(self.status(sid)[2], 'Recovered')

    def test_model_failure_is_terminal_until_explicit_paid_retry(self):
        sid = self.enqueue()
        with patch('app.pipeline.summarize.llm.call', side_effect=RuntimeError('provider unavailable')):
            self.assertTrue(run_summary(sid))
        self.assertEqual(self.status(sid)[:2], ('failed', 'provider unavailable'))
        self.assertEqual(next_pending_ids(), [])
        response = self.client.post(f'/api/summaries/{sid}/retry')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.status(sid), ('pending', None, None))
        self.assertEqual(self.client.post(f'/api/summaries/{sid}/retry').status_code, 409)
        with patch('app.pipeline.summarize.llm.call', return_value='Retried'):
            run_summary(sid)
        self.assertEqual(self.client.post(f'/api/summaries/{sid}/retry').status_code, 409)

    def test_database_failure_remains_pending(self):
        sid = self.enqueue()
        with patch('app.pipeline.summarize._generate', side_effect=OperationalError('test', {}, Exception('lost DB'))):
            with self.assertRaises(OperationalError):
                run_summary(sid)
        self.assertEqual(self.status(sid), ('pending', None, None))

    def test_deleted_jobs_are_skipped_and_work_per_tick_is_bounded(self):
        deleted = self.enqueue()
        self.assertEqual(self.client.delete(f'/api/summaries/{deleted}').status_code, 200)
        self.assertFalse(run_summary(deleted))
        first, second = self.enqueue(), self.enqueue()
        with patch('app.pipeline.summarize.llm.call', return_value='One report') as model, \
             patch('app.worker.enrich_pending', return_value=40) as classify:
            tick()
            model.assert_called_once()
            classify.assert_called_once()
        self.assertEqual(self.status(first)[0], 'done')
        self.assertEqual(self.status(second)[0], 'pending')

    def test_missing_key_preserves_queue_without_model_calls(self):
        sid = self.enqueue()
        with patch('app.worker.get_settings', return_value=self.settings.model_copy(update={'anthropic_api_key': None})), \
             patch('app.pipeline.summarize.llm.call') as model:
            tick()
            model.assert_not_called()
        self.assertEqual(self.status(sid)[0], 'pending')

    def test_status_reports_fresh_stale_and_stopped_workers_and_queue_ages(self):
        sid = self.enqueue()
        at = datetime.now(timezone.utc)
        with self.session_scope() as s:
            s.add_all([
                WorkerState(id='alive', heartbeat_at=at, phase='summarising', phase_started_at=at, summary_id=sid),
                WorkerState(id='stale', heartbeat_at=at-timedelta(seconds=46), phase='classifying', phase_started_at=at),
                WorkerState(id='stopped', heartbeat_at=at, phase='stopped', phase_started_at=at),
                Article(url='https://example.test', title='Pending', title_hash='pending', published_at=at,
                        ingested_at=at-timedelta(hours=2)),
            ])
        with self.sessions() as s:
            health = pipeline_health(s, at)
        workers = {w['id']: w for w in health['workers']}
        self.assertTrue(workers['alive']['healthy'])
        self.assertFalse(workers['stale']['healthy'])
        self.assertFalse(workers['stopped']['healthy'])
        self.assertEqual(health['summaries_by_status'], {'pending': 1})
        self.assertIsNotNone(health['oldest_pending_summary_at'])
        self.assertEqual(health['oldest_pending_ingested_at'], (at-timedelta(hours=2)).isoformat())
        self.assertEqual(self.client.get('/api/status').status_code, 200)

    def test_heartbeat_runs_independently_and_records_stop(self):
        monitor = WorkerMonitor()
        updated = threading.Event()
        original = monitor.report
        def report(*args, **kwargs):
            original(*args, **kwargs)
            if threading.current_thread().name == 'worker-heartbeat':
                updated.set()
        with patch('app.worker_health.HEARTBEAT_SECONDS', .01), patch.object(monitor, 'report', side_effect=report):
            monitor.start()
            try:
                monitor.report('summarising', summary_id=12, last_error='previous tick failed')
                self.assertTrue(updated.wait(2), 'heartbeat did not update during work')
                with self.sessions() as s:
                    row = s.get(WorkerState, monitor.id)
                    self.assertEqual(row.phase, 'summarising')
                    self.assertEqual(row.summary_id, 12)
                    self.assertEqual(row.last_error, 'previous tick failed')
            finally:
                monitor.stop()
        with self.sessions() as s:
            self.assertEqual(s.get(WorkerState, monitor.id).phase, 'stopped')


@unittest.skipUnless(os.environ.get('TEST_POSTGRES_URL'), 'requires disposable PostgreSQL')
class PostgresLockTests(unittest.TestCase):
    def setUp(self):
        self.schema = 'reliability_' + uuid.uuid4().hex
        self.root = create_engine(os.environ['TEST_POSTGRES_URL'])
        with self.root.begin() as c:
            c.execute(text(f'CREATE SCHEMA {self.schema}'))
        self.engine = self.root.execution_options(schema_translate_map={None: self.schema})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.patch = patch('app.pipeline.summarize.session_scope', self.session_scope)
        self.patch.start()
        def request_db():
            with self.sessions() as s:
                yield s
        app.dependency_overrides[get_db] = request_db
        self.client = TestClient(app)
        with self.session_scope() as s:
            dashboard = PirSet(name='Lock test'); s.add(dashboard); s.flush()
            at = datetime.now(timezone.utc)
            summary = Summary(set_id=dashboard.id, period_label='Test', period_start=at-timedelta(days=7), period_end=at)
            s.add(summary); s.flush(); self.sid = summary.id

    @contextmanager
    def session_scope(self):
        with self.sessions.begin() as s:
            yield s

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.patch.stop()
        with self.root.begin() as c:
            c.execute(text(f'DROP SCHEMA {self.schema} CASCADE'))
        self.root.dispose()

    def test_concurrent_worker_skips_locked_job_and_crash_releases_it(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def crash(s, row):
            entered.set()
            if not release.wait(5):
                raise AssertionError('test timed out')
            raise SystemExit('simulated process death')
        def worker():
            try:
                run_summary(self.sid)
            except BaseException as e:
                errors.append(e)
        with patch('app.pipeline.summarize._generate', side_effect=crash):
            thread = threading.Thread(target=worker); thread.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assertFalse(run_summary(self.sid), 'another worker must not run the locked job')
                self.assertEqual(self.client.delete(f'/api/summaries/{self.sid}').status_code, 409)
                self.assertEqual(self.client.post(f'/api/summaries/{self.sid}/retry').status_code, 409)
            finally:
                release.set(); thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(errors[0], SystemExit)
        def finish(s, row):
            row.status, row.content = 'done', 'Recovered after rollback'
        with patch('app.pipeline.summarize._generate', side_effect=finish):
            self.assertTrue(run_summary(self.sid))
            self.assertFalse(run_summary(self.sid))

    def test_connection_loss_before_commit_leaves_job_retryable(self):
        def disconnect(s, row):
            pid = s.scalar(text('SELECT pg_backend_pid()'))
            with self.root.begin() as c:
                c.execute(text('SELECT pg_terminate_backend(:pid)'), {'pid': pid})
            row.status, row.content = 'done', 'Unsaved result'
        with patch('app.pipeline.summarize._generate', side_effect=disconnect):
            with self.assertRaises(OperationalError):
                run_summary(self.sid)
        with self.sessions() as s:
            row = s.get(Summary, self.sid)
            self.assertEqual(row.status, 'pending')
            self.assertIsNone(row.content)
        def finish(s, row):
            row.status, row.content = 'done', 'Recovered'
        with patch('app.pipeline.summarize._generate', side_effect=finish):
            self.assertTrue(run_summary(self.sid))
