"""Independent pilot ledger, mock-only transports; never uses app DB or real keys."""
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from pydantic import ValidationError
from app.pilot import (Ledger, NEWS, PilotPlan, PilotRequest, Refused, ProviderHTTPError,
                       digest, import_preview, live_transport, safe_validation_errors)

AT=datetime(2026,11,19,12,tzinfo=timezone.utc)


def plan_data():
    def variant(name, query):
        return {'name':name,'requests':[{'endpoint':'search','parameters':{
            'q':query,'effort':'low','limit':2,'search_window':'60m'}}]}
    return {'name':'Offline fixture','mode':'simulation','expires_at':(AT+timedelta(hours=1)).isoformat(),
        'allowed_endpoints':['search'],'access_reference':'Synthetic access note','access_confirmed':False,
        'limits':{'max_http_requests':8,'max_collection_requests':4,'max_nominal_credits':4,
                  'max_model_calls':4,'max_reserved_model_tokens':1000},
        'variants':[variant('baseline','ports'),variant('expanded','ports OR shipping')],
        'reference_urls':['https://one.example/a?utm_source=ref'],'polling_interval_minutes':60}


def response(*urls):
    return {'results':[{'url':u,'title':'Same informative title','language':'da','summary':'Fixture evidence'} for u in urls]}


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'pilot.sqlite'
        clock=patch('app.pilot.now',return_value=AT);self.clock=clock.start();self.addCleanup(clock.stop)
        self.env=patch.dict('os.environ',{'INTEL_PILOT_ALLOW_LIVE':'false','ANTHROPIC_API_KEY':'not-used','NEWSCATCHER_API_KEY':'not-used'})
        self.env.start();self.addCleanup(self.env.stop)
        network=patch('requests.sessions.Session.request',side_effect=AssertionError('No external network'))
        network.start();self.addCleanup(network.stop)
        self.config=plan_data()

    def ledger(self, config=None):
        return Ledger.create(self.path,config or self.config)

    def classified(self, *, tokens=1000):
        self.config['classification']={'model':'fixture-model','requirements':'Watch port disruption',
            'max_output_tokens':64,'max_article_chars':2000,'input_usd_per_million':1,'output_usd_per_million':2}
        self.config['limits']['max_reserved_model_tokens']=tokens
        self.config['projected_new_unique_per_poll']=[1,3]
        ledger=self.ledger()
        ledger.collect('baseline',fixture=lambda *args:response('https://one.example/a'))
        ledger.collect('expanded',fixture=lambda *args:response('https://one.example/a'))
        return ledger

    def test_default_live_disarmed_and_requires_exact_approval_separate_keys_and_ack(self):
        self.config.update(mode='live',access_confirmed=True)
        ledger=self.ledger()
        with patch('app.pilot.live_transport') as transport:
            for ack in (False,True):
                with self.assertRaises(Refused):ledger.collect('baseline',ack=ack)
            with self.assertRaises(Refused):ledger.arm(ledger.plan_hash,True)
            with patch.dict('os.environ',{'INTEL_PILOT_ALLOW_LIVE':'true'}):
                with self.assertRaises(Refused):ledger.arm('wrong-hash',True)
                ledger.arm(ledger.plan_hash,True)
                with self.assertRaises(Refused):ledger.collect('baseline')
                transport.return_value=response('https://one.example/a')
                ledger.collect('baseline',ack=True)
                transport.assert_called_once()
        self.assertEqual(ledger.report()['usage']['reserved_http_requests'],1)

    def test_simulation_cannot_be_armed_or_used_to_execute_live(self):
        ledger=self.ledger()
        with patch.dict('os.environ',{'INTEL_PILOT_ALLOW_LIVE':'true'}):
            with self.assertRaises(Refused):ledger.arm(ledger.plan_hash,True)
            with self.assertRaises(Refused):ledger.collect('baseline',ack=True)
        self.assertEqual(ledger.report()['usage']['reserved_http_requests'],0)

    def test_expiry_create_bound_and_existing_file_preserved(self):
        for expiry in (AT,AT+timedelta(days=2)):
            with self.assertRaises(Refused):self.ledger({**self.config,'expires_at':expiry.isoformat()})
            self.assertFalse(self.path.exists())
        ledger=self.ledger();before=self.path.read_bytes()
        with self.assertRaises(FileExistsError):self.ledger()
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)
        self.clock.return_value=AT+timedelta(hours=2)
        with self.assertRaisesRegex(Refused,'expired'):ledger.collect('baseline',fixture=lambda *a:response())
        self.assertEqual(ledger.report()['usage']['reserved_http_requests'],0)

    def test_compiler_preview_import_keeps_payload_and_lanes_not_foreign_review_ids(self):
        payload=self.config['variants'][0]['requests'][0]['parameters']
        preview={'requests':[{'method':'POST','endpoint':NEWS+'search','parameters':payload,
                             'translation_language':'da','translation_review_id':'foreign-id'}]}
        result=import_preview('reviewed',preview)
        self.assertEqual(result['requests'][0]['parameters'],payload)
        self.assertEqual(result['requests'][0]['language_lane'],'da')
        self.assertNotIn('foreign-id',json.dumps(result))
        result['requests'][0]['parameters']['q']='changed'
        self.assertEqual(payload['q'],'ports')
        for endpoint in ('https://evil.example/search',NEWS+'search?key=private','https://v3-api.newscatcherapi.com/api/search'):
            with self.assertRaises(Refused):import_preview('bad',{'requests':[{'endpoint':endpoint,'method':'POST','parameters':payload}]})

    def test_unknown_fields_costs_paging_and_oversized_comparison_refused(self):
        for change in ({'page':2},{'url':'https://evil.example'},{'effort':'unknown'}):
            config=copy.deepcopy(self.config);config['variants'][0]['requests'][0]['parameters'].update(change)
            with self.assertRaises(ValidationError):PilotPlan.model_validate(config)
        for limit,value in [('max_http_requests',1),('max_collection_requests',1),('max_nominal_credits',1)]:
            config=copy.deepcopy(self.config);config['limits'][limit]=value
            with self.assertRaises(ValidationError):PilotPlan.model_validate(config)
        articles={'endpoint':'articles','parameters':{'q':'ports','page':2,'page_size':10,'from_date':AT.isoformat(),'to_date':(AT+timedelta(hours=1)).isoformat()}}
        with self.assertRaises(ValidationError):PilotRequest.model_validate(articles)

    def test_overlap_reference_diversity_caps_and_scheduled_estimates_are_honest(self):
        ledger=self.ledger()
        ledger.collect('baseline',fixture=lambda *a:response('https://one.example/a?utm_source=x','https://two.example/b'))
        ledger.collect('expanded',fixture=lambda *a:response('https://one.example/a','https://three.example/c'))
        report=ledger.report();a,b=report['variants']
        self.assertEqual((a['unique_urls'],b['unique_urls']),(2,2))
        self.assertEqual(len(a['publishers']),2)  # identical titles do not merge independent URLs
        self.assertEqual(a['matched_reference_urls'],['https://one.example/a'])
        self.assertEqual(a['cap_warnings'],1)
        self.assertEqual(a['scheduled_30d_requests'],720)
        self.assertEqual(a['scheduled_30d_nominal_credits'],720)
        self.assertEqual(report['overlap'][0],{'left':'baseline','right':'expanded','shared_urls':1,'left_only':1,'right_only':1})
        self.assertIsNone(report['usage']['actual_collection_credits'])
        self.assertIsNone(report['usage']['actual_quota_delta'])
        self.assertIsNone(report['conditional_classification_projection'])

    def test_failures_keep_full_batch_allowance_and_never_retry_automatically(self):
        self.config['variants'][0]['requests']*=2
        self.config['limits'].update(max_collection_requests=3,max_nominal_credits=3)
        ledger=self.ledger();transport=MagicMock(side_effect=TimeoutError('key must not appear'))
        with self.assertRaises(Refused):ledger.collect('baseline',fixture=transport)
        report=ledger.report();self.assertEqual(report['usage']['reserved_http_requests'],2)
        self.assertEqual(report['usage']['dispatched_http_requests'],1)
        self.assertEqual(report['usage']['reserved_nominal_credits'],2)
        with self.assertRaises(Refused):ledger.collect('baseline',fixture=transport)
        self.assertEqual(transport.call_count,1)
        self.assertNotIn('key must not appear',json.dumps(report))

    def test_stop_between_requests_and_permanent_stop_after_restart(self):
        self.config['variants'][0]['requests']*=2
        ledger=self.ledger();seen=[]
        def stop(kind,spec):seen.append(kind);ledger.stop();return response('https://one.example/a')
        with self.assertRaises(Refused):ledger.collect('baseline',fixture=stop)
        self.assertEqual(seen,['collection'])
        restored=Ledger(self.path)
        self.assertTrue(restored.report()['stopped'])
        with self.assertRaises(Refused):restored.collect('expanded',fixture=lambda *a:response())
        self.assertEqual(restored.report()['usage']['reserved_http_requests'],2)

    def test_expiry_between_requests_prevents_remaining_dispatch(self):
        self.config['variants'][0]['requests']*=2
        ledger=self.ledger();seen=[]
        def expire(kind,spec):seen.append(kind);self.clock.return_value=AT+timedelta(hours=2);return response()
        with self.assertRaises(Refused):ledger.collect('baseline',fixture=expire)
        self.assertEqual(seen,['collection'])

    def test_crash_retains_reservations_and_lock_is_released(self):
        ledger=self.ledger()
        with self.assertRaises(SystemExit):ledger.collect('baseline',fixture=MagicMock(side_effect=SystemExit))
        restored=Ledger(self.path)
        self.assertEqual(restored.report()['attempts'][0]['status'],'started')
        restored.collect('expanded',fixture=lambda *a:response())
        self.assertEqual(restored.report()['usage']['reserved_http_requests'],2)

    def test_same_ledger_concurrent_run_is_refused_and_report_stop_still_work(self):
        ledger=self.ledger();other=Ledger(self.path)
        with ledger.exclusive_run():
            with self.assertRaises(Refused):other.collect('baseline',fixture=lambda *a:response())
            self.assertFalse(other.report()['stopped']);other.stop()
        self.assertTrue(ledger.report()['stopped'])

    def test_plan_mutation_cannot_raise_limits_or_extend_expiry(self):
        ledger=self.ledger();ledger.plan.limits.max_http_requests=64
        with self.assertRaisesRegex(Refused,'Plan changed'):ledger.collect('baseline',fixture=lambda *a:response())

    def test_classification_counts_shared_url_once_fixed_settings_and_records_usage(self):
        ledger=self.classified();seen=[]
        def transport(kind,spec):
            seen.append((kind,spec))
            if kind=='count_tokens':return {'input_tokens':100}
            return {'content':[{'type':'text','text':'{"relevant":true,"rationale":"Port disruption"}'}],
                    'usage':{'input_tokens':90,'output_tokens':10}}
        self.assertTrue(ledger.classify_one(fixture=transport))
        self.assertFalse(ledger.classify_one(fixture=transport))
        self.assertEqual([k for k,_ in seen],['count_tokens','inference'])
        self.assertEqual(seen[0][1]['system'],seen[1][1]['system'])
        self.assertEqual(seen[0][1]['messages'],seen[1][1]['messages'])
        report=ledger.report();usage=report['usage']
        self.assertEqual(usage['reserved_model_calls'],2)
        self.assertEqual(usage['reserved_model_tokens'],164)
        self.assertEqual((usage['reported_input_tokens'],usage['reported_output_tokens']),(90,10))
        self.assertAlmostEqual(usage['estimated_model_usd_at_declared_prices'],.00011)
        self.assertEqual([v['model_relevant_urls'] for v in report['variants']],[1,1])
        self.assertEqual(report['conditional_classification_projection']['scheduled_30d_model_tokens'],[72000,216000])

    def test_token_ceiling_refuses_inference_after_count_without_resetting_calls(self):
        ledger=self.classified(tokens=100);seen=[]
        def count(kind,spec):seen.append(kind);return {'input_tokens':100}
        with self.assertRaisesRegex(Refused,'Token reservation'):ledger.classify_one(fixture=count)
        self.assertEqual(seen,['count_tokens'])
        self.assertEqual(ledger.report()['usage']['reserved_model_calls'],2)
        self.assertFalse(ledger.classify_one(fixture=count))

    def test_missing_or_excess_provider_usage_stops_further_work(self):
        ledger=self.classified()
        def transport(kind,spec):
            if kind=='count_tokens':return {'input_tokens':10}
            return {'usage':{'input_tokens':11,'output_tokens':5},'content':[]}
        with self.assertRaisesRegex(Refused,'stopped'):ledger.classify_one(fixture=transport)
        self.assertTrue(ledger.report()['stopped'])
        self.assertEqual(ledger.report()['usage']['reserved_model_tokens'],74)
        with self.assertRaises(Refused):ledger.collect('expanded',fixture=lambda *a:response())

    def test_missing_labels_and_unknown_charges_are_not_retried(self):
        ledger=self.classified();calls=[]
        def transport(kind,spec):
            calls.append(kind)
            return {'input_tokens':10} if kind=='count_tokens' else {'usage':{'input_tokens':10,'output_tokens':2},'content':[]}
        with self.assertRaisesRegex(Refused,'Invalid model label'):ledger.classify_one(fixture=transport)
        self.assertFalse(ledger.classify_one(fixture=transport))
        self.assertEqual(calls,['count_tokens','inference'])
        self.assertEqual(ledger.report()['usage']['reported_output_tokens'],2)

    def test_no_classification_or_future_projection_is_implicitly_enabled(self):
        ledger=self.ledger()
        with self.assertRaises(Refused):ledger.classify_one(fixture=lambda *a:{})
        self.assertEqual(ledger.report()['usage']['reserved_model_calls'],0)
        for bounds in ([-1,2],[3,1],[0,float('inf')]):
            with self.assertRaises(ValidationError):PilotPlan.model_validate({**self.config,'projected_new_unique_per_poll':bounds})

    def test_live_transport_never_reads_standard_production_key_names(self):
        with patch.dict('os.environ',{'INTEL_PILOT_ALLOW_LIVE':'true','INTEL_PILOT_NEWSCATCHER_KEY':''}):
            with self.assertRaisesRegex(Refused,'Separate pilot'):live_transport('collection',self.config['variants'][0]['requests'][0])

    def test_isolated_import_does_not_load_application_settings_sources_or_database(self):
        code = ('import app.pilot,sys; '
                'assert not ({"app.db","app.config","app.sources"} & set(sys.modules)); '
                'print("isolated import verified")')
        env = {**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1])}
        result = subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,text=True,check=True)
        self.assertIn('isolated import verified',result.stdout)

    def test_malformed_collection_results_are_not_success_or_refunded(self):
        ledger=self.ledger()
        with self.assertRaises(Refused):ledger.collect('baseline',fixture=lambda *a:{'results':'not a list'})
        report=ledger.report()
        self.assertEqual(report['attempts'][0]['status'],'invalid')
        self.assertEqual(report['usage']['reserved_nominal_credits'],1)
        self.assertEqual(report['usage']['completed_collection_requests'],0)

    def test_articles_payload_uses_explicit_fixed_dates_and_known_credit_cost(self):
        payload={'q':'ports','page':1,'page_size':20,'from_date':(AT-timedelta(hours=1)).isoformat(),'to_date':AT.isoformat()}
        request=PilotRequest(endpoint='articles',parameters=payload)
        self.assertEqual(request.credits(),5)
        for bad in ({'from_date':'yesterday'},{'to_date':payload['from_date']},{'page':2}):
            with self.assertRaises(ValidationError):PilotRequest(endpoint='articles',parameters={**payload,**bad})

    def test_model_http_limit_is_checked_before_token_counter_or_inference(self):
        self.config['limits']['max_model_calls']=2
        ledger=self.classified();ledger.classify_one(fixture=lambda kind,spec:
            {'input_tokens':10} if kind=='count_tokens' else {'usage':{'input_tokens':10,'output_tokens':2},
                'content':[{'type':'text','text':'{"relevant":false,"rationale":"No disruption"}'}]})
        # Add a new URL with one remaining collection reservation; existing classification is never repeated.
        ledger.collect('expanded',fixture=lambda *a:response('https://two.example/new'))
        with self.assertRaises(Refused):ledger.classify_one(fixture=lambda *a: self.fail('No model calls allowed'))

    def test_safe_validation_details_keep_fields_not_inputs_headers_or_secrets(self):
        secret='fixture-secret-key'
        raw={'detail':[{'loc':['body','languages',2],'type':'literal_error',
            'msg':'Unsupported language no; key='+secret,'input':secret,'ctx':{'key':secret}}],
            'headers':{'x-api-key':secret},'request':{'q':'private input'}}
        result=safe_validation_errors(json.dumps(raw).encode(),secret)
        self.assertEqual(result[0]['field'],['body','languages','2'])
        self.assertIn('Unsupported language no',result[0]['message'])
        self.assertNotIn(secret,json.dumps(result))
        self.assertNotIn('private input',json.dumps(result))
        self.assertNotIn('headers',json.dumps(result))
        self.assertEqual(safe_validation_errors(b'<html>not JSON</html>',secret),[])
        many=safe_validation_errors(json.dumps({'detail':['x'*2000]*30}),secret)
        self.assertEqual(len(many),8)
        self.assertTrue(all(len(x['message'])<=600 for x in many))

    def test_provider_422_fields_survive_in_report_without_raw_inputs(self):
        ledger=self.ledger()
        error=ProviderHTTPError(422,[{'field':['body','languages','2'],'type':'literal_error','message':'Unsupported no'}])
        with self.assertRaises(Refused):ledger.collect('baseline',fixture=MagicMock(side_effect=error))
        attempt=ledger.report()['attempts'][0]
        self.assertEqual(attempt['http_status'],422)
        self.assertEqual(attempt['validation_errors'][0]['field'],['body','languages','2'])
        self.assertEqual(ledger.report()['usage']['dispatched_http_requests'],1)

    def test_diagnostic_is_exactly_one_low_effort_search_with_zero_model_allowance(self):
        self.config.update(purpose='diagnostic',variants=[self.config['variants'][0]],
            limits={'max_http_requests':1,'max_collection_requests':1,'max_nominal_credits':1,
                    'max_model_calls':0,'max_reserved_model_tokens':0})
        ledger=self.ledger()
        ledger.collect('baseline',fixture=lambda *a:response())
        self.assertEqual(ledger.report()['purpose'],'diagnostic')
        with self.assertRaises(Refused):ledger.collect('baseline',fixture=lambda *a:self.fail('No second call'))
        for key in ('max_http_requests','max_collection_requests','max_nominal_credits','max_model_calls','max_reserved_model_tokens'):
            config=copy.deepcopy(self.config);config['limits'][key]+=1
            with self.assertRaises(ValidationError):PilotPlan.model_validate(config)
        config=copy.deepcopy(self.config);config.pop('purpose')
        with self.assertRaises(ValidationError):PilotPlan.model_validate(config)
        config=copy.deepcopy(self.config);config['variants'][0]['requests'][0]['parameters']['effort']='medium'
        with self.assertRaises(ValidationError):PilotPlan.model_validate(config)

    def test_existing_frozen_plan_hash_survives_optional_diagnostic_field(self):
        model=PilotPlan.model_validate(self.config)
        original=model.model_dump(mode='json');original.pop('purpose')
        self.assertEqual(digest(original),digest(model.model_dump(mode='json')))

    def test_transport_captures_422_error_details_and_redacts_test_key(self):
        session=MagicMock();reply=MagicMock(status_code=422)
        reply.iter_content.return_value=[json.dumps({'detail':[{'loc':['body','languages',2],
            'type':'literal_error','msg':'Unsupported language; fixture-only','input':'fixture-only'}]}).encode()]
        session.post.return_value.__enter__.return_value=reply
        factory=MagicMock();factory.return_value.__enter__.return_value=session
        with patch.dict('os.environ',{'INTEL_PILOT_ALLOW_LIVE':'true','INTEL_PILOT_NEWSCATCHER_KEY':'fixture-only'}),patch('app.pilot.requests.Session',factory):
            with self.assertRaises(ProviderHTTPError) as caught:
                live_transport('collection',self.config['variants'][0]['requests'][0])
        self.assertEqual(caught.exception.validation_errors[0]['field'],['body','languages','2'])
        self.assertNotIn('fixture-only',json.dumps(caught.exception.validation_errors))
        self.assertEqual(session.post.call_count,1)

    def test_transport_has_fixed_host_no_redirects_and_no_inherited_proxy(self):
        session=MagicMock();reply=MagicMock(status_code=200)
        reply.iter_content.return_value=[b'{"results":[]}']
        session.post.return_value.__enter__.return_value=reply
        factory=MagicMock();factory.return_value.__enter__.return_value=session
        with patch.dict('os.environ',{'INTEL_PILOT_ALLOW_LIVE':'true','INTEL_PILOT_NEWSCATCHER_KEY':'fixture-only'}),patch('app.pilot.requests.Session',factory):
            self.assertEqual(live_transport('collection',self.config['variants'][0]['requests'][0]),{'results':[]})
        args,kwargs=session.post.call_args
        self.assertEqual(args[0],NEWS+'search')
        self.assertFalse(kwargs['allow_redirects']);self.assertFalse(session.trust_env)
        self.assertEqual(kwargs['timeout'],(5,30));self.assertTrue(kwargs['stream'])
