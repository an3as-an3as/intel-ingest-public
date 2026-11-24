// Shared database choices; keys and provider endpoints are never entered here.
export const modelEfforts = (provider, info) => provider === 'anthropic'
  ? ['auto', ...(info?.efforts ?? ['low','medium','high','xhigh','max'])] : ['auto'];

export async function renderModelSettings({api,state,esc,toast},body) {
 let settings=await api('/api/settings/models'), notice='', busy=false;
 const catalogues=new Map();
 let draft;
 const reset=()=>draft=Object.fromEntries(['classify','summary'].map(p=>[p,{
  provider:settings.effective[p].provider||'anthropic', model:settings.effective[p].model,
  effort:settings.effective[p].effort,
 }]));
 reset();
 const capture=()=>{
  const form=body.querySelector('form');
  if(form)for(const p of ['classify','summary'])draft[p]={provider:form.elements[`${p}_provider`].value,
   model:form.elements[`${p}_model`].value,effort:form.elements[`${p}_effort`].value};
 };
 const configured=p=>settings.providers?.[p]?.configured ?? (p==='anthropic'&&settings.configured);
 const infoFor=(provider,id)=>(catalogues.get(provider)||[]).find(m=>m.id===id)||
  Object.values(settings.effective).find(c=>(c.provider||'anthropic')===provider&&c.model===id)?.metadata;
 const updateMeta=()=>{
  state.meta.models={classify:settings.effective.classify.model,summary:settings.effective.summary.model};
  state.meta.classify_configured=settings.effective.classify.configured;
  state.meta.summary_configured=settings.effective.summary.configured;
 };
 const draw=()=>{
  const providers=settings.providers||{anthropic:{label:'Anthropic',configured:settings.configured,configuration:'ANTHROPIC_API_KEY'}};
  body.innerHTML=`<div class="stack"><div class="card pad"><h2>Model providers and models</h2>
   <p>Choose a provider and model independently for classification and intelligence summaries. Cloud keys and endpoints stay in server configuration. Ollama can run on your machine, another computer or a protected server.</p>
   <p class="small muted">Refresh discovers models without inference or article text. Save verifies discovery/access, not output quality; some listed models may not support this task. Unsupported or malformed output fails closed. There is no automatic cross-provider fallback. Existing results are not reprocessed. Cloud inference may incur costs; local models use your hardware.</p>
   <p class="small muted">Ollama needs an explicit OLLAMA_BASE_URL reachable from the app. Container localhost is not the host computer. See the portable setup guide in docs/model-providers.md.</p>
   <p role="status" data-model-notice>${esc(notice)}</p></div>
   <form class="card pad" id="model-settings"><div class="grid-2">${[['classify','Article classification'],['summary','Intelligence summaries']].map(([p,label])=>{
    const choice=draft[p], options=new Map((catalogues.get(choice.provider)||[]).map(m=>[m.id,m]));
    if(choice.model&&!options.has(choice.model))options.set(choice.model,{id:choice.model,name:'Saved/current — refresh to verify'});
    return `<section><h2>${label}</h2><label>Provider</label><select name="${p}_provider">${Object.entries(providers).map(([id,info])=>`<option value="${esc(id)}" ${choice.provider===id?'selected':''}>${esc(info.label)}${info.configured?'':' — not configured'}</option>`).join('')}</select>
     <p class="small muted">${configured(choice.provider)?'Server configuration present; connectivity and model access are checked on refresh/save.':`Configure ${esc(providers[choice.provider]?.configuration||'this provider')} on the server first.`}</p>
     <button type="button" data-load="${p}" ${busy||!configured(choice.provider)?'disabled':''}>Refresh available models</button>
     <label>Model</label><select name="${p}_model" required><option value="">Choose a model after refreshing</option>${Array.from(options.values()).map(m=>`<option value="${esc(m.id)}" ${choice.model===m.id?'selected':''} ${p==='classify'&&m.structured_outputs===false?'disabled':''}>${esc(m.name)} — ${esc(m.id)}${m.structured_outputs===false?' (no structured classification)':''}</option>`).join('')}</select>
     <label>Effort</label><select name="${p}_effort">${modelEfforts(choice.provider,infoFor(choice.provider,choice.model)).map(e=>`<option value="${e}" ${choice.effort===e?'selected':''}>${e==='auto'?'Auto — adapter/provider default':e}</option>`).join('')}</select>
     <p class="small muted">${choice.provider==='anthropic'?'Only advertised effort levels are accepted when available.':'This adapter currently supports Auto effort only. Classification JSON is validated against the app schema.'}</p>
     <p class="small muted">Environment default: ${esc(settings.defaults[p].provider||'anthropic')} / <code>${esc(settings.defaults[p].model)}</code> · ${esc(settings.defaults[p].effort)}</p></section>`;
   }).join('')}</div>
   <div class="row" style="margin-top:12px"><button class="primary" ${busy||!['classify','summary'].every(p=>configured(draft[p].provider))?'disabled':''}>Save model choices</button>
    <button type="button" data-reset ${busy||!settings.overridden?'disabled':''}>Use environment defaults</button></div>
   <p class="setup-error" role="alert" data-model-error></p></form></div>`;
  const form=body.querySelector('form');
  if(busy)form.querySelectorAll('input,select,button').forEach(control=>control.disabled=true);
  for(const p of ['classify','summary']){
   form.elements[`${p}_provider`].onchange=()=>{capture();draft[p].model='';draft[p].effort='auto';notice='Refresh models for the selected provider, then choose a model. No settings have been saved.';draw();};
   form.elements[`${p}_model`].onchange=()=>{capture();if(!modelEfforts(draft[p].provider,infoFor(draft[p].provider,draft[p].model)).includes(draft[p].effort))draft[p].effort='auto';draw();};
  }
  body.querySelectorAll('[data-load]').forEach(button=>button.onclick=async()=>{
   capture();const provider=draft[button.dataset.load].provider;busy=true;draw();
   try{const result=await api(`/api/models?provider=${encodeURIComponent(provider)}`);catalogues.set(provider,result.models);notice=`${result.models.length} models discovered for ${providers[provider].label}. Availability does not guarantee schema/task compatibility. No inference was run.`;}
   catch(error){notice=error.message;}
   finally{busy=false;if(body.isConnected)draw();}
  });
  form.onsubmit=async event=>{
   event.preventDefault();capture();busy=true;draw();
   try{settings=await api('/api/settings/models',{method:'PUT',body:draft});reset();updateMeta();notice='Saved for future batches/jobs only. Existing articles and summaries were not changed.';toast('Provider/model choices saved');}
   catch(error){notice=error.message;}
   finally{busy=false;if(body.isConnected)draw();}
  };
  body.querySelector('[data-reset]').onclick=async()=>{
   if(!confirm('Use the server environment defaults for future jobs? Existing results will not be regenerated.'))return;
   busy=true;draw();
   try{settings=await api('/api/settings/models',{method:'DELETE'});reset();updateMeta();notice='Using environment defaults.';}
   catch(error){notice=error.message;}
   finally{busy=false;if(body.isConnected)draw();}
  };
 };
 updateMeta();draw(); // Discovery requires an explicit refresh, not just opening Settings.
}
