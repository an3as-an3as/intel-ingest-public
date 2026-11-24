"""Versioned vocabulary/compiler tests; no real provider calls or article ingestion."""
import copy
import hashlib
import itertools
import json
import shlex
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import IngestRun, SourceProfile
from app.pipeline.ingest import run_profile
from app.sources.event_vocabulary import LEGACY_QUERIES, LIBRARIES, selected_terms, settings, summary
from app.sources.newscatcher import SCHEMAS, NewsCatcherSource, build_q, build_requests
from app.taxonomy import EVENT_TYPE_LABELS

NOW=datetime(2026,1,10,12,tzinfo=timezone.utc)


def tokens(query):
    lexer=shlex.shlex(query,posix=True,punctuation_chars='()')
    lexer.whitespace_split=True
    lexer.commenters=''
    # shlex can group consecutive parentheses; generated nested raw queries need individual tokens.
    return [token for value in lexer for token in (list(value) if set(value)<=set('()') else [value])]


def evaluate(query, present):
    values=tokens(query)
    position=0
    def atom():
        nonlocal position
        value=values[position]; position+=1
        if value=='(':
            result=or_group()
            assert values[position]==')'
            position+=1
            return result
        return value in present
    def and_group():
        nonlocal position
        result=atom()
        while position<len(values) and values[position] in ('AND','NOT'):
            operator=values[position]; position+=1
            right=atom()
            result=result and (not right if operator=='NOT' else right)
        return result
    def or_group():
        nonlocal position
        result=and_group()
        while position<len(values) and values[position]=='OR':
            position+=1
            right=and_group()
            result=result or right
        return result
    result=or_group()
    assert position==len(values),(query,values[position:])
    return result


class VocabularyCompilerTests(unittest.TestCase):
    def expanded(self, **overrides):
        return {'event_presets':['cyber'],'event_vocabulary_version':'expanded-v1',
                'event_vocabulary_tiers':['core','indicators','discovery'],
                'coverage_countries':['EE','LV','LT'],'keywords':['Baltic Sea'],
                'exclude_keywords':['sport'],**overrides}

    def test_legacy_snapshot_is_frozen_and_default_query_is_unchanged(self):
        digest=hashlib.sha256(json.dumps(LEGACY_QUERIES,sort_keys=True).encode()).hexdigest()
        self.assertEqual(digest,'26dfde356807bb8e19119ea9bfa69e0fb4cbc723b69c9469ca0d4e7f968ed053')
        params={'event_presets':['cyber'],'coverage_countries':['FI'],'keywords':['shipping'],'exclude_keywords':['sport']}
        self.assertEqual(build_q(params),'shipping AND (cyberattack OR ransomware OR "data breach") AND (Finland) NOT sport')
        explicit={**params,'event_vocabulary_version':'legacy-v1','event_vocabulary_tiers':['core']}
        self.assertEqual(build_requests(params,NOW,NOW),build_requests(explicit,NOW,NOW))

    def test_all_categories_have_curated_tiers_and_no_duplicate_terms_within_tier(self):
        for version,library in LIBRARIES.items():
            self.assertEqual(set(library['events']),set(EVENT_TYPE_LABELS)-{'other'})
            for event,tiers in library['events'].items():
                self.assertIn('core',tiers)
                for tier,terms in tiers.items():
                    self.assertTrue(terms,(version,event,tier))
                    self.assertEqual(len(terms),len(set(terms)))
                    self.assertTrue(all(isinstance(t,str) and t.strip()==t and t for t in terms))
                    self.assertTrue(all('"' not in t and '\\' not in t for t in terms))

    def test_discovery_is_opt_in_and_removed_legacy_terms_are_visible(self):
        params={'event_presets':['military_activity'],'event_vocabulary_version':'expanded-v1'}
        core=selected_terms(params)
        self.assertIn('reservist call-up',core)
        self.assertNotIn('military',core)
        self.assertIn('military',summary(params)['removed_vs_legacy'])
        broad=selected_terms({**params,'event_vocabulary_tiers':['core','discovery']})
        self.assertIn('military',broad)
        self.assertIn('military mobilisation',core)
        self.assertIn('military mobilization',core)

    def test_one_large_preset_splits_inside_terms_without_dropping_filters(self):
        params=self.expanded(native_filters={'min_newsrooms':2,'not_sources':['example.test']},languages=['en'],source_countries=['GB'])
        original=copy.deepcopy(params)
        parts=build_requests(params,NOW-timedelta(hours=1),NOW)
        self.assertGreater(len(parts),1)
        found=set()
        for mode,body in parts:
            self.assertEqual(mode,'search')
            self.assertLessEqual(len(body['q']),500)
            found.update(tokens(body['q']))
            for country in ('Estonia','Latvia','Lithuania'):
                self.assertIn(country,tokens(body['q']))
            self.assertIn('Baltic Sea',tokens(body['q']))
            self.assertIn(' NOT sport',body['q'])
            self.assertEqual(body['min_newsrooms'],2)
            self.assertEqual(body['not_sources'],['example.test'])
            self.assertEqual(body['languages'],['en'])
            self.assertEqual(body['countries'],['GB'])
        self.assertTrue(set(selected_terms(params))<=found)
        self.assertEqual(params,original)

    def test_split_union_is_logically_equivalent_exhaustively(self):
        params={'keywords':['ports','logistics'],'event_presets':['cyber'],'coverage_countries':['FI','SE'],
                'exclude_keywords':['football'], 'query_planner_version':'bounded-v1'}
        original=build_q(params)
        with patch.dict(SCHEMAS['search']['q'],{'maxLength':60}):
            parts=build_requests(params,NOW,NOW)
        self.assertGreater(len(parts),6)  # Force partitions across multiple AND groups, not just events.
        universe=['ports','logistics','cyberattack','ransomware','data breach','Finland','Sweden','football']
        for booleans in itertools.product((False,True),repeat=len(universe)):
            present={t for t,enabled in zip(universe,booleans) if enabled}
            self.assertEqual(evaluate(original,present),any(evaluate(body['q'],present) for _,body in parts),present)

    def test_raw_advanced_query_is_not_partitioned_or_rewritten(self):
        raw='(ports OR logistics) AND (strike OR blockade)'
        params=self.expanded(query=raw)
        for _,body in build_requests(params,NOW,NOW):
            self.assertIn('('+raw+')',body['q'])
        with self.assertRaisesRegex(ValueError,'Shorten the advanced query'):
            build_requests({'query':'x'*501},NOW,NOW)

    def test_literal_lists_cannot_inject_boolean_structure(self):
        self.assertEqual(build_q({'keywords':['OR'], 'query_planner_version':'bounded-v1'}),'"OR"')
        self.assertEqual(build_q({'keywords':['rail(way)'], 'query_planner_version':'bounded-v1'}),'"rail(way)"')
        for literal in ('bad" OR injected',r'bad\path'):
            with self.assertRaisesRegex(ValueError,'Use Advanced query'):
                build_requests({'keywords':[literal], 'query_planner_version':'bounded-v1'},NOW,NOW)
        raw='(ports OR "rail terminal") NOT "sport"'
        self.assertIn(raw,build_requests({'query':raw},NOW,NOW)[0][1]['q'])

    def test_request_and_nominal_credit_budgets_fail_before_article_requests(self):
        for extra in ({'max_requests_per_poll':1},{'max_credits_per_poll':1},
                      {'native_filters':{'effort':'high'},'max_credits_per_poll':10}):
            with self.subTest(extra=extra),patch('app.sources.newscatcher.requests.post') as post:
                source=NewsCatcherSource()
                with patch.object(source,'_plan',return_value={}):
                    with self.assertRaises(ValueError):
                        source._fetch_news(SimpleNamespace(newscatcher_api_key='fixture',newscatcher_effort='low'),self.expanded(**extra),NOW,NOW)
                post.assert_not_called()

    def test_global_request_cap_cannot_be_disabled(self):
        for extra in ({'max_requests_per_poll':17},{'max_requests_per_poll':True},{'max_requests_per_poll':0},
                      {'max_credits_per_poll':False},{'max_credits_per_poll':0}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):
                build_requests(self.expanded(**extra),NOW,NOW)

    def test_articles_endpoint_uses_its_own_length_limit(self):
        params=self.expanded(endpoint='articles',max_requests_per_poll=1,max_credits_per_poll=5)
        parts=build_requests(params,NOW,NOW)
        self.assertEqual(len(parts),1)
        self.assertLessEqual(len(parts[0][1]['q']),1000)

    def test_unknown_enterprise_credit_cost_is_not_zero(self):
        params={'event_presets':['cyber'],'endpoint':'v3','max_credits_per_poll':10}
        with self.assertRaisesRegex(ValueError,'credit estimate unavailable'):
            build_requests(params,NOW,NOW,api_version='v3')
        with patch('app.sources.newscatcher.requests.get') as get:
            with self.assertRaises(ValueError):
                NewsCatcherSource()._fetch_v3('fixture',params,NOW,NOW)
            get.assert_not_called()

    def test_duplicate_selections_do_not_create_duplicate_requests(self):
        params=self.expanded()
        repeated={**params,'event_presets':['cyber','cyber'],'keywords':['Baltic Sea','Baltic Sea']}
        self.assertEqual(build_requests(params,NOW,NOW),build_requests(repeated,NOW,NOW))

    def test_unknown_versions_or_tiers_are_rejected_not_silently_replaced(self):
        for extra in ({'event_vocabulary_version':'future-v99'},{'event_vocabulary_tiers':[]},
                      {'event_vocabulary_tiers':['bogus']},{'event_vocabulary_version':'legacy-v1','event_vocabulary_tiers':['discovery']}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):
                settings(self.expanded(**extra))


class VocabularyApiTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
        Base.metadata.create_all(self.engine)
        self.db=sessionmaker(bind=self.engine,expire_on_commit=False)()
        app.dependency_overrides[get_db]=lambda:self.db
        self.client=TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close(); self.db.close(); self.engine.dispose()

    def test_save_reload_preview_and_no_automatic_upgrade(self):
        payload={'name':'Offline vocabulary test','source':'newscatcher','enabled':False,'interval_minutes':60,
                 'params':{'event_presets':['cyber'],'coverage_countries':['EE','LV','LT'],'keywords':['Baltic Sea']}}
        old=self.client.post('/api/profiles',json=payload)
        self.assertEqual(old.status_code,200,old.text)
        self.assertNotIn('event_vocabulary_version',old.json()['params'])
        expanded={**payload,'params':{**payload['params'],'event_vocabulary_version':'expanded-v1',
                  'event_vocabulary_tiers':['core','indicators','discovery'],'max_requests_per_poll':3,'max_credits_per_poll':3}}
        with patch('app.sources.newscatcher.requests.get') as get,patch('app.sources.newscatcher.requests.post') as post:
            preview=self.client.post('/api/profiles/preview-query',json=expanded)
            self.assertEqual(preview.status_code,200,preview.text)
            result=preview.json()
            self.assertEqual(result['request_count'],2)
            self.assertEqual(result['estimated_credits_per_poll'],2)
            self.assertEqual(result['estimated_credits_per_30_days'],1440)
            self.assertEqual(result['vocabulary']['version'],'expanded-v1')
            self.assertTrue(result['vocabulary']['experimental'])
            self.assertEqual(result['budget']['max_requests_per_poll'],3)
            get.assert_not_called(); post.assert_not_called()
        unchanged=self.client.get('/api/profiles').json()[0]
        self.assertEqual(unchanged['params'],payload['params'])
        saved=self.client.put(f'/api/profiles/{old.json()["id"]}',json=expanded)
        self.assertEqual(saved.status_code,200,saved.text)
        loaded=self.client.get('/api/profiles').json()[0]
        self.assertEqual(loaded['params'],expanded['params'])
        self.assertFalse(loaded['enabled'])

    def test_runtime_budget_refusal_has_safe_diagnostics_and_preserves_success(self):
        from sqlalchemy import select
        old=NOW-timedelta(hours=1)
        profile=SourceProfile(name='Budget runtime test',source='newscatcher',enabled=True,last_run_at=old,
                              params={'keywords':['shipping'],'max_credits_per_poll':1})
        self.db.add(profile);self.db.commit()
        source=NewsCatcherSource()
        settings=SimpleNamespace(newscatcher_api='news',newscatcher_api_key='fixture',newscatcher_effort='high')
        with patch('app.pipeline.ingest.SOURCES',{'newscatcher':source}), \
                patch('app.sources.newscatcher.get_settings',return_value=settings), \
                patch.object(source,'_plan',return_value={}), \
                patch('app.sources.newscatcher.requests.post') as post:
            self.assertEqual(run_profile(self.db,profile),0)
            post.assert_not_called()
        run=self.db.scalar(select(IngestRun))
        self.assertEqual(run.error_code,'CREDIT_BUDGET_EXCEEDED')
        self.assertEqual(run.estimated_credits,0)
        self.assertEqual(run.planned_requests,0)
        self.assertEqual(profile.last_run_at,old)

    def test_api_rejects_invalid_budget_or_version_before_saving(self):
        for extra in ({'event_vocabulary_version':'future-v99'},{'max_requests_per_poll':True},
                      {'max_credits_per_poll':0},{'event_vocabulary_tiers':[]}):
            payload={'name':'Invalid','params':{'event_presets':['cyber'],**extra}}
            response=self.client.post('/api/profiles',json=payload)
            self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.client.get('/api/profiles').json(),[])

    def test_preview_uses_effective_effort_and_unknown_enterprise_estimate(self):
        payload={'name':'Preview','interval_minutes':60,'params':{'keywords':['shipping'],'native_filters':{'effort':'high'}}}
        result=self.client.post('/api/profiles/preview-query',json=payload).json()
        self.assertEqual(result['estimated_credits_per_poll'],10)
        self.assertEqual(result['estimated_credits_per_30_days'],7200)
        payload['params']={'keywords':['shipping'],'endpoint':'v3'}
        with patch('app.sources.newscatcher_filters.get_settings',return_value=SimpleNamespace(newscatcher_api='v3')):
            result=self.client.post('/api/profiles/preview-query',json=payload)
        self.assertEqual(result.status_code,200,result.text)
        self.assertIsNone(result.json()['estimated_credits_per_poll'])


if __name__=='__main__':
    unittest.main()
