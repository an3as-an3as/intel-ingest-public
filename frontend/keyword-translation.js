import {enhanceMultiSelects} from './filters.js';

const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const suggestedTranslationLanguages=(countries,metadata)=>[...new Set(countries.flatMap(c=>metadata?.mapping?.countries?.[c]||[]).filter(l=>l!=='en'))].sort();

export function keywordTranslationForm(metadata, languages, params={}) {
 const selected=params.translation_auto_languages===false?(params.translation_languages||[]):suggestedTranslationLanguages([...(params.coverage_countries||[]), ...(params.coverage_regions||[]).flatMap(r=>metadata.regions?.[r]?.countries||[])],metadata);
 return `<section data-keyword-translation class="card pad" style="margin-top:12px">
  <h3>Country-aware keyword translation (experimental)</h3>
  <p class="small muted">Coverage countries suggest reporting languages, not publisher countries. Original terms and the original query are retained. No translated search is activated until you approve and Save.</p>
  <label class="inline"><input type="checkbox" name="multilingual_enabled" ${params.multilingual_enabled?'checked':''}> Enable multilingual collection</label>
  <input type="hidden" name="translation_review_id" value="${esc(params.translation_review_id||'')}">
  <p class="small muted" data-translation-suggestions></p>
  <div data-translation-content ${params.multilingual_enabled?'':'hidden'}>
   <label class="inline"><input type="checkbox" name="translation_auto_languages" ${params.translation_auto_languages!==false?'checked':''}> Automatically suggest languages from coverage countries</label>
   <label>Language of custom keywords (event/country presets remain English)</label>
   <select name="keyword_source_language">${Object.entries(languages).map(([key,label])=>`<option value="${esc(key)}" ${key===(params.keyword_source_language||'en')?'selected':''}>${esc(label)}</option>`).join('')}</select>
   <label>Additional reporting languages (maximum ${esc(metadata?.max_languages||8)}; English/original query retained)</label>
   <select name="translation_languages" multiple size="5" data-empty-summary="Choose coverage countries or additional reporting languages">${Object.entries(languages).filter(([key])=>key!=='en').map(([key,label])=>`<option value="${esc(key)}" ${selected.includes(key)?'selected':''}>${esc(label)}</option>`).join('')}</select>
   <p class="small muted">Changing this list switches to manual overrides. Article-language restrictions are never widened silently.</p>
   <button type="button" data-translation-include>Include selected targets in the existing article-language filter</button>
   <p class="small muted">This button only changes which article languages are allowed; it does not prepare translations. A translation review is limited to ${esc(metadata?.max_rows||400)} phrase/language rows, including country names. English queries alone do not guarantee local-language coverage.</p>
   <button type="button" data-translation-prepare>Prepare / refresh translation review</button>
   <p class="small" role="status" data-translation-message></p>
   <div data-translation-review></div>
  </div>
 </section>`;
}

export function readKeywordTranslation(form) {
 const e=form.elements;
 return {keyword_source_language:e.keyword_source_language?.value||'en',multilingual_enabled:e.multilingual_enabled.checked,translation_auto_languages:e.translation_auto_languages.checked,
  translation_languages:Array.from(e.translation_languages.selectedOptions,o=>o.value),
  ...(e.translation_review_id.value?{translation_review_id:e.translation_review_id.value}:{})};
}

export function translationReviewHtml(review, edits=new Map()) {
 return `<p class="small muted">${review.rows.length} phrase/language rows · ${review.missing_count} missing suggestions · ${esc(review.mapping_version)} · Model calls: ${review.model_calls} / ${review.max_model_calls_per_review}</p>
  ${review.language_conflicts.length?`<p><strong>Language filter conflict: ${esc(review.language_conflicts.join(', '))}. Adjust the article-language filter/exclusions or choose different targets before approval.</strong></p>`:''}
  <details><summary>Review notes and limitations</summary><ul>${review.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></details>
  <p class="small muted">Inspect every proposal. One to three literal phrases per row, one per line. Names/acronyms and unchanged terms may be deliberately retained. Missing phrases are never silently invented or skipped.</p>
  <div style="max-height:480px;overflow:auto"><table><thead><tr><th>Language / concept</th><th>Source phrase</th><th>Translation suggestions / reviewed terms</th><th>Decision</th></tr></thead><tbody>${review.rows.map(row=>{
   const edit=edits.get(row.id);const terms=edit?.text??(row.approved_terms||row.candidates).join('\n');
   return `<tr data-translation-row="${esc(row.id)}"><td>${esc(row.language)}<br>${esc(row.kind)} (${esc(row.source_language||'en')} → ${esc(row.language)})<br><span class="small">${esc(row.contexts.join(', '))}</span></td>
    <td>${esc(row.source)}<br><span class="small muted">${esc(row.origin)}</span></td>
    <td><textarea data-translation-text rows="2" style="min-width:180px;min-height:48px" ${review.approved?'disabled':''}>${esc(terms)}</textarea></td>
    <td><label class="inline"><input type="checkbox" data-translation-keep ${(edit?.keep??row.keep_original)?'checked':''} ${review.approved?'disabled':''}> Keep original only (intentional)</label></td></tr>`;
  }).join('')}</tbody></table></div>
  <p class="small muted">Live model generation: ${review.live_generation_enabled?'explicit opt-in available':'disabled; offline suggestions/manual review only'}. At most ${review.max_model_terms} missing rows and one request per review, no automatic retries. This is not a global monthly token budget.</p>
  <button type="button" data-translation-generate ${review.approved||!review.live_generation_enabled||!review.missing_count||review.model_calls>=review.max_model_calls_per_review?'disabled':''}>Generate missing suggestions with model (paid, explicit action)</button>
  <label class="inline"><input type="checkbox" data-translation-confirm ${review.approved?'checked disabled':''}> I reviewed all rows, intentional originals and language restrictions</label>
  <button type="button" data-translation-approve ${review.approved?'disabled':''}>Approve translations & preview requests (not Save)</button>
  ${review.approved?'<p class="small"><strong>Approved snapshot is frozen. Preview and Save to apply; refresh the review to edit it.</strong></p>':''}`;
}

function resetSelect(select, values) {
 Array.from(select.options).forEach(o=>o.selected=values.includes(o.value));
 if(select.nextElementSibling?.classList.contains('multi-picker')) select.nextElementSibling.remove();
 delete select.dataset.enhanced;select.hidden=false;enhanceMultiSelects(select.parentElement);
}

export function wireKeywordTranslation(form, metadata, api, readParams, preview) {
 const box=form.querySelector('[data-keyword-translation]');if(!box)return;
 const e=form.elements,output=box.querySelector('[data-translation-review]'),message=box.querySelector('[data-translation-message]');
 let draft=null,serial=0,timer=null,busy=false,filterOnlyChange=false;const edits=new Map();
 const active=()=>e.source.value==='newscatcher'&&e.multilingual_enabled.checked;
 const note=text=>message.textContent=text;
 const updateSuggestion=()=>{
  const countries=[...Array.from(e.coverage_countries.selectedOptions,o=>o.value), ...Array.from(e.coverage_regions?.selectedOptions||[],o=>o.value).flatMap(r=>metadata.regions?.[r]?.countries||[])];
  const languages=suggestedTranslationLanguages(countries,metadata);
  box.querySelector('[data-translation-suggestions]').textContent=`Suggested additional languages: ${languages.join(', ')||'none; choose coverage countries or override manually'}. Original English terms are retained.`;
  box.querySelector('[data-translation-content]').hidden=!active();
  return languages;
 };
 const invalidate=()=>{serial++;e.translation_review_id.value='';draft=null;edits.clear();output.innerHTML='';note('Search settings changed; translations need a fresh review.');};
 const remember=()=>{
  output.querySelectorAll('[data-translation-row]').forEach(row=>edits.set(row.dataset.translationRow,{text:row.querySelector('[data-translation-text]').value,keep:row.querySelector('[data-translation-keep]').checked}));
 };
 const draw=()=>{
  output.innerHTML=translationReviewHtml(draft,edits);
  output.querySelectorAll('[data-translation-text], [data-translation-keep]').forEach(input=>input.addEventListener('input',()=>{remember();output.querySelector('[data-translation-confirm]').checked=false;}));
  output.querySelector('[data-translation-generate]').onclick=async()=>{
   if(busy||!confirm('Send the missing positive search phrases and event/geography context to Anthropic for a paid translation request? This is separate from NewsCatcher search credits; candidates will still require review.'))return;
   busy=true;const generation=serial;
   try {remember();const result=await api(`/api/ingestion/translation-plans/${encodeURIComponent(draft.id)}/generate`,{method:'POST'});if(generation!==serial||!form.isConnected)return;draft=result;draw();note('Model candidates are still unapproved. Inspect all rows.');}
   catch(error){if(generation===serial)note(error.message);}finally{busy=false;}
  };
  output.querySelector('[data-translation-approve]').onclick=async()=>{
   if(busy)return;
   if(!output.querySelector('[data-translation-confirm]').checked){note('Confirm that you reviewed every row before approval.');return;}
   remember();busy=true;const approvalSerial=serial;
   const params=readParams();
   try {
    const decisions=draft.rows.map(row=>({id:row.id,translations:edits.get(row.id).text.split(/\n+/).map(t=>t.trim()).filter(Boolean),keep_original:edits.get(row.id).keep}));
    const result=await api(`/api/ingestion/translation-plans/${encodeURIComponent(draft.id)}/approve`,{method:'POST',body:{params,decisions,confirmed:true}});
    if(approvalSerial!==serial||!active()||!form.isConnected)return;
    draft=result.review;e.translation_review_id.value=result.params_patch.translation_review_id;edits.clear();draw();
    note('Approved, not saved. Inspect the full query/credit preview, then Save to apply.');await preview();
   }catch(error){if(approvalSerial===serial)note(error.message);}finally{busy=false;}
  };
 };
 const prepare=async()=>{
  clearTimeout(timer);if(!active()||!form.isConnected)return;
  const request=++serial;const params=readParams();note('Preparing cached/offline translation suggestions…');
  try {const result=await api('/api/ingestion/translation-plans',{method:'POST',body:{params}});if(request!==serial||!active()||!form.isConnected)return;draft=result;edits.clear();draw();note('Suggestions prepared. Missing rows require manual completion or an explicit keep-original decision. Nothing is active until approval and Save.');}
  catch(error){if(request===serial)note(error.message);}
 };
 const schedule=()=>{clearTimeout(timer);if(active())timer=setTimeout(prepare,500);};
 box.querySelector('[data-translation-prepare]').onclick=()=>{invalidate();prepare();};
 box.querySelector('[data-translation-include]').onclick=()=>{
  const current=Array.from(e.nc_languages.selectedOptions,o=>o.value);
  if(!current.length){note('The positive article-language filter is already unrestricted. Resolve any native excluded languages manually.');return;}
  // Updating an allowed-language filter is not a request to build translation rows.
  // Still invalidate the approved snapshot and notify the rest of the form.
  filterOnlyChange=true;
  try {
   resetSelect(e.nc_languages,[...new Set([...current,...Array.from(e.translation_languages.selectedOptions,o=>o.value)])]);
   e.nc_languages.dispatchEvent(new Event('change',{bubbles:true}));
  } finally {filterOnlyChange=false;}
 };
 const semantic=name=>['keyword_source_language','coverage_countries','coverage_regions','event_presets','event_vocabulary_version','event_vocabulary_tiers','nc_languages','nc_endpoint','content_matching'].includes(name)||/^nc_.*_not_(languages|lang)$/.test(name);
 form.addEventListener('change',event=>{
  const name=event.target.name;
  if(name==='nc_languages'&&filterOnlyChange){
   clearTimeout(timer);invalidate();updateSuggestion();
   note('Article-language filter updated; no translation plan was requested. Any previous approval is invalidated. Use Prepare / refresh translation review separately; its phrase/language limit still applies.');
   return;
  }
  if(name==='source'){updateSuggestion();return;}
  if(name==='multilingual_enabled'){
   updateSuggestion();if(!active()){serial++;clearTimeout(timer);return;}
   if(e.translation_review_id.value){loadSaved();}else schedule();return;
  }
  if(name==='translation_languages')e.translation_auto_languages.checked=false;
  if(name==='coverage_countries'||name==='coverage_regions'||name==='translation_auto_languages'){
   const suggested=updateSuggestion();if(e.translation_auto_languages.checked)resetSelect(e.translation_languages,suggested);
  }
  if(semantic(name)||name==='translation_auto_languages'||name==='translation_languages'){invalidate();updateSuggestion();schedule();}
 });
 form.addEventListener('input',event=>{
  if(['keywords','nc_query'].includes(event.target.name)){invalidate();schedule();}
 });
 async function loadSaved(){
  const request=++serial;
  try {const result=await api(`/api/ingestion/translation-plans/${encodeURIComponent(e.translation_review_id.value)}`);if(request!==serial||!active()||!form.isConnected)return;draft=result;if(!result.approved)e.translation_review_id.value='';draw();note(result.approved?'Loaded saved approved snapshot. No translation model was called.':'Loaded an unapproved draft; review and approve it before saving.');}
  catch(error){if(request===serial){e.translation_review_id.value='';note(error.message);}}
 }
 updateSuggestion();if(active()&&e.translation_review_id.value)loadSaved();else if(active())schedule();
}
