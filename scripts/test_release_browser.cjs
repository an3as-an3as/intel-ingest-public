// Read-only browser smoke for an isolated restored-database candidate.
// NODE_PATH=/path/to/playwright/node_modules INTEL_REVIEW_URL=http://127.0.0.1:8083 node scripts/test_release_browser.cjs
// Never saves profiles. Requires APP_ENVIRONMENT=test, local non-production port.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const base=process.env.INTEL_REVIEW_URL;
assert.ok(base,'Set INTEL_REVIEW_URL to the isolated candidate');
const url=new URL(base);
assert.ok(url.hostname==='127.0.0.1' && url.port && !['8080','8081'].includes(url.port));

(async()=>{
 const browser=await chromium.launch({headless:true});
 const page=await browser.newPage();
 const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
   const request=route.request(), target=new URL(request.url());
   if(target.origin===url.origin){
     if(!['GET','HEAD'].includes(request.method()) && target.pathname!=='/api/profiles/preview-query')
       throw Error('Mutation blocked by release browser test');
     return route.continue();
   }
   // No external requests. Rendering libraries are unused by this form smoke.
   if(target.pathname.endsWith('marked.min.js')) return route.fulfill({contentType:'application/javascript',body:'window.marked={parse:()=>""};'});
   if(target.pathname.endsWith('purify.min.js')) return route.fulfill({contentType:'application/javascript',body:'window.DOMPurify={sanitize:()=>""};'});
   return route.abort();
 });
 try {
   const meta=await (await page.request.get(base+'/api/meta')).json();
   assert.equal(meta.environment,'test','Requires isolated test candidate, not production/development');
   await page.goto(base+'/#/ingestion');
   const form=page.locator('#new-prof');
   await form.waitFor();
   assert.equal(await form.locator('[name=event_vocabulary_version]').inputValue(),'optimized-v1');
   assert.equal(await form.locator('[name=query_planner_version]').inputValue(),'bounded-v1');
   assert.equal(await form.locator('[name=content_matching]').inputValue(),'english-translated-v1');
   assert.equal(await form.locator('[name=nc_endpoint]').inputValue(),'articles');
   assert.equal(await form.locator('[data-keyword-translation]').isVisible(),false);
   assert.equal(await form.locator('[name=event_vocabulary_tiers] + section.multi-picker').count(),0);
   await form.locator('[data-stream-mode]').click();
   await form.locator('details').evaluateAll(ds=>ds.forEach(d=>d.open=true));
   await form.locator('[name=name]').fill('Synthetic regional preview — NOT SAVED');
   for(const region of ['Europe','Asia'])
     await form.locator('select[name=coverage_regions] + section label').filter({hasText:new RegExp('^'+region+'$')}).locator('input').check();
   await form.locator('select[name=event_presets] + section label').filter({hasText:/^Armed conflict$/}).locator('input').check();
   await form.locator('select[name=nc_languages]').selectOption(['de'],{force:true});
   const pending=page.waitForResponse(r=>r.url().includes('/api/profiles/preview-query') && r.request().method()==='POST');
   await form.locator('[data-preview]').click();
   const response=await pending;
   assert.equal(response.status(),200);
   const preview=await response.json();
   assert.equal(preview.query_planner_version,'bounded-v1');
   assert.equal(preview.vocabulary.version,'optimized-v1');
   assert.equal(preview.content_matching.mode,'english-translated-v1');
   assert.equal(preview.translations.enabled,false);
   for(const request of preview.requests){
    assert.ok(request.endpoint.endsWith('/articles'));
    assert.deepEqual(request.parameters.search_in,['title_body','title_body_translated']);
    assert.deepEqual(request.parameters.languages,['de']);
   }
   const queries=preview.requests.map(r=>r.parameters.q).join(' ');
   assert.ok(queries.includes('Japan')&&queries.includes('Ukraine')&&queries.includes('airstrike'));
   console.log('PASS: new single-list default and Europe + Asia regional preview; no save.');
   // Local-language expansion is an alternative, not needed in English-content mode.
   await form.locator('[name=content_matching]').selectOption('provider-default');
   // Reproduce an oversized translation review without creating any draft rows.
   let planCalls=0;
   await page.route('**/api/ingestion/translation-plans', route=>{
     planCalls++;
     return route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({detail:'Translation review exceeds 400 phrase/language rows (mocked UI test)'})});
   });
   await form.locator('select[name=nc_languages]').selectOption(['en'],{force:true});
   await form.locator('[name=multilingual_enabled]').check();
   await form.locator('[name=translation_auto_languages]').uncheck();
   await form.locator('select[name=translation_languages]').selectOption(['da','de','fr','sv'],{force:true});
   await page.waitForFunction(()=>document.querySelector('#new-prof [data-translation-message]').textContent.includes('400 phrase/language'));
   const beforeInclude=planCalls;
   await form.locator('[data-translation-include]').click();
   await page.waitForTimeout(900);
   assert.equal(planCalls,beforeInclude,'Adding allowed article languages must not prepare translation rows');
   assert.ok((await form.locator('[data-translation-message]').textContent()).includes('no translation plan was requested'));
   const allowed=await form.locator('select[name=nc_languages]').evaluate(s=>Array.from(s.selectedOptions,o=>o.value));
   assert.deepEqual(allowed.sort(),['da','de','en','fr','sv']);
   assert.equal(await form.locator('[name=translation_review_id]').inputValue(),'');
   await form.locator('[name=multilingual_enabled]').uncheck();
   console.log('PASS: article-language include invalidates approval but does not regenerate an oversized translation plan.');
   const profiles=await (await page.request.get(base+'/api/profiles')).json();
   for(const profile of profiles){
     const card=page.locator(`[data-prof="${profile.id}"]`);
     assert.equal(await card.locator('[name=query_planner_version]').inputValue(),'legacy-v1');
     assert.equal(await card.locator('[name=content_matching]').inputValue(),'provider-default');
     assert.equal(await card.locator('[name=event_vocabulary_version]').inputValue(),'legacy-v1');
     await card.locator('details').evaluateAll(ds=>ds.forEach(d=>d.open=true));
     const expected=await (await page.request.post(base+'/api/profiles/preview-query',{data:profile})).json();
     const wait=page.waitForResponse(r=>r.url().includes('/api/profiles/preview-query')&&r.request().method()==='POST');
     await card.locator('[data-preview]').click();
     const result=await wait;
     assert.equal(result.status(),200);
     const actual=await result.json();
     assert.equal(actual.query_planner_version,'legacy-v1');
     // Avoid printing private queries in assertion diagnostics.
     assert.ok(JSON.stringify(actual.requests)===JSON.stringify(expected.requests),'Existing form changed request payloads');
     // Explicit opt-in affects this unsaved form only, not the stored stream.
     await card.locator('[name=content_matching]').selectOption('english-translated-v1');
     assert.equal(await card.locator('[name=nc_endpoint]').inputValue(),'articles');
     assert.equal(await card.locator('[data-keyword-translation]').isVisible(),false);
     const opted=page.waitForResponse(r=>r.url().includes('/api/profiles/preview-query')&&r.request().method()==='POST');
     await card.locator('[data-preview]').click();
     const changed=await opted;
     assert.equal(changed.status(),200);
     const content=await changed.json();
     assert.equal(content.content_matching.mode,'english-translated-v1');
     for(const request of content.requests)assert.deepEqual(request.parameters.search_in,['title_body','title_body_translated']);
   }
   console.log(`PASS: ${profiles.length} existing forms retain exact legacy payloads; explicit English-content opt-in previews correctly without saving.`);
   assert.equal(errors.length,0,'Browser runtime error');
 } finally {await browser.close();}
})().catch(()=>{console.error('Release browser smoke FAILED (private details suppressed).');process.exit(1)});
