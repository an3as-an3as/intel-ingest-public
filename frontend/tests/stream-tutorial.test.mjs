import test from 'node:test';
import assert from 'node:assert/strict';
import {STREAM_STEPS, pausedStream, streamFingerprint, streamSummaryHtml} from '../stream-tutorial.js';
import {eventVocabularyForm, eventBudgetForm} from '../event-vocabulary.js';

const draft = {
  name:'Ports & security', source:'newscatcher', enabled:true, interval_minutes:60, dashboard_ids:[8],
  params:{keywords:['ports'],exclude_keywords:['sport'],coverage_countries:['DK'],event_presets:['cyber'],
    languages:['en'],source_countries:['SE'],endpoint:'articles',query:'(ports OR shipping)',
    event_vocabulary_version:'legacy-v1',event_vocabulary_tiers:['core'],max_requests_per_poll:3,max_credits_per_poll:10,
    max_records:20,lookback_hours:24,multilingual_enabled:false,native_filters:{exclude_duplicates:false,word_count_min:0}},
};
const options = {countries:{DK:'Denmark',SE:'Sweden'},event_presets:{cyber:'Cyber'},languages:{en:'English',da:'Danish'}};

test('six focused questions explain selection effects and paused completion', () => {
  assert.deepEqual(STREAM_STEPS.map(s=>s[0]),['Purpose','Geography','Developments','Languages','Collection limits','Review']);
  for (const [,question,explanation] of STREAM_STEPS) {
    assert.ok(question.endsWith('?'));
    assert.ok(explanation.length > 70);
  }
  assert.match(STREAM_STEPS[0][2],/requirements decide relevance/);
  assert.match(STREAM_STEPS[3][2],/never silently widen/);
  assert.match(STREAM_STEPS[4][2],/not per month/);
  assert.match(STREAM_STEPS[5][2],/does not start collection/);
});

test('new stream payload is paused without modifying the draft or dropping settings', () => {
  const before=structuredClone(draft),result=pausedStream(draft);
  assert.equal(result.enabled,false);
  assert.deepEqual(draft,before);
  assert.equal(result.params,draft.params);
  assert.deepEqual(result.dashboard_ids,[8]);
  assert.equal(streamFingerprint(draft),streamFingerprint({...draft,enabled:false}));
});

test('preview fingerprint changes for advanced filters, budgets, source and translation receipt', () => {
  for (const variant of [
    {...draft,source:'gdelt'}, {...draft,interval_minutes:180},
    {...draft,params:{...draft.params,native_filters:{exclude_duplicates:true,word_count_min:0}}},
    {...draft,params:{...draft.params,max_requests_per_poll:4}},
    {...draft,params:{...draft.params,translation_review_id:'new receipt'}},
  ]) assert.notEqual(streamFingerprint(variant),streamFingerprint(draft));
});

test('plain-language review retains every advanced effect including false, zero and exclusions', () => {
  const html=streamSummaryHtml(draft,options);
  for (const text of ['Ports &amp; security','Paused','sport','Denmark','Sweden','Cyber','English',
    'articles','ports OR shipping','false','word_count_min','0','8','60 minutes','24 hours','20',
    'Advanced query — replaces keywords','All retained settings','AND groups']) assert.ok(html.includes(text),text);
  assert.ok(!html.includes('GDELT themes'));
  assert.ok(html.includes('<details>'));
});

test('review escapes all user-supplied text and exposes missing translation approval', () => {
  const html=streamSummaryHtml({...draft,name:'<img src=x onerror=bad()>',params:{...draft.params,query:'<script>',
    multilingual_enabled:true,translation_auto_languages:true,translation_languages:['da'],native_filters:{sources:['<iframe>']}}},options);
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('<iframe>'));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('MISSING — review required'));
  assert.ok(html.includes('Danish'));
});

test('unrestricted language filters and unset credit ceilings are not invented', () => {
  const html=streamSummaryHtml({...draft,params:{...draft.params,languages:[],max_credits_per_poll:undefined}});
  assert.ok(html.includes('Unrestricted / none selected'));
  assert.ok(html.includes('Not set — no credit ceiling'));
});

test('vocabulary and budget controls can occupy different steps without duplicate fields', () => {
  const catalog={'legacy-v1':{label:'Legacy v1',tiers:{core:'Core'},description:'Frozen'}};
  const vocabulary=eventVocabularyForm(catalog,{}, {includeBudget:false});
  assert.ok(vocabulary.includes('name="event_vocabulary_version"'));
  assert.ok(!vocabulary.includes('name="max_requests_per_poll"'));
  const budget=eventBudgetForm({max_requests_per_poll:3,max_credits_per_poll:10});
  assert.ok(budget.includes('value="3"'));
  assert.ok(budget.includes('value="10"'));
  assert.equal((eventVocabularyForm(catalog).match(/name="max_requests_per_poll"/g)||[]).length,1);
});
