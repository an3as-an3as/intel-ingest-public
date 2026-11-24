import test from 'node:test';
import assert from 'node:assert/strict';
import {collectionDiagnostics, collectionRunsHtml, wireCollectionDiagnostics} from '../collection.js';

const run = {started_at:'2026-01-10T12:00:00Z',status:'partial',error_code:'HTTP_503',duration_ms:25,
  returned_articles:20,new_articles:12,duplicate_urls:5,duplicate_titles:3,excluded_articles:0,invalid_articles:0,
  tracked_requests:2,planned_requests:3,estimated_credits:null,cap_warnings:1,
  new_article_statuses:{pending:12},requests:[{part:1,endpoint:'search',status:'success',http_status:200,
    returned:20,limit:20,duration_ms:12,query_hash:'abcdef',window_overridden:true,history_clamped:true,time_parameters:{search_window:'60m'}}]};

test('diagnostics starts read-only with separate attempted/successful times', () => {
  const html=collectionDiagnostics({id:12,ingestion:{last_attempt_at:'2026-01-10T12:00:00Z',last_success_at:null,failures:2}});
  assert.ok(html.includes('Last attempt:'));
  assert.ok(html.includes('Last successful poll: never'));
  assert.ok(html.includes('Consecutive failures: 2'));
  assert.ok(html.includes('type="button"'));
  assert.ok(!html.includes('/run'));
});

test('empty history does not offer to ingest or seed anything', () => {
  const html=collectionRunsHtml([]);
  assert.ok(html.includes('No recorded polls yet'));
  assert.ok(html.includes('does not fetch articles'));
});

test('partial outcomes, unknown costs and incomplete coverage are explicit', () => {
  const html=collectionRunsHtml([run]);
  for(const text of ['partial','HTTP_503','unknown','at cap','articles may be missing','2 tracked / 3 planned','pending: 12',
    'scheduling window may not apply','History limit shortened','60m']) assert.ok(html.includes(text),text);
});

test('provider-derived fields and status keys are escaped', () => {
  const html=collectionRunsHtml([{...run,error_code:'<img src=x onerror=alert(1)>',new_article_statuses:{'<script>':1},
    requests:[{...run.requests[0],query_hash:'<script>bad</script>'}]}]);
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('<img'));
  assert.ok(html.includes('&lt;script&gt;'));
});

test('loading diagnostics uses only the read endpoint and restores the button', async () => {
  const button={disabled:false},target={innerHTML:''},calls=[];
  const panel={dataset:{collectionProfile:'12'},querySelector:selector=>selector.includes('refresh')?button:target};
  wireCollectionDiagnostics({querySelectorAll:()=>[panel]},async path=>{calls.push(path);return [run];});
  await button.onclick();
  assert.deepEqual(calls,['/api/profiles/12/ingest-runs?limit=20']);
  assert.equal(button.disabled,false);
  assert.ok(target.innerHTML.includes('HTTP_503'));
});

test('load errors remain escaped and can be retried', async () => {
  const button={disabled:false},target={innerHTML:''};
  const panel={dataset:{collectionProfile:'12'},querySelector:selector=>selector.includes('refresh')?button:target};
  wireCollectionDiagnostics({querySelectorAll:()=>[panel]},async()=>{throw Error('<script>unsafe</script>');});
  await button.onclick();
  assert.ok(target.innerHTML.includes('&lt;script&gt;unsafe'));
  assert.ok(!target.innerHTML.includes('<script>'));
  assert.equal(button.disabled,false);
});
