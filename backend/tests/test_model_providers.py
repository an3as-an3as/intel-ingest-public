"""Offline adapter, credential, compatibility and routing tests. No provider calls."""
import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import Base, get_db
from app.main import app
from app.models import AppSetting, Article, utcnow
from app import model_providers as providers, model_settings
from app.pipeline import llm
from app.pipeline.classify import enrich_pending
from app import worker

SCHEMA = {'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}


def settings(**extra):
    return Settings(_env_file=None, openai_api_key='openai-test-secret', deepseek_api_key='deepseek-test-secret',
                    gemini_api_key='gemini-test-secret', ollama_base_url='http://models.internal:11434',
                    fetch_article_text=False, classify_concurrency=1, **extra)


def response(data, status=200):
    return NS(status_code=status, json=lambda:data)


class ProviderAdapterTests(unittest.TestCase):
    def setUp(self):
        self.st = settings()

    def generate(self, provider, data, **extra):
        with patch('app.model_providers.requests.request', return_value=response(data)) as transport:
            text = providers.generate(provider=provider, model='unit-model', effort=None, system='System',
                                      user='Private article', max_tokens=100, settings=self.st, **extra)
        return text, transport.call_args

    def test_openai_native_schema_and_token_parameter(self):
        text, args = self.generate('openai', {'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]}, schema=SCHEMA)
        self.assertEqual(text, '{"ok":true}')
        self.assertEqual(args.args, ('POST','https://api.openai.com/v1/chat/completions'))
        self.assertEqual(args.kwargs['json']['response_format']['json_schema']['schema'], SCHEMA)
        self.assertEqual(args.kwargs['json']['max_completion_tokens'], 100)
        self.assertFalse(args.kwargs['allow_redirects'])

    def test_deepseek_json_mode_is_not_misrepresented_as_native_schema(self):
        _, args = self.generate('deepseek', {'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]}, schema=SCHEMA)
        body = args.kwargs['json']
        self.assertEqual(body['response_format'], {'type':'json_object'})
        self.assertIn('JSON Schema', body['messages'][0]['content'])
        self.assertEqual(body['max_tokens'], 100)
        self.assertNotIn('max_completion_tokens', body)

    def test_gemini_schema_header_and_thought_blocks(self):
        text, args = self.generate('gemini', {'candidates':[{'finishReason':'STOP','content':{'parts':[
            {'thought':True,'text':'private reasoning'}, {'text':'{"ok":true}'}]}}]}, schema=SCHEMA)
        self.assertEqual(text, '{"ok":true}')
        self.assertEqual(args.kwargs['headers']['x-goog-api-key'], 'gemini-test-secret')
        self.assertNotIn('key=', args.args[1])
        self.assertEqual(args.kwargs['json']['generationConfig']['responseJsonSchema'], SCHEMA)

    def test_ollama_native_schema_and_no_assumed_host_address(self):
        text, args = self.generate('ollama', {'done':True,'done_reason':'stop','message':{'content':'{"ok":true}'}}, schema=SCHEMA)
        self.assertEqual(text, '{"ok":true}')
        self.assertEqual(args.args[1], 'http://models.internal:11434/api/chat')
        self.assertEqual(args.kwargs['json']['format'], SCHEMA)
        self.assertFalse(args.kwargs['json']['stream'])
        self.assertEqual(args.kwargs['json']['options']['num_predict'], 100)
        self.assertNotIn('Authorization', args.kwargs['headers'])

    def test_summary_uses_text_mode_without_schema(self):
        _, args = self.generate('openai', {'choices':[{'finish_reason':'stop','message':{'content':'Report'}}]})
        self.assertNotIn('response_format', args.kwargs['json'])

    def test_refusals_truncation_empty_and_bad_messages_fail_closed(self):
        cases = [('openai', {'choices':[{'finish_reason':'length','message':{'content':'partial'}}]}),
                 ('deepseek', {'choices':[{'finish_reason':'stop','message':{'refusal':'blocked','content':'text'}}]}),
                 ('gemini', {'candidates':[{'finishReason':'MAX_TOKENS'}]}),
                 ('ollama', {'done':True,'done_reason':'length','message':{'content':'partial'}}),
                 ('openai', {'choices':[]}), ('ollama', {'done':True,'message':{}})]
        for provider, data in cases:
            with self.subTest(provider=provider), self.assertRaises(providers.ProviderError):
                self.generate(provider, data)

    def test_http_failure_is_safe_no_retry_or_secret_body(self):
        with patch('app.model_providers.requests.request', return_value=response({'error':'secret article'},429)) as transport:
            with self.assertRaises(providers.ProviderError) as error:
                providers.available_models('openai', self.st)
            self.assertNotIn('openai-test-secret', str(error.exception))
            self.assertNotIn('secret article', str(error.exception))
            self.assertEqual(transport.call_count, 1)

    def test_redirects_and_invalid_urls_cannot_forward_credentials(self):
        with patch('app.model_providers.requests.request', return_value=response({},302)) as transport:
            with self.assertRaises(providers.ProviderError):
                providers.available_models('openai', self.st)
            self.assertFalse(transport.call_args.kwargs['allow_redirects'])
        for url in ('http://cloud.example/v1','https://user:password@cloud.example/v1','https://cloud.example/?key=secret'):
            self.st.openai_base_url = url
            with patch('app.model_providers.requests.request') as transport, self.assertRaises(ValueError):
                providers.available_models('openai', self.st)
            transport.assert_not_called()

    def test_discovery_is_provider_specific_and_does_not_generate(self):
        for provider, data in [('openai',{'data':[{'id':'test-chat'}]}),
                               ('deepseek',{'data':[{'id':'test-chat'}]}),
                               ('ollama',{'models':[{'name':'qwen-local:8b'}]})]:
            with self.subTest(provider=provider), patch('app.model_providers.requests.request', return_value=response(data)) as transport:
                models = providers.available_models(provider, self.st)
                self.assertEqual(models[0]['provider'], provider)
                self.assertEqual(models[0]['efforts'], [])
                self.assertIsNone(models[0]['structured_outputs'])
                self.assertEqual(transport.call_args.args[0], 'GET')

    def test_gemini_discovery_pages_and_filters_non_generate_models(self):
        replies = [response({'models':[{'name':'models/unit-gemini','supportedGenerationMethods':['generateContent'], 'outputTokenLimit':2048}], 'nextPageToken':'page2'}),
                   response({'models':[{'name':'models/embed-only','supportedGenerationMethods':['embedContent']}]})]
        with patch('app.model_providers.requests.request', side_effect=replies) as transport:
            models = providers.available_models('gemini', self.st)
        self.assertEqual([m['id'] for m in models], ['unit-gemini'])
        self.assertEqual(models[0]['max_tokens'], 2048)
        self.assertEqual(transport.call_args.kwargs['params']['pageToken'], 'page2')

    def test_local_endpoint_is_explicit_and_effort_rejected_before_generation(self):
        self.assertFalse(providers.configured('ollama', Settings(_env_file=None)))
        with patch('app.model_providers.requests.request') as transport, self.assertRaises(providers.ProviderError):
            providers.generate(provider='ollama',model='unit',effort='high',system='s',user='u',max_tokens=10,settings=self.st)
        transport.assert_not_called()

    def test_local_schema_validation_rejects_valid_but_wrong_json(self):
        for output in ('{"ok":"wrong"}', '[]', 'not json'):
            with patch('app.pipeline.llm.call', return_value=output), self.assertRaises(llm.LLMError):
                llm.call_json(provider='openai',schema=SCHEMA)
        with patch('app.pipeline.llm.call', return_value='{"ok":true}'):
            self.assertEqual(llm.call_json(provider='ollama',schema=SCHEMA), {'ok':True})


class ProviderSettingsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine,expire_on_commit=False)()
        app.dependency_overrides[get_db] = lambda:self.db
        self.client = TestClient(app)
        self.st = settings()
        self.patches = [patch('app.model_settings.get_settings', return_value=self.st),
                        patch('app.main.get_settings', return_value=self.st)]
        for p in self.patches:p.start()
        self.payload = {'classify':{'provider':'openai','model':'test-chat','effort':'auto'},
                        'summary':{'provider':'ollama','model':'qwen-local:8b','effort':'auto'}}

    def tearDown(self):
        for p in self.patches:p.stop()
        app.dependency_overrides.clear();self.client.close();self.db.close();self.engine.dispose()

    def discovery(self, provider, *args):
        return [providers._info(provider, 'qwen-local:8b' if provider=='ollama' else 'test-chat')]

    def save(self):
        with patch('app.model_providers.available_models', side_effect=self.discovery):
            r = self.client.put('/api/settings/models',json=self.payload)
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def test_save_mixed_providers_without_anthropic_and_preserve_secrets(self):
        saved = self.save()
        self.assertEqual(saved['effective']['classify']['provider'],'openai')
        self.assertTrue(saved['effective']['summary']['configured'])
        self.assertNotIn('test-secret', json.dumps(saved))
        self.assertNotIn('models.internal', json.dumps(saved))
        self.assertEqual(model_settings.model_for(self.db,'summary',self.st)['max_tokens'],8192)
        stored = self.db.get(AppSetting,'models').value
        self.assertNotIn('api_key',json.dumps(stored))

    def test_missing_provider_key_and_failed_validation_do_not_change_preferences(self):
        self.save()
        old = json.loads(json.dumps(self.db.get(AppSetting,'models').value))
        bad = {**self.payload,'classify':{'provider':'openai','model':'unknown','effort':'auto'}}
        with patch('app.model_providers.available_models', side_effect=self.discovery):
            self.assertEqual(self.client.put('/api/settings/models',json=bad).status_code,400)
        self.assertEqual(self.db.get(AppSetting,'models').value,old)
        self.st.openai_api_key = None
        self.assertEqual(self.client.get('/api/models?provider=openai').status_code,400)
        self.assertEqual(self.client.put('/api/settings/models',json=self.payload).status_code,400)
        self.assertEqual(self.client.get('/api/models?provider=unknown').status_code,422)

    def test_legacy_claude_choices_do_not_inherit_new_environment_provider(self):
        self.db.add(AppSetting(key='models',value={'classify':{'model':'claude-legacy','effort':'low'}}));self.db.commit()
        self.st.classify_provider = 'openai'
        config = model_settings.model_for(self.db,'classify',self.st)
        self.assertEqual(config['provider'],'anthropic')
        self.assertEqual(model_settings.result_model(config),'claude-legacy')

    def test_classifier_routes_provider_and_records_provenance(self):
        self.save()
        article = Article(url='https://example.test/new',title='Article',title_hash='test',published_at=utcnow(),status='pending')
        self.db.add(article);self.db.commit()
        output={'relevant':True,'event_type':'other','region':'unknown','countries':[],'location':{},'summary':'Test','pir_matches':[]}
        with patch('app.pipeline.classify.get_settings',return_value=self.st), patch('app.pipeline.classify.llm.call_json',return_value=output) as generate:
            self.assertEqual(enrich_pending(self.db),1)
        self.assertEqual(generate.call_args.kwargs['provider'],'openai')
        self.assertEqual(article.model,'openai:test-chat')

    def test_schema_mismatch_fails_article_instead_of_applying_empty_classification(self):
        self.save()
        article=Article(url='https://example.test/invalid',title='Test',title_hash='invalid',published_at=utcnow(),status='pending')
        self.db.add(article);self.db.commit()
        with patch('app.pipeline.classify.get_settings',return_value=self.st), \
             patch('app.pipeline.llm.model_providers.generate',return_value='{}'):
            self.assertEqual(enrich_pending(self.db),0)
        self.assertEqual(article.status,'failed')
        self.assertIsNone(article.ai_summary)
        self.assertIn('classification was not applied',article.error)

    def test_summary_routes_local_provider_and_records_provenance(self):
        self.save()
        from contextlib import contextmanager
        from app.models import PirSet,Summary
        from app.pipeline.summarize import run_summary
        from datetime import timedelta
        dashboard=PirSet(name='Local summary');self.db.add(dashboard);self.db.flush()
        job=Summary(set_id=dashboard.id,period_label='Test',period_start=utcnow()-timedelta(days=1),period_end=utcnow())
        self.db.add(job);self.db.commit()
        @contextmanager
        def session():
            yield self.db
            self.db.commit()
        with patch('app.pipeline.summarize.session_scope',session), patch('app.pipeline.summarize.llm.call',return_value='Report') as generate:
            run_summary(job.id)
        self.assertEqual(generate.call_args.kwargs['provider'],'ollama')
        self.assertEqual(job.model,'ollama:qwen-local:8b')
        self.assertEqual(job.status,'done')

    def test_worker_handles_providers_independently_without_anthropic_key(self):
        self.save()
        # Classifier unavailable, local summary available. Neither should block the other.
        self.st.openai_api_key=None
        from contextlib import contextmanager
        @contextmanager
        def session():
            yield self.db
        with patch('app.worker.session_scope',session), patch('app.worker.get_settings',return_value=self.st), \
             patch('app.worker.next_pending_ids',return_value=[1]), patch('app.worker.run_summary',return_value=True) as summarize, \
             patch('app.worker.enrich_pending') as classify:
            worker.tick()
        summarize.assert_called_once_with(1);classify.assert_not_called()

    def test_summary_queue_accepts_configured_non_anthropic_provider(self):
        self.save()
        from app.models import PirSet
        dashboard=PirSet(name='Provider test');self.db.add(dashboard);self.db.commit()
        result=self.client.post(f'/api/pir-sets/{dashboard.id}/summaries',json={'period':'7d'})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['status'],'pending')
