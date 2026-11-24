// Read-only real configuration checks + mocked provider/save UI interactions.
// NODE_PATH=/path/to/playwright/node_modules INTEL_PROVIDER_REVIEW_URL=http://127.0.0.1:8084 node scripts/test_model_providers_browser.cjs
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const base=process.env.INTEL_PROVIDER_REVIEW_URL;
assert.ok(base,'Set the isolated provider preview URL');
const url=new URL(base);
assert.ok(url.hostname==='127.0.0.1' && url.port && !['8080','8081','8083'].includes(url.port));
(async()=>{
 const browser=await chromium.launch({headless:true});
 const page=await browser.newPage();const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>{
  const target=new URL(route.request().url());
  if(target.origin===url.origin){
   if(!['GET','HEAD'].includes(route.request().method()))throw Error('Unmocked mutation blocked');
   return route.continue();
  }
  if(target.pathname.endsWith('marked.min.js'))return route.fulfill({contentType:'application/javascript',body:'window.marked={parse:()=>""};'});
  if(target.pathname.endsWith('purify.min.js'))return route.fulfill({contentType:'application/javascript',body:'window.DOMPurify={sanitize:()=>""};'});
  return route.abort();
 });
 try{
  const real=await (await page.request.get(base+'/api/settings/models')).json();
  const meta=await (await page.request.get(base+'/api/meta')).json();
  assert.equal(meta.environment,'development');
  assert.equal(real.configured,false,'Preview must not have live provider configuration');
  assert.equal(real.overridden,false,'Use an empty isolated preference database');
  let discovery=0;
  page.on('request',r=>{if(r.url().includes('/api/models?'))discovery++;});
  await page.goto(base+'/#/settings/models');
  await page.locator('#model-settings').waitFor();
  assert.equal(await page.locator('[name=classify_provider] option').count(),5);
  assert.equal(await page.locator('[name=summary_provider] option').count(),5);
  await page.locator('[name=classify_provider]').selectOption('ollama');
  assert.equal(await page.locator('[data-load=classify]').isDisabled(),true);
  await page.waitForTimeout(200);assert.equal(discovery,0);
  console.log('PASS: real offline preview lists five providers; no implicit discovery or credential entry.');

  let savedPayload=null, state=structuredClone(real);
  for(const info of Object.values(state.providers))info.configured=true;
  state.configured=true;
  const reply=(route,data)=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  await page.route('**/api/settings/models',route=>{
   if(route.request().method()==='PUT'){
    savedPayload=route.request().postDataJSON();
    state.overridden=true;
    for(const p of ['classify','summary'])state.effective[p]={...savedPayload[p],configured:true};
   }
   return reply(route,state);
  });
  await page.route('**/api/models?*',route=>{
   const provider=new URL(route.request().url()).searchParams.get('provider');
   const id=provider==='ollama'?'qwen-local:8b':'test-chat';
   return reply(route,{provider,models:[{id,name:id,provider,efforts:[],structured_outputs:null,lifecycle:'active'}]});
  });
  await page.reload();await page.locator('#model-settings').waitFor();
  assert.equal(discovery,0);
  await page.locator('[name=classify_provider]').selectOption('openai');
  await page.locator('[data-load=classify]').click();
  await page.locator('[name=classify_model] option[value="test-chat"]').waitFor({state:'attached'});
  await page.locator('[name=classify_model]').selectOption('test-chat');
  await page.locator('[name=summary_provider]').selectOption('ollama');
  await page.locator('[data-load=summary]').click();
  await page.locator('[name=summary_model] option[value="qwen-local:8b"]').waitFor({state:'attached'});
  await page.locator('[name=summary_model]').selectOption('qwen-local:8b');
  assert.equal(await page.locator('[name=classify_effort] option').count(),1);
  assert.equal(await page.locator('[name=summary_effort] option').count(),1);
  await page.locator('#model-settings button.primary').click();
  await page.waitForFunction(()=>document.querySelector('[data-model-notice]').textContent.includes('Saved for future'));
  assert.equal(savedPayload.classify.provider,'openai');assert.equal(savedPayload.summary.provider,'ollama');
  assert.equal(savedPayload.summary.model,'qwen-local:8b');
  assert.equal(discovery,2);
  assert.ok(!JSON.stringify(savedPayload).includes('api_key'));
  assert.equal((await (await page.request.get(base+'/api/settings/models')).json()).overridden,false);
  assert.equal(errors.length,0);
  console.log('PASS: explicit mocked discovery, mixed provider save/reload and Auto-only efforts. Real database unchanged; no inference.');
 }finally{await browser.close();}
})().catch(()=>{console.error('Provider browser smoke FAILED (details suppressed)');process.exit(1)});
