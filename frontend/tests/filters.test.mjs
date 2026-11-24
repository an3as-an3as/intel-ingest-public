import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { nativeFilterForm, readNativeFilters, queryPreviewText } from '../filters.js';

const contract = JSON.parse(readFileSync(new URL('../../backend/app/sources/newscatcher_filters.json', import.meta.url)));
const managed = ['q','countries','languages','lang','limit','page_size'];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const options = {countries: {FI:'Finland',SE:'Sweden'}, languages: {en:'English',fi:'Finnish'}};

test('split query preview shows every request and its cost warning', () => {
  const requests = ['war AND Estonia', 'shipping AND Estonia'].map(q => ({method:'POST',endpoint:'/search',parameters:{q,languages:['en','et']}}));
  const text = queryPreviewText({requests,request_count:2,note:'Article limit applies per request.'});
  assert.ok(text.includes('2 API requests per poll'));
  assert.ok(text.includes('each consumes quota/credits'));
  assert.ok(text.includes('Request 1: POST /search'));
  assert.ok(text.includes('Request 2: POST /search'));
  assert.ok(text.includes('war AND Estonia'));
  assert.ok(text.includes('shipping AND Estonia'));
  assert.equal(queryPreviewText({query:'GDELT query'}), 'GDELT query');
});

test('every documented non-managed field has a typed form control for its endpoint', () => {
  for (const [mode, fields] of Object.entries(contract.modes)) {
    const html = nativeFilterForm({modes:{[mode]:fields}, managed}, options, {}, esc);
    for (const key of Object.keys(fields)) {
      assert.equal(html.includes(`data-native-filter="${key}"`), !managed.includes(key), `${mode}: ${key}`);
    }
    assert.ok(html.includes(`data-nc-mode="${mode}"`));
  }
});

test('saved arrays, false, zero and Enterprise comma-list selections are rendered', () => {
  const html = nativeFilterForm({modes:contract.modes, managed}, options,
    {endpoint:'v3', native_filters:{not_lang:'en,fi', theme:'Tech,Finance', is_opinion:false, word_count_min:0}}, esc);
  assert.ok(html.includes('value="en" selected'));
  assert.ok(html.includes('value="fi" selected'));
  assert.ok(html.includes('value="Tech" selected'));
  assert.ok(html.includes('value="Finance" selected'));
  assert.ok(html.includes('value="false" selected'));
  assert.match(html, /data-native-filter="word_count_min" data-filter-mode="v3"[^>]*value="0"/);
});

test('field help and user-supplied filters are HTML escaped', () => {
  const html = nativeFilterForm({modes:contract.modes, managed}, options,
    {native_filters:{sources:['<script>alert(1)</script>']}}, esc);
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('&lt;script&gt;'));
});

test('serializing selects retains multiple values, booleans and zero; skips other endpoints', () => {
  const input = (key, type, value, mode='search', multiple=false) => ({dataset:{nativeFilter:key,filterType:type,filterMode:mode},
    value, multiple, selectedOptions:multiple ? value.map(value => ({value})) : undefined});
  const fields = [input('not_countries','array',['FI','SE'],'search',true),
    input('not_languages','array',['en','fi'],'search',true), input('min_newsrooms','number','0'),
    input('sources','array','bbc.co.uk, reuters.com'), input('content_type','string','all'),
    input('sort_by','string',''), input('ranked_only','boolean','false','articles')];
  const form = {elements:{nc_endpoint:{value:'search'}},querySelectorAll:() => fields};
  assert.deepEqual(readNativeFilters(form), {endpoint:'search',native_filters:{not_countries:['FI','SE'],
    not_languages:['en','fi'],min_newsrooms:0,sources:['bbc.co.uk','reuters.com'],content_type:'all'}});
  form.elements.nc_endpoint.value='articles';
  assert.deepEqual(readNativeFilters(form).native_filters,{ranked_only:false});
  form.elements.nc_endpoint.value='v3';
  fields.push(input('theme','csv',['Tech','Finance'],'v3',true));
  assert.deepEqual(readNativeFilters(form).native_filters,{theme:'Tech,Finance'});
});
