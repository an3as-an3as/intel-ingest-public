const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function newStreamParams(params={}) {
 return {endpoint:'articles', content_matching:'english-translated-v1',
         event_vocabulary_version:'optimized-v1', query_planner_version:'bounded-v1', ...params};
}

export function contentMatchingForm(params={}) {
 const mode=params.content_matching||'provider-default';
 const choices={'provider-default':'Existing endpoint settings — unchanged',
                'english-translated-v1':'English keywords across languages — Articles'};
 if(!choices[mode])choices[mode]=`Unavailable saved mode: ${mode}`;
 return `<label>Content matching</label><select name="content_matching">${Object.entries(choices).map(([key,label])=>`<option value="${esc(key)}" ${mode===key?'selected':''}>${esc(label)}</option>`).join('')}</select>
 <p class="small muted">English mode searches original content and English translations using one English keyword set. No translated keyword lists, translation review or extra language lanes are required. It uses Articles (5 nominal credits per request); account coverage and result caps still apply. Keep custom keywords in English. Publisher/event-location restrictions are unchanged.</p>
 <p class="small muted" data-content-matching-note></p>`;
}

export function wireContentMatching(form) {
 const control=form.elements.content_matching;
 if(!control)return;
 const note=form.querySelector('[data-content-matching-note]');
 const render=()=>{
  const english=control.value==='english-translated-v1';
  const translations=form.querySelector('[data-keyword-translation]');
  if(translations)translations.hidden=english;
  if(note)note.textContent=english
   ? 'Articles searches title_body + title_body_translated. Select the article languages you want, or leave them unrestricted. Advanced search_in must not conflict. No keyword translation is performed.'
   : 'Saved endpoint matching is preserved. Search with only non-English languages uses original-language matching; Articles uses its selected search_in fields.';
 };
 control.addEventListener('change',()=>{
  if(control.value==='english-translated-v1'){
   form.elements.nc_endpoint.value='articles';
   form.elements.nc_endpoint.dispatchEvent(new Event('change',{bubbles:true}));
   if(form.elements.multilingual_enabled.checked){
    form.elements.multilingual_enabled.checked=false;
    form.elements.multilingual_enabled.dispatchEvent(new Event('change',{bubbles:true}));
   }
   form.elements.translation_review_id.value='';
  }
  render();
 });
 render(); // Do not migrate saved settings merely by opening the form.
}
