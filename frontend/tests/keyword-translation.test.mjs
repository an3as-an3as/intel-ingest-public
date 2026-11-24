import test from 'node:test';
import assert from 'node:assert/strict';
import {suggestedTranslationLanguages,keywordTranslationForm,readKeywordTranslation,translationReviewHtml} from '../keyword-translation.js';
import {queryPreviewText} from '../filters.js';
const metadata={mapping:{countries:{FI:['fi','sv'],SE:['sv'],DK:['da'],US:['en']}},max_languages:8};
const languages={en:'English',da:'Danish',fi:'Finnish',sv:'Swedish'};
const review={id:'review-id',rows:[{id:'row-id',language:'da',kind:'events',contexts:['cyber'],source:'data breach',candidates:['databrud'],origin:'offline-suggestions-v1'}],
 missing_count:0,mapping_version:'country-v1',model_calls:0,max_model_calls_per_review:1,language_conflicts:[],warnings:['Review domain terminology'],
 approved:false,live_generation_enabled:false,max_model_terms:40};

test('country suggestions cover multiple languages without duplicate or English lanes',()=>{
 assert.deepEqual(suggestedTranslationLanguages(['FI','SE','FI'],metadata),['fi','sv']);
 assert.deepEqual(suggestedTranslationLanguages(['DK'],metadata),['da']);
 assert.deepEqual(suggestedTranslationLanguages(['US','unknown'],metadata),[]);
});

test('translation remains opt-in with original terms retained and English not offered as an extra target',()=>{
 const html=keywordTranslationForm(metadata,languages,{coverage_countries:['FI']});
 assert.ok(!html.includes('name="multilingual_enabled" checked'));
 assert.ok(html.includes('value="fi" selected'));
 assert.ok(html.includes('value="sv" selected'));
 const targets=html.match(/<select name="translation_languages"[^>]*>([\s\S]*?)<\/select>/)[1];
 assert.ok(!targets.includes('value="en"'));
 assert.ok(html.includes('Language of custom keywords'));
 assert.ok(html.includes('Original terms and the original query are retained'));
});

test('manual language override and saved review ID round-trip in the form',()=>{
 const html=keywordTranslationForm(metadata,languages,{multilingual_enabled:true,translation_auto_languages:false,translation_languages:['da'],translation_review_id:'saved-id',coverage_countries:['FI']});
 assert.ok(html.includes('name="multilingual_enabled" checked'));
 assert.ok(html.includes('value="da" selected'));
 assert.ok(!html.includes('value="fi" selected'));
 assert.ok(html.includes('value="saved-id"'));
});

test('form reads explicit flags and optional immutable snapshot reference',()=>{
 const form={elements:{multilingual_enabled:{checked:true},translation_auto_languages:{checked:false},translation_languages:{selectedOptions:[{value:'da'}]},translation_review_id:{value:'saved-id'}}};
 assert.deepEqual(readKeywordTranslation(form),{keyword_source_language:'en',multilingual_enabled:true,translation_auto_languages:false,translation_languages:['da'],translation_review_id:'saved-id'});
 form.elements.translation_review_id.value='';
 assert.ok(!('translation_review_id' in readKeywordTranslation(form)));
});

test('review requires explicit confirmation, preserves missing rows and shows language conflicts',()=>{
 const html=translationReviewHtml({...review,missing_count:1,language_conflicts:['da'],rows:[{...review.rows[0],candidates:[],origin:'missing'}]});
 assert.ok(html.includes('Language filter conflict: da'));
 assert.ok(html.includes('Keep original only (intentional)'));
 assert.ok(html.includes('data-translation-confirm >'));
 assert.ok(html.includes('Missing phrases are never silently invented or skipped'));
 assert.ok(html.includes('disabled; offline suggestions/manual review only'));
});

test('approved rows are frozen and show approved terms, not stale suggestions',()=>{
 const html=translationReviewHtml({...review,approved:true,rows:[{...review.rows[0],approved_terms:['revideret term'],keep_original:false}]});
 assert.ok(html.includes('revideret term'));
 assert.ok(!html.includes('>databrud</textarea>'));
 assert.ok(html.includes('checked disabled'));
 assert.ok(html.includes('Approved snapshot is frozen'));
});

test('review HTML escapes terms, provenance and context and retains unsaved local edits',()=>{
 const unsafe={...review,rows:[{...review.rows[0],source:'<script>x</script>',origin:'<img src=x>',contexts:['<b>x</b>']}]};
 const edits=new Map([['row-id',{text:'<img src=x>',keep:true}]]);
 const html=translationReviewHtml(unsafe,edits);
 assert.ok(!html.includes('<script>'));
 assert.ok(!html.includes('<img'));
 assert.ok(html.includes('&lt;script&gt;'));
 assert.ok(html.includes('data-translation-keep checked'));
});

test('request preview identifies approved language lanes and separate generation cost',()=>{
 const text=queryPreviewText({request_count:2,requests:[{method:'POST',endpoint:'/search',parameters:{q:'data breach'},translation_language:'original'},
  {method:'POST',endpoint:'/search',parameters:{q:'databrud',languages:['da']},translation_language:'da'}],
  translations:{enabled:true,languages:['da'],review_id:'saved-id'},note:'Review first'});
 for(const phrase of ['Approved multilingual expansion: da','original query retained','lane: da','review: saved-id','no models run during polling'])assert.ok(text.includes(phrase),phrase);
});
