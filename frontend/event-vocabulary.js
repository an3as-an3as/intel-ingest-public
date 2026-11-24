import {enhanceMultiSelects} from './filters.js';

const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const DEFAULT = 'legacy-v1';

function tierControl(catalog, version, selected) {
  const allowed = catalog[version]?.tiers || Object.fromEntries(selected.map(t => [t, `Unavailable tier: ${t}`]));
  if (Object.keys(allowed).length === 1 && allowed.core) return '<p class="small muted">One keyword list per category; no tier selection required.</p><select name="event_vocabulary_tiers" multiple hidden data-enhanced="true"><option value="core" selected>Core</option></select>';
  return `<label>Event vocabulary tiers (choose at least one)</label><select name="event_vocabulary_tiers" multiple size="3" data-empty-summary="Choose at least one vocabulary tier">${Object.entries(allowed).map(([key,label]) => `<option value="${esc(key)}" ${selected.includes(key)?'selected':''}>${esc(label)}</option>`).join('')}</select>`;
}

export function eventBudgetForm(params = {}) {
  return `<div data-event-budget><div class="grid-2">
    <div><label>Maximum API requests per poll (1–16)</label><input name="max_requests_per_poll" type="number" min="1" max="16" required value="${esc(params.max_requests_per_poll ?? 16)}"></div>
    <div><label>Nominal credit ceiling per poll (optional)</label><input name="max_credits_per_poll" type="number" min="1" max="10000" value="${esc(params.max_credits_per_poll ?? '')}" placeholder="No additional credit ceiling"></div>
  </div><p class="small muted">The compiler refuses plans over these limits before paid article requests. This is not a monthly spending cap or an exact billing guarantee; Enterprise pricing may be unknown.</p></div>`;
}

export function eventVocabularyForm(catalog, params = {}, {includeBudget = true} = {}) {
  const version=params.event_vocabulary_version || DEFAULT;
  const versions={...catalog};
  if (!versions[version]) versions[version]={label:`Unavailable vocabulary: ${version}`};
  const planner=params.query_planner_version || (version==='legacy-v1' && !params.coverage_regions?.length && !params.multilingual_enabled ? 'legacy-v1' : 'bounded-v1');
  return `<section data-event-vocabulary>
    <input type="hidden" name="query_planner_version" value="${esc(planner)}">
    <p class="small muted">Existing streams retain legacy request planning until you opt into a new library, regions or translations. Enhanced selections require a new preview and confirmation.</p>
    <label>Event keyword library</label><select name="event_vocabulary_version">${Object.entries(versions).map(([key,value]) => `<option value="${esc(key)}" ${key===version?'selected':''}>${esc(value.label)}</option>`).join('')}</select>
    <p class="small muted" data-event-description>${esc(catalog[version]?.description || 'This saved version is unavailable. Do not silently substitute another library.')}</p>
    <div data-event-tiers>${tierControl(catalog,version,params.event_vocabulary_tiers || ['core'])}</div>
    <p class="small muted">English phrases only at this stage. Indicators and broad discovery are opt-in; they can increase noise and request cost. Preview added/removed terms before saving. Selecting a library does not change a saved stream until Save.</p>
    ${includeBudget ? eventBudgetForm(params) : ''}
  </section>`;
}

export function wireEventVocabulary(form, catalog) {
  const section=form.querySelector('[data-event-vocabulary]');
  if (!section) return;
  form.elements.event_vocabulary_version.onchange=()=>{
    const version=form.elements.event_vocabulary_version.value;
    const selected=Array.from(form.elements.event_vocabulary_tiers.selectedOptions,o=>o.value);
    const allowed=catalog[version]?.tiers || {};
    const retained=selected.filter(t=>Object.hasOwn(allowed,t));
    section.querySelector('[data-event-tiers]').innerHTML=tierControl(catalog,version,retained.length?retained:['core']);
    section.querySelector('[data-event-description]').textContent=catalog[version]?.description || 'Unavailable saved version';
    enhanceMultiSelects(section);
    const preview=form.querySelector('[data-q]');
    if (preview) {preview.hidden=false;preview.style.display='block';preview.textContent='Vocabulary changed. Preview again to inspect terms, request count and costs before saving.';}
  };
}

export function readEventVocabulary(form) {
  const credit=form.elements.max_credits_per_poll.value.trim();
  const enhanced=form.elements.event_vocabulary_version.value!=='legacy-v1' ||
    (form.elements.coverage_regions?.selectedOptions.length || 0)>0 || form.elements.multilingual_enabled?.checked ||
    form.elements.content_matching?.value==='english-translated-v1';
  return {query_planner_version:enhanced ? 'bounded-v1' : (form.elements.query_planner_version?.value || 'legacy-v1'),
    event_vocabulary_version:form.elements.event_vocabulary_version.value,
    event_vocabulary_tiers:Array.from(form.elements.event_vocabulary_tiers.selectedOptions,o=>o.value),
    max_requests_per_poll:Number(form.elements.max_requests_per_poll.value),
    ...(credit ? {max_credits_per_poll:Number(credit)} : {})};
}
