import test from 'node:test';
import assert from 'node:assert/strict';
import {eventVocabularyForm,readEventVocabulary} from '../event-vocabulary.js';
import {queryPreviewText} from '../filters.js';

const catalog={
 'legacy-v1':{label:'Legacy v1',description:'Original terms',tiers:{core:'Original terms'}},
 'expanded-v1':{label:'Expanded v1',description:'Experimental',tiers:{core:'Core',indicators:'Indicators',discovery:'Discovery'}}
};

test('new or legacy forms default to the frozen library and core only',()=>{
 const html=eventVocabularyForm(catalog);
 assert.ok(html.includes('value="legacy-v1" selected'));
 assert.ok(html.includes('value="core" selected'));
 assert.ok(!html.includes('value="discovery"'));
 assert.ok(html.includes('name="max_requests_per_poll"'));
 assert.ok(html.includes('not a monthly spending cap'));
});

test('expanded saved version, tiers and limits render for reload',()=>{
 const html=eventVocabularyForm(catalog,{event_vocabulary_version:'expanded-v1',event_vocabulary_tiers:['core','indicators'],max_requests_per_poll:3,max_credits_per_poll:5});
 assert.ok(html.includes('value="expanded-v1" selected'));
 assert.ok(html.includes('value="indicators" selected'));
 assert.ok(html.includes('value="discovery" >'));
 assert.ok(html.includes('value="3"'));
 assert.ok(html.includes('value="5"'));
});

test('unavailable saved version is preserved rather than silently downgraded',()=>{
 const html=eventVocabularyForm(catalog,{event_vocabulary_version:'future-v99',event_vocabulary_tiers:['custom']});
 assert.ok(html.includes('value="future-v99" selected'));
 assert.ok(html.includes('Unavailable vocabulary'));
 assert.ok(html.includes('Do not silently substitute'));
 assert.ok(html.includes('value="custom" selected'));
});

test('vocabulary labels, descriptions and saved values are HTML escaped',()=>{
 const html=eventVocabularyForm({'bad':{label:'<img src=x>',description:'<script>bad</script>',tiers:{core:'<b>bad</b>'}}},{event_vocabulary_version:'bad',event_vocabulary_tiers:['core']});
 assert.ok(!html.includes('<img'));
 assert.ok(!html.includes('<script>'));
 assert.ok(html.includes('&lt;script&gt;'));
});

function form(credit='') {
 return {elements:{event_vocabulary_version:{value:'expanded-v1'},event_vocabulary_tiers:{selectedOptions:[{value:'core'},{value:'indicators'}]},
  max_requests_per_poll:{value:'3'},max_credits_per_poll:{value:credit}}};
}

test('form serialization retains explicit version, tiers and budgets',()=>{
 assert.deepEqual(readEventVocabulary(form('5')),{query_planner_version:'bounded-v1',event_vocabulary_version:'expanded-v1',event_vocabulary_tiers:['core','indicators'],max_requests_per_poll:3,max_credits_per_poll:5});
 assert.ok(!('max_credits_per_poll' in readEventVocabulary(form())));
 const empty=form();empty.elements.event_vocabulary_tiers.selectedOptions=[];
 assert.deepEqual(readEventVocabulary(empty).event_vocabulary_tiers,[]); // Server rejects, not a hidden default.
});

test('existing forms retain legacy planning while enhanced selections opt in',()=>{
 const saved=form(); saved.elements.event_vocabulary_version.value='legacy-v1';
 saved.elements.query_planner_version={value:'legacy-v1'};
 assert.equal(readEventVocabulary(saved).query_planner_version,'legacy-v1');
 saved.elements.coverage_regions={selectedOptions:[{value:'europe'}]};
 assert.equal(readEventVocabulary(saved).query_planner_version,'bounded-v1');
 saved.elements.coverage_regions.selectedOptions=[];
 saved.elements.multilingual_enabled={checked:true};
 assert.equal(readEventVocabulary(saved).query_planner_version,'bounded-v1');
 saved.elements.multilingual_enabled.checked=false;
 saved.elements.query_planner_version.value='bounded-v1';
 assert.equal(readEventVocabulary(saved).query_planner_version,'bounded-v1');
});

test('preview explains additions/removals, nominal credits and scheduling assumptions',()=>{
 const text=queryPreviewText({request_count:2,requests:[{method:'POST',endpoint:'/search',parameters:{q:'example'}}],
  vocabulary:{version:'expanded-v1',tiers:['core'],term_count:2,terms:['airstrike','missile strike'],language:'en',experimental:true,
   added_vs_legacy:['missile strike'],removed_vs_legacy:['war']},budget:{max_requests_per_poll:3,max_credits_per_poll:5},
  estimated_credits_per_poll:2,estimated_credits_per_30_days:1440,estimated_requests_per_30_days:1440,note:'Not provider billing.'});
 for(const phrase of ['expanded-v1','EXPERIMENTAL','Added vs Legacy v1: missile strike','Removed vs Legacy v1: war',
  '2 credits','1440','excludes retries and manual runs','Request limit: 3','credit ceiling: 5']) {
   if(phrase==='2 credits') assert.ok(text.includes('credits per poll: 2')); else assert.ok(text.includes(phrase),phrase);
 }
});

test('unknown endpoint cost stays unknown in preview, not zero',()=>{
 const text=queryPreviewText({request_count:1,requests:[{method:'GET',endpoint:'/v3',parameters:{q:'x'}}],
  estimated_credits_per_poll:null,estimated_credits_per_30_days:null,estimated_requests_per_30_days:720});
 assert.ok(text.includes('credits per poll: unknown'));
 assert.ok(text.includes('30-day scheduled estimate: unknown'));
});
