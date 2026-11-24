"""Country-aware query translation: local packs/cache, strict review, mocked providers."""
import copy
import json
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import Base, get_db
from app.main import app
from app.models import KeywordTranslationCache, KeywordTranslationReview, SourceProfile, utcnow
from app.sources import keyword_translation as kt
from app.sources.newscatcher import NewsCatcherSource, build_requests


class KeywordTranslationTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
        Base.metadata.create_all(self.engine)
        self.db=sessionmaker(bind=self.engine,expire_on_commit=False)()
        app.dependency_overrides[get_db]=lambda:self.db
        self.client=TestClient(app)
        self.params={'keywords':['Baltic Sea'],'event_presets':['cyber'],'coverage_countries':['DK'],
                     'multilingual_enabled':True,'translation_auto_languages':True,'max_requests_per_poll':16}
        self.live=Settings(_env_file=None,anthropic_api_key='fixture-only',keyword_translation_allow_live=True)

    def tearDown(self):
        app.dependency_overrides.clear();self.client.close();self.db.close();self.engine.dispose()

    def plan(self,params=None):
        review=kt.create_review(self.db,params or self.params)
        self.db.commit()
        return review

    def decisions(self,review,*,keep_missing=False):
        return [{'id':row['id'],'translations':row['candidates'],
                 'keep_original':bool(keep_missing and not row['candidates'])} for row in review.payload['rows']]

    def approved(self,params=None):
        params=copy.deepcopy(params or self.params)
        review=self.plan(params)
        kt.approve_review(self.db,review.id,params,self.decisions(review))
        self.db.commit()
        params['translation_review_id']=review.id
        return params,kt.load_approved(self.db,params)

    def test_suggestions_are_country_aware_multilingual_and_deduplicated(self):
        self.assertEqual(kt.suggested_languages(['FI','SE','FI']),['fi','sv'])
        self.assertEqual(kt.suggested_languages(['DK']),['da'])
        self.assertEqual(kt.suggested_languages(['US','GB']),[])
        self.assertEqual(kt.target_languages({**self.params,'source_countries':['RU']}),['da'])
        manual={**self.params,'translation_auto_languages':False,'translation_languages':['sv','da','sv']}
        self.assertEqual(kt.target_languages(manual),['da','sv'])

    def test_draft_defers_request_cap_but_approval_preview_save_and_runtime_do_not(self):
        params = {**self.params, 'query_planner_version':'bounded-v1',
                  'keywords':[f'concept {i:03d} ' + 'network '*20 for i in range(80)]}
        with patch('app.sources.newscatcher.requests.post') as provider:
            draft = self.client.post('/api/ingestion/translation-plans', json={'params':params})
            self.assertEqual(draft.status_code, 200)
            self.assertLess(len(draft.json()['rows']), kt.MAX_ROWS)
            review = self.db.get(KeywordTranslationReview, draft.json()['id'])
            approved = self.client.post(f'/api/ingestion/translation-plans/{review.id}/approve',
                                       json={'params':params, 'decisions':self.decisions(review, keep_missing=True), 'confirmed':True})
            self.assertEqual(approved.status_code, 400, approved.text)
            self.assertIn('global ceiling is already reached', approved.json()['detail'])
            self.db.rollback()
            self.assertIsNone(self.db.get(KeywordTranslationReview, review.id).approved_at)
            collection = {**params, 'multilingual_enabled':False}
            payload = {'name':'Collection still guarded', 'params':collection, 'translation_draft':True}
            for path in ('/api/profiles/preview-query', '/api/profiles'):
                response = self.client.post(path, json=payload)
                self.assertEqual(response.status_code, 422)
                self.assertIn('global ceiling is already reached', response.text)
            source = NewsCatcherSource()
            with patch.object(source, '_plan', return_value={}):
                with self.assertRaisesRegex(ValueError, 'global ceiling is already reached'):
                    source._fetch_news(SimpleNamespace(newscatcher_api_key='fixture', newscatcher_effort='low'),
                                       collection, utcnow()-timedelta(hours=1), utcnow())
            provider.assert_not_called()
        self.assertEqual(self.db.scalar(select(func.count()).select_from(SourceProfile)), 0)

    def test_draft_validation_errors_are_concise_and_still_check_settings(self):
        invalid = {**self.params, 'max_requests_per_poll':17}
        response = self.client.post('/api/ingestion/translation-plans', json={'params':invalid})
        self.assertEqual(response.status_code, 400)
        self.assertIn('max_requests_per_poll', response.json()['detail'])
        self.assertNotIn('input_value', response.json()['detail'])
        self.assertEqual(self.db.scalar(select(func.count()).select_from(KeywordTranslationReview)), 0)

    def test_oversized_review_explains_counts_without_cache_or_model_calls(self):
        with patch.object(kt, 'MAX_ROWS', 1), patch('anthropic.Anthropic') as provider:
            with self.assertRaisesRegex(ValueError, r'5 phrase/language rows \(5 phrases including country names.*1 target languages') as error:
                self.plan()
            self.assertIn('Article-language filtering alone', str(error.exception))
            self.assertIn('No translation model was called', str(error.exception))
            provider.assert_not_called()
        self.assertEqual(self.db.scalar(select(func.count()).select_from(KeywordTranslationReview)), 0)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(KeywordTranslationCache)), 0)

    def test_country_map_and_offline_pack_have_valid_codes_and_aligned_rows(self):
        from app.sources.options import COUNTRIES,LANGUAGES
        self.assertTrue(set(kt.MAPPING['countries'])<=set(COUNTRIES))
        for languages in kt.MAPPING['countries'].values():
            self.assertTrue(set(languages)<=set(LANGUAGES))
        for table in [kt.PACK['keywords'],*kt.PACK['events'].values()]:
            for translations in table.values():
                self.assertEqual(len(translations),len(kt.PACK['languages']))
                self.assertTrue(all(isinstance(t,str) and t for t in translations))

    def test_plan_uses_offline_pack_country_names_and_cache_without_network(self):
        with patch('requests.post') as post,patch('requests.get') as get,patch.object(kt,'_model_candidates') as model:
            review=self.plan()
            data=kt.serialize_review(review,self.params)
            self.assertEqual(data['missing_count'],0)
            self.assertEqual(data['languages'],['da'])
            country=next(r for r in data['rows'] if r['kind']=='places')
            self.assertIn('Danmark',country['candidates'])
            baltic=next(r for r in data['rows'] if r['source']=='Baltic Sea')
            self.assertEqual(baltic['candidates'],['Østersøen'])
            count=self.db.scalar(select(func.count()).select_from(KeywordTranslationCache))
            cached=self.plan()
            self.assertTrue(all(row['origin'].startswith('cache:') for row in cached.payload['rows']))
            self.assertEqual(self.db.scalar(select(func.count()).select_from(KeywordTranslationCache)),count)
            get.assert_not_called();post.assert_not_called();model.assert_not_called()

    def test_source_language_and_event_context_are_part_of_the_cache_key(self):
        english=self.plan({**self.params,'keywords':['pain'],'keyword_source_language':'en'})
        french=self.plan({**self.params,'keywords':['pain'],'keyword_source_language':'fr'})
        en_row=next(r for r in english.payload['rows'] if r['kind']=='keywords')
        fr_row=next(r for r in french.payload['rows'] if r['kind']=='keywords')
        self.assertNotEqual(en_row['id'],fr_row['id'])
        self.assertIn('cyber',en_row['contexts'])
        self.assertEqual(fr_row['source_language'],'fr')

    def test_manual_missing_phrase_is_explicit_and_never_partially_approved(self):
        params={**self.params,'keywords':['Unmapped company 42']}
        review=self.plan(params)
        self.assertEqual(kt.serialize_review(review,params)['missing_count'],1)
        with self.assertRaisesRegex(ValueError,'one to three'):
            kt.approve_review(self.db,review.id,params,self.decisions(review))
        self.db.rollback()
        self.assertIsNone(self.db.get(KeywordTranslationReview,review.id).approved_at)
        review=self.db.get(KeywordTranslationReview,review.id)
        decisions=self.decisions(review,keep_missing=True)
        kt.approve_review(self.db,review.id,params,decisions);self.db.commit()
        approved={**params,'translation_review_id':review.id}
        snapshot=kt.load_approved(self.db,approved)
        self.assertIn('Unmapped company 42',snapshot.groups['da'][0])
        self.assertEqual(kt.serialize_review(review,approved)['missing_count'],0)

    def test_language_restrictions_and_native_exclusions_are_not_widened(self):
        params={**self.params,'languages':['en']}
        review=self.plan(params)
        self.assertEqual(kt.serialize_review(review,params)['language_conflicts'],['da'])
        with self.assertRaisesRegex(ValueError,'filter conflicts'):
            kt.approve_review(self.db,review.id,params,self.decisions(review))
        self.db.rollback()
        self.assertEqual(kt.language_conflicts({**self.params,'native_filters':{'not_languages':['da']}},['da']),['da'])
        self.assertEqual(kt.language_conflicts({**self.params,'languages':['en','da']},['da']),[])

    def test_chinese_aliases_respect_endpoint_semantics(self):
        p={**self.params,'languages':['zh']}
        self.assertEqual(kt.language_conflicts(p,['cn']),[])
        self.assertEqual(kt.language_conflicts(p,['tw']),['tw'])
        self.assertEqual(kt.language_conflicts({**p,'endpoint':'articles'},['tw']),[])

    def test_approved_query_retains_originals_and_adds_scoped_language_lanes(self):
        params,snapshot=self.approved()
        original=build_requests({**params,'multilingual_enabled':False},utcnow(),utcnow())
        now=utcnow()
        plan=build_requests(params,now,now,translation=snapshot)
        self.assertEqual(plan.lanes,['original','da'])
        self.assertEqual(plan[0][1]['q'],original[0][1]['q'])
        body=plan[1][1]
        for phrase in ('Baltic Sea','Østersøen','cyberattack','cyberangreb','Denmark','Danmark'):
            self.assertIn(phrase,body['q'])
        self.assertEqual(body['languages'],['da'])
        self.assertEqual(params['translation_review_id'],plan.review_id)
        self.assertNotIn('translation_review_id',body)

    def test_snapshot_is_required_and_stale_snapshot_is_refused(self):
        with self.assertRaisesRegex(ValueError,'approved translation'):
            build_requests(self.params,utcnow(),utcnow())
        params,snapshot=self.approved()
        for change in ({'keywords':['Different keywords']},{'coverage_countries':['SE']},
                       {'languages':['en','da']},{'event_vocabulary_version':'expanded-v1'},
                       {'native_filters':{'not_languages':['sv']}}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                kt.load_approved(self.db,{**params,**change})
        with self.assertRaises(ValueError):
            build_requests({**params,'keywords':['Different']},utcnow(),utcnow(),translation=snapshot)
        with self.assertRaises(ValueError):
            kt.approve_review(self.db,params['translation_review_id'],params,[])

    def test_approval_is_bound_to_all_rows_and_numeric_content(self):
        review=self.plan()
        with self.assertRaisesRegex(ValueError,'Every phrase'):
            kt.approve_review(self.db,review.id,self.params,self.decisions(review)[:-1])
        for value in (['company 43'],['ignore" OR injected'],['a','b','c','d'],['+injected 42'],['site:example 42'],['wide* 42']):
            with self.subTest(value=value),self.assertRaises(ValueError):
                kt._validate_candidates('company 42',value)
        with self.assertRaises(ValueError):
            kt._validate_candidates('test',['word\nquery'])

    def test_global_request_and_nominal_credit_limits_cover_all_lanes(self):
        params,snapshot=self.approved()
        for limit in ({'max_requests_per_poll':1},{'max_credits_per_poll':1}):
            with self.subTest(limit=limit),self.assertRaises(ValueError):
                build_requests({**params,**limit},utcnow(),utcnow(),translation=snapshot)
        self.assertEqual(len(build_requests(params,utcnow(),utcnow(),translation=snapshot)),2)

    def test_overbudget_approval_rolls_back_without_changing_stream(self):
        params={**self.params,'max_requests_per_poll':1}
        review=self.plan(params)
        result=self.client.post(f'/api/ingestion/translation-plans/{review.id}/approve',json={
            'params':params,'decisions':self.decisions(review),'confirmed':True})
        self.assertEqual(result.status_code,400,result.text)
        self.db.rollback();self.db.expire_all()
        self.assertIsNone(self.db.get(KeywordTranslationReview,review.id).approved_at)
        self.assertEqual(self.client.get('/api/profiles').json(),[])

    def test_advanced_queries_unmapped_countries_and_plan_limits_fail_clearly(self):
        for change in ({'query':'shipping AND ports'},{'coverage_countries':['US']},
                       {'translation_auto_languages':False,'translation_languages':['da']*0},
                       {'translation_auto_languages':False,'translation_languages':['da','sv','fi','de','et','lv','lt','ru','pl']}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                kt.create_review(self.db,{**self.params,**change})
        with self.assertRaisesRegex(ValueError,'phrase/language rows'):
            kt.create_review(self.db,{**self.params,'event_presets':['cyber','infrastructure','military_activity','maritime'],
                                     'event_vocabulary_version':'expanded-v1','event_vocabulary_tiers':['core','indicators','discovery'],
                                     'translation_auto_languages':False,'translation_languages':kt.PACK['languages']})

    def test_default_is_off_and_live_generation_requires_explicit_deployment_flag(self):
        self.assertIsNone(kt.load_approved(self.db,{'keywords':['shipping']}))
        review=self.plan({**self.params,'keywords':['Unmapped phrase']})
        disabled=Settings(_env_file=None,keyword_translation_allow_live=False,anthropic_api_key='fixture')
        with patch.object(kt,'get_settings',return_value=disabled),patch.object(kt,'_model_candidates') as model:
            with self.assertRaisesRegex(ValueError,'Live translation is disabled'):
                kt.generate_missing(self.db,review.id)
            model.assert_not_called()
        self.assertEqual(review.model_calls,0)

    def test_model_generation_is_once_per_review_cached_and_never_auto_approved(self):
        params={**self.params,'keywords':['Unmapped phrase']}
        review=self.plan(params)
        def generated(rows):return [{'id':row['id'],'terms':['Oversat udtryk']} for row in rows]
        with patch.object(kt,'get_settings',return_value=self.live),patch.object(kt,'_model_candidates',side_effect=generated) as model:
            result=kt.generate_missing(self.db,review.id);self.db.commit()
            self.assertEqual(model.call_count,1)
            self.assertIsNone(result.approved_at)
            with self.assertRaisesRegex(ValueError,'one permitted model call'):
                kt.generate_missing(self.db,review.id)
        next_review=self.plan(params)
        self.assertEqual(kt.serialize_review(next_review,params)['missing_count'],0)
        self.assertIsNone(next_review.approved_at)

    def test_failed_generation_counts_attempt_without_partial_cache_or_exception_leak(self):
        review=self.plan({**self.params,'keywords':['Unknown phrase']})
        with patch.object(kt,'get_settings',return_value=self.live),patch.object(kt,'_model_candidates',side_effect=RuntimeError('secret-provider-body')):
            with self.assertRaises(ValueError) as error:
                kt.generate_missing(self.db,review.id)
        self.assertNotIn('secret-provider-body',str(error.exception))
        self.db.rollback();self.db.expire_all()
        saved=self.db.get(KeywordTranslationReview,review.id)
        self.assertEqual(saved.model_calls,1)
        self.assertEqual(kt.serialize_review(saved)['missing_count'],1)
        self.assertIsNone(saved.approved_at)

    def test_incomplete_model_response_is_not_partially_applied(self):
        review=self.plan({**self.params,'keywords':['First missing','Second missing']})
        with patch.object(kt,'get_settings',return_value=self.live),patch.object(kt,'_model_candidates',return_value=[]):
            with self.assertRaises(ValueError):kt.generate_missing(self.db,review.id)
        self.db.rollback();self.db.expire_all()
        self.assertEqual(kt.serialize_review(self.db.get(KeywordTranslationReview,review.id))['missing_count'],2)

    def test_generation_cannot_overwrite_a_snapshot_approved_during_the_call(self):
        params={**self.params,'keywords':['Unknown phrase']}
        review=self.plan(params)
        def concurrent_approval(rows):
            kt.approve_review(self.db,review.id,params,self.decisions(review,keep_missing=True))
            self.db.commit()
            return [{'id':row['id'],'terms':['Forslag efter godkendelse']} for row in rows]
        with patch.object(kt,'get_settings',return_value=self.live),patch.object(kt,'_model_candidates',side_effect=concurrent_approval):
            with self.assertRaisesRegex(ValueError,'immutable/approved'):
                kt.generate_missing(self.db,review.id)
        self.db.rollback();self.db.expire_all()
        saved=self.db.get(KeywordTranslationReview,review.id)
        self.assertIsNotNone(saved.approved_at)
        row=next(row for row in saved.payload['rows'] if row['source']=='Unknown phrase')
        self.assertEqual(row['approved_terms'],['Unknown phrase'])

    def test_expired_drafts_fail_but_approved_snapshots_do_not_expire(self):
        review=self.plan();review.created_at=utcnow()-timedelta(days=2);self.db.commit()
        with self.assertRaisesRegex(ValueError,'expired'):
            kt.approve_review(self.db,review.id,self.params,self.decisions(review))
        params,_=self.approved()
        saved=self.db.get(KeywordTranslationReview,params['translation_review_id'])
        saved.created_at=utcnow()-timedelta(days=100);self.db.commit()
        self.assertIsNotNone(kt.load_approved(self.db,params))

    def test_api_review_preview_save_reload_and_rejected_stale_edit(self):
        with patch('requests.post') as post,patch('requests.get') as get,patch.object(kt,'_model_candidates') as model:
            plan=self.client.post('/api/ingestion/translation-plans',json={'params':self.params})
            self.assertEqual(plan.status_code,200,plan.text)
            draft=plan.json()
            decisions=[{'id':r['id'],'translations':r['candidates'],'keep_original':False} for r in draft['rows']]
            approved=self.client.post(f'/api/ingestion/translation-plans/{draft["id"]}/approve',json={'params':self.params,'decisions':decisions,'confirmed':True})
            self.assertEqual(approved.status_code,200,approved.text)
            params={**self.params,**approved.json()['params_patch']}
            payload={'name':'Local multilingual test','enabled':False,'interval_minutes':60,'params':params}
            preview=self.client.post('/api/profiles/preview-query',json=payload)
            self.assertEqual(preview.status_code,200,preview.text)
            self.assertEqual(preview.json()['translations']['languages'],['da'])
            self.assertEqual(preview.json()['estimated_credits_per_poll'],2)
            self.assertEqual(preview.json()['request_count'],2)
            self.assertEqual(self.client.get('/api/profiles').json(),[])
            saved=self.client.post('/api/profiles',json=payload)
            self.assertEqual(saved.status_code,200,saved.text)
            loaded=self.client.get('/api/profiles').json()[0]
            self.assertEqual(loaded['params'],params)
            self.assertFalse(loaded['enabled'])
            bad=self.client.put(f'/api/profiles/{loaded["id"]}',json={**payload,'params':{**params,'keywords':['Changed']}})
            self.assertEqual(bad.status_code,400,bad.text)
            self.db.rollback();self.db.expire_all()
            self.assertEqual(self.db.get(SourceProfile,loaded['id']).params,params)
            get.assert_not_called();post.assert_not_called();model.assert_not_called()

    def test_api_disallows_missing_approval_and_gdelt_expansion(self):
        response=self.client.post('/api/profiles',json={'name':'Invalid','params':self.params})
        self.assertEqual(response.status_code,422,response.text)
        response=self.client.post('/api/profiles',json={'name':'Invalid','source':'gdelt','params':self.params})
        self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.client.get('/api/ingestion/translation-plans/not-found').status_code,404)

    def test_enterprise_fetches_every_language_lane_and_deduplicates_shared_urls(self):
        params={**self.params,'endpoint':'v3','coverage_countries':['FI']}
        with patch('app.sources.newscatcher_filters.get_settings',return_value=SimpleNamespace(newscatcher_api='v3')):
            params,snapshot=self.approved(params)
            response=SimpleNamespace(status_code=200,headers={},json=lambda:{'articles':[
                {'link':'https://example.test/shared','title':'Synthetic multilingual report'}]})
            with patch('app.sources.newscatcher._throttle'),patch('app.sources.newscatcher.requests.get',return_value=response) as get:
                result=NewsCatcherSource()._fetch_v3('fixture-only',params,utcnow(),utcnow(),translation=snapshot)
            self.assertEqual(get.call_count,3)
            self.assertEqual(len(result),1)
            self.assertEqual(result[0].extra['_query_parts'],[1,2,3])
            self.assertEqual([m['translation_language'] for m in result.request_metrics],['original','fi','sv'])
            self.assertTrue(all(m['estimated_credits'] is None for m in result.request_metrics))

    def test_polling_loads_frozen_snapshot_without_calling_translation_models(self):
        from app.pipeline.ingest import run_profile
        from app.models import Article, IngestRun
        params,_=self.approved()
        profile=SourceProfile(name='Snapshot poll',source='newscatcher',enabled=False,params=params)
        self.db.add(profile);self.db.commit()
        source=NewsCatcherSource()
        config=SimpleNamespace(newscatcher_api='news',newscatcher_api_key='fixture',newscatcher_effort='low')
        response=SimpleNamespace(status_code=200,headers={},json=lambda:{'results':[
            {'url':'https://example.test/shared','title':'Synthetic translated news report'}]})
        with patch('app.pipeline.ingest.SOURCES',{'newscatcher':source}), \
                patch('app.sources.newscatcher.get_settings',return_value=config), \
                patch.object(source,'_plan',return_value={}),patch('app.sources.newscatcher._throttle'), \
                patch('app.sources.newscatcher.requests.post',return_value=response) as post, \
                patch.object(kt,'_model_candidates') as model:
            self.assertEqual(run_profile(self.db,profile),1);self.db.commit()
            self.assertEqual(run_profile(self.db,profile),0);self.db.commit()
            self.assertEqual(post.call_count,4)
            model.assert_not_called()
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Article)),1)
        run=self.db.scalar(select(IngestRun).order_by(IngestRun.id.desc()))
        self.assertEqual([m['translation_language'] for m in run.request_metrics],['original','da'])
        self.assertTrue(all(m['translation_review_id']==params['translation_review_id'] for m in run.request_metrics))

    def test_sdk_generation_has_no_retries_no_fallback_and_bounded_output(self):
        row={'id':'row','source':'Unknown phrase','contexts':['user-keyword'],'language':'da'}
        message=SimpleNamespace(stop_reason='end_turn',content=[SimpleNamespace(type='text',text=json.dumps({'translations':[{'id':'row','terms':['Ukendt udtryk']}]}))])
        with patch.object(kt,'get_settings',return_value=self.live),patch('anthropic.Anthropic') as sdk:
            sdk.return_value.__enter__.return_value.messages.create.return_value=message
            self.assertEqual(kt._model_candidates([row])[0]['id'],'row')
            self.assertEqual(sdk.call_args.kwargs['max_retries'],0)
            self.assertEqual(sdk.call_args.kwargs['timeout'],30)
            kwargs=sdk.return_value.__enter__.return_value.messages.create.call_args.kwargs
            self.assertEqual(kwargs['max_tokens'],4000)
            self.assertNotIn('fallbacks',kwargs)


if __name__=='__main__':unittest.main()
