import test from 'node:test';
import assert from 'node:assert/strict';
import {newStreamParams,contentMatchingForm,wireContentMatching} from '../content-matching.js';
import {queryPreviewText} from '../filters.js';

test('new stream defaults explicitly opt into Articles and English translated content',()=>{
 assert.deepEqual(newStreamParams(),{endpoint:'articles',content_matching:'english-translated-v1',event_vocabulary_version:'optimized-v1',query_planner_version:'bounded-v1'});
 assert.equal(newStreamParams({endpoint:'search',content_matching:'provider-default'}).endpoint,'search');
 assert.ok(contentMatchingForm().includes('value="provider-default" selected'));
 assert.ok(contentMatchingForm(newStreamParams()).includes('value="english-translated-v1" selected'));
 assert.ok(contentMatchingForm(newStreamParams()).includes('No translated keyword lists'));
});

test('opening an existing form does not migrate endpoint or disable saved translations',()=>{
 const listeners={},events=[],translations={hidden:false},note={};
 const elements={content_matching:{value:'provider-default',addEventListener:(name,fn)=>listeners[name]=fn},
   nc_endpoint:{value:'search',dispatchEvent:()=>events.push('endpoint')},
   multilingual_enabled:{checked:true,dispatchEvent:()=>events.push('translations')},translation_review_id:{value:'saved'}};
 wireContentMatching({elements,querySelector:selector=>selector==='[data-keyword-translation]'?translations:note});
 assert.equal(elements.nc_endpoint.value,'search');
 assert.equal(elements.multilingual_enabled.checked,true);
 assert.equal(elements.translation_review_id.value,'saved');
 assert.deepEqual(events,[]);
 elements.content_matching.value='english-translated-v1';listeners.change();
 assert.equal(elements.nc_endpoint.value,'articles');
 assert.equal(elements.multilingual_enabled.checked,false);
 assert.equal(elements.translation_review_id.value,'');
 assert.equal(translations.hidden,true);
 assert.deepEqual(events,['endpoint','translations']);
});

test('technical preview states translated fields and lack of extra query translation',()=>{
 const text=queryPreviewText({request_count:1,requests:[],content_matching:{mode:'english-translated-v1',search_in:['title_body','title_body_translated'],note:'No keyword-translation model calls.'}});
 assert.match(text,/title_body_translated/);
 assert.match(text,/No keyword-translation model calls/);
 const original=queryPreviewText({request_count:1,requests:[],content_matching:{mode:'provider-default',search_in:'title'}});
 assert.match(original,/search fields: title/);
});
