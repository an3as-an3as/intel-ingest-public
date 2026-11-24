import test from 'node:test';
import assert from 'node:assert/strict';
import {catchUpPreviewForm, readCatchUpForm, catchUpPreviewText, wireCatchUpPreview} from '../catchup.js';

const run = {id:7,status:'partial',started_at:'2026-11-18T12:00:00Z',finished_at:'2026-11-18T12:00:01Z',
  window_since:'2026-11-18T10:00:00Z',window_until:'2026-11-18T12:00:00Z',requests:[]};
const plan = {request_count:2,estimated_credits:10,entitlement:{status:'operator-declared; not live-verified'},
  warnings:['One page per query/language part.', '<script>unsafe</script>'],requests:[]};
function fixture() {
  const values = {catchup_run:'7',catchup_start:'2026-11-18T10:00:00Z',catchup_end:'2026-11-18T12:00:00Z',
    catchup_minutes:'60',catchup_requests:'4',catchup_credits:'20',catchup_reference:' Offline note ',
    catchup_observed:'2026-11-18T12:00:00Z',catchup_history:'2026-10-18T12:00:00Z',catchup_page_size:'20'};
  const elements = Object.fromEntries(Object.entries(values).map(([key,value])=>[key,{value}]));
  elements.catchup_confirmed={checked:true};
  const handlers={},output={textContent:'',innerHTML:'untouched'},button={disabled:false};
  elements.catchup_run.addEventListener=(event,fn)=>handlers['run-'+event]=fn;
  const form={elements,isConnected:true,querySelector:s=>s.includes('result')?output:button,
    addEventListener:(event,fn)=>handlers[event]=fn};
  return {form,output,button,handlers,root:{querySelector:()=>form}};
}
const submit = form => form.onsubmit({preventDefault(){}});

test('only saved Articles streams with completed incomplete-coverage evidence offer a preview', () => {
  for (const profile of [{source:'gdelt',endpoint:'articles'},{source:'newscatcher',endpoint:'search'},{source:'newscatcher',endpoint:'v3'}]) {
    const html=catchUpPreviewForm(profile,[run]);
    assert.ok(!html.includes('<form'));
    assert.match(html,/no arbitrary historical paging/);
  }
  const p={source:'newscatcher',endpoint:'articles'};
  assert.ok(!catchUpPreviewForm(p,[]).includes('<form'));
  assert.ok(!catchUpPreviewForm(p,[{...run,finished_at:null}]).includes('<form'));
  assert.ok(!catchUpPreviewForm(p,[{...run,status:'success'}]).includes('<form'));
  assert.ok(catchUpPreviewForm(p,[{...run,status:'success',requests:[{history_clamped:true}]}]).includes('<form'));
});

test('controls are explicitly offline, require access evidence, and have no execution action', () => {
  const html=catchUpPreviewForm({source:'newscatcher',endpoint:'articles'},[run]);
  for(const text of ['no collection','not unsaved stream edits','not live-verified','One total budget','required','past 24 hours','do not fetch'])
    assert.ok(html.includes(text),text);
  assert.ok(!html.includes('/run'));
  assert.ok(!html.includes('data-execute'));
  assert.ok(!html.includes('checked>'));
  assert.match(catchUpPreviewForm({source:'newscatcher',endpoint:'articles'},[{...run,status:'<script>',cap_warnings:1}]),/&lt;script&gt;/);
});

test('serialization uses explicit numeric budgets and timezone-aware dates, no saved profile edits', () => {
  const {form}=fixture(),body=readCatchUpForm(form);
  assert.equal(body.evidence_run_id,7);
  assert.equal(body.window_minutes,60);
  assert.equal(body.max_requests,4);
  assert.equal(body.max_credits,20);
  assert.equal(body.entitlement.max_articles_per_page,20);
  assert.equal(body.entitlement.reference,'Offline note');
  assert.equal(body.entitlement.confirmed,true);
  assert.equal(body.window_start,'2026-11-18T10:00:00.000Z');
  assert.ok(!('params' in body));
  assert.ok(!('execute' in body));
});

test('wiring makes no call until explicit submit, then only calls preview and renders text', async () => {
  const f=fixture(),calls=[];
  wireCatchUpPreview(f.root,async (...args)=>{calls.push(args);return plan;},12,[run]);
  assert.deepEqual(calls,[]);
  await submit(f.form);
  assert.equal(calls.length,1);
  assert.equal(calls[0][0],'/api/profiles/12/catch-up-preview');
  assert.equal(calls[0][1].method,'POST');
  assert.match(f.output.textContent,/2 requests \/ 10 nominal credits TOTAL/);
  assert.match(f.output.textContent,/not live-verified/);
  assert.match(f.output.textContent,/<script>unsafe/);
  assert.equal(f.output.innerHTML,'untouched','untrusted preview data must be text, not HTML');
  assert.equal(f.button.disabled,false);
});

test('budget or entitlement refusal remains visible and preview can be retried', async () => {
  const f=fixture();
  wireCatchUpPreview(f.root,async()=>{throw Error('CATCHUP_BUDGET_EXCEEDED <script>');},12,[run]);
  await submit(f.form);
  assert.match(f.output.textContent,/Preview refused: CATCHUP_BUDGET_EXCEEDED/);
  assert.equal(f.output.innerHTML,'untouched');
  assert.equal(f.button.disabled,false);
});

test('input edits invalidate pending results and prevent duplicate submissions', async () => {
  const f=fixture();let resolve,calls=0;
  wireCatchUpPreview(f.root,()=>{calls++;return new Promise(r=>resolve=r);},12,[run]);
  const pending=submit(f.form);
  await submit(f.form);
  assert.equal(calls,1);
  f.form.elements.catchup_credits.value='5';f.handlers.input();
  resolve(plan);await pending;
  assert.match(f.output.textContent,/Inputs changed/);
  assert.doesNotMatch(f.output.textContent,/PREVIEW ONLY/);
  assert.equal(f.button.disabled,false);
});

test('detached forms ignore results and selecting a poll uses that poll’s exact interval', async () => {
  const f=fixture();let resolve;
  wireCatchUpPreview(f.root,()=>new Promise(r=>resolve=r),12,[run]);
  f.handlers['run-change']();
  assert.equal(new Date(f.form.elements.catchup_start.value).toISOString(),new Date(run.window_since).toISOString());
  assert.equal(new Date(f.form.elements.catchup_end.value).toISOString(),new Date(run.window_until).toISOString());
  const pending=submit(f.form);f.form.isConnected=false;resolve(plan);await pending;
  assert.doesNotMatch(f.output.textContent,/PREVIEW ONLY/);
});

test('preview text makes uncertainty, total costs and no execution clear', () => {
  const text=catchUpPreviewText(plan);
  for(const phrase of ['PREVIEW ONLY','no state changed','Coverage remains uncertain','TOTAL (not billing)','not live-verified'])
    assert.ok(text.includes(phrase));
});
