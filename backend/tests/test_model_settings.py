"""Shared model settings and provider payloads, without live inference."""
import os
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['APP_PASSWORD'] = ''

import unittest
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import Base, get_db
from app.main import app
from app.model_settings import model_for
from app.models import Article, AppSetting, PirSet, Summary, utcnow
from app.pipeline.classify import enrich_pending
from app.pipeline.summarize import run_summary
from app.pipeline import llm


def info(model, structured=True, efforts=('low','medium','high'), max_tokens=64000):
    support = lambda value: NS(supported=value)
    return NS(id=model, display_name=model, lifecycle='active', max_tokens=max_tokens,
              capabilities=NS(structured_outputs=support(structured), effort=NS(supported=bool(efforts),
                  **{e:support(e in efforts) for e in ('low','medium','high','xhigh','max')})))


class ModelSettingsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine,expire_on_commit=False)
        self.db = self.sessions()
        app.dependency_overrides[get_db] = lambda:self.db
        self.client = TestClient(app)
        self.settings = Settings(_env_file=None,anthropic_api_key='test-only',fetch_article_text=False,classify_concurrency=1)
        self.patches = [patch('app.model_settings.get_settings',return_value=self.settings),
                        patch('app.main.get_settings',return_value=self.settings)]
        for p in self.patches:p.start()
        self.models = {m.id:m for m in [info('claude-unit-fast',efforts=(),max_tokens=8192),
                                       info('claude-unit-deep'),info('claude-unit-text',structured=False,efforts=())]}
        self.provider = MagicMock()
        self.provider.__enter__.return_value.models.retrieve.side_effect = lambda model:self.models[model]
        self.provider.__enter__.return_value.models.list.return_value = list(self.models.values())
        self.provider_patch = patch('app.model_settings.provider',return_value=self.provider)
        self.provider_patch.start()
        self.payload = {'classify':{'model':'claude-unit-fast','effort':'auto'},
                        'summary':{'model':'claude-unit-deep','effort':'high'}}

    def tearDown(self):
        self.provider_patch.stop()
        for p in self.patches:p.stop()
        app.dependency_overrides.clear()
        self.client.close();self.db.close();self.engine.dispose()

    def save(self,payload=None):
        response = self.client.put('/api/settings/models',json=payload or self.payload)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_defaults_save_shared_session_meta_and_reset(self):
        defaults = self.client.get('/api/settings/models').json()
        self.assertFalse(defaults['overridden'])
        self.assertEqual(defaults['effective']['classify']['model'],self.settings.classify_model)
        saved = self.save()
        self.assertTrue(saved['overridden'])
        self.assertNotIn('test-only',str(saved))
        with self.sessions() as worker:
            self.assertEqual(model_for(worker,'classify')['model'],'claude-unit-fast')
            self.assertIsNone(model_for(worker,'classify')['effort'])
            self.assertEqual(model_for(worker,'summary')['effort'],'high')
        meta = self.client.get('/api/meta').json()
        self.assertEqual(meta['models'],{'classify':'claude-unit-fast','summary':'claude-unit-deep'})
        reset = self.client.delete('/api/settings/models').json()
        self.assertFalse(reset['overridden'])
        self.assertEqual(reset['effective']['summary']['model'],self.settings.summary_model)

    def test_catalogue_and_validation_are_atomic(self):
        catalogue = self.client.get('/api/models').json()['models']
        self.assertEqual(catalogue[0]['efforts'],[])
        self.assertFalse(catalogue[-1]['structured_outputs'])
        self.save()
        for classify in ({'model':'claude-unit-text','effort':'auto'}, {'model':'claude-unit-fast','effort':'high'}):
            response = self.client.put('/api/settings/models',json={**self.payload,'classify':classify})
            self.assertEqual(response.status_code,400,response.text)
        self.assertEqual(self.db.get(AppSetting,'models').value['classify']['model'],'claude-unit-fast')
        invalid = self.client.put('/api/settings/models',json={**self.payload,'summary':{'model':'invalid','effort':'anything'}})
        self.assertEqual(invalid.status_code,422)
        # Text-only models can still be selected for summaries using provider-default effort.
        self.save({**self.payload,'summary':{'model':'claude-unit-text','effort':'auto'}})

    def test_missing_key_allows_read_reset_but_not_verification(self):
        self.settings.anthropic_api_key = None
        self.assertEqual(self.client.get('/api/models').status_code,400)
        self.assertEqual(self.client.put('/api/settings/models',json=self.payload).status_code,400)
        self.assertEqual(self.client.delete('/api/settings/models').status_code,200)

    def test_classifier_uses_saved_model_and_records_it_without_requeueing_old_articles(self):
        old = Article(url='https://example.com/old',title='Old',title_hash='old',published_at=utcnow(),status='enriched')
        new = Article(url='https://example.com/new',title='New',title_hash='new',published_at=utcnow(),status='pending')
        self.db.add_all([old,new]);self.db.commit()
        self.save()
        self.assertEqual(old.status,'enriched')
        output = dict(relevant=True,event_type='other',region='unknown',countries=[],location={},summary='Summary',pir_matches=[])
        with patch('app.pipeline.classify.get_settings',return_value=self.settings),patch('app.pipeline.classify.llm.call_json',return_value=output) as model:
            self.assertEqual(enrich_pending(self.db),1)
        self.assertEqual(model.call_args.kwargs['model'],'claude-unit-fast')
        self.assertIsNone(model.call_args.kwargs['effort'])
        self.assertEqual(new.model,'claude-unit-fast')
        self.assertIsNone(old.model)

    def test_summary_uses_saved_model_and_caps_tokens(self):
        self.save({**self.payload,'summary':{'model':'claude-unit-fast','effort':'auto'}})
        dashboard = PirSet(name='Test')
        self.db.add(dashboard);self.db.flush()
        summary = Summary(set_id=dashboard.id,period_label='Test',period_start=utcnow()-timedelta(days=1),period_end=utcnow())
        self.db.add(summary);self.db.commit()
        @contextmanager
        def session():
            yield self.db
            self.db.commit()
        with patch('app.pipeline.summarize.session_scope',session),patch('app.pipeline.summarize.llm.call',return_value='Report') as model:
            run_summary(summary.id)
        self.assertEqual(model.call_args.kwargs['model'],'claude-unit-fast')
        self.assertIsNone(model.call_args.kwargs['effort'])
        self.assertEqual(model.call_args.kwargs['max_tokens'],8192)
        self.assertEqual(summary.model,'claude-unit-fast')
        self.assertEqual(summary.status,'done')

    def test_auto_effort_is_not_sent_to_provider(self):
        client = MagicMock()
        client.messages.create.return_value = NS(stop_reason='end_turn',content=[NS(type='text',text='Hello')])
        with patch('app.pipeline.llm.client',return_value=client):
            self.assertEqual(llm.call(model='claude-unit-fast',effort=None,system='System',user='Article',max_tokens=10),'Hello')
        self.assertNotIn('output_config',client.messages.create.call_args.kwargs)
        with patch('app.pipeline.llm.client',return_value=client):
            llm.call(model='claude-unit-fast',effort=None,system='System',user='Article',max_tokens=10,schema={'type':'object'})
        config = client.messages.create.call_args.kwargs['output_config']
        self.assertIn('format',config)
        self.assertNotIn('effort',config)


if __name__=='__main__':unittest.main()
