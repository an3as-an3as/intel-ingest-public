export const queryPreviewText = r => {
  if (!r.requests) return r.parameters ? `${r.method} ${r.endpoint}\n${JSON.stringify(r.parameters, null, 2)}\n\n${r.note || ''}` : r.query;
  const lines = [`${r.request_count} API request${r.request_count === 1 ? '' : 's'} per poll — each consumes quota/credits.`];
  if (r.query_planner_version) lines.push(`Query planner: ${r.query_planner_version}`);
  if (r.content_matching) {
    const fields=r.content_matching.search_in;
    lines.push(`Content matching: ${r.content_matching.mode} · search fields: ${Array.isArray(fields) ? fields.join(', ') : fields || 'endpoint default'}`);
  }
  if (r.content_matching?.mode==='english-translated-v1') lines.push(r.content_matching.note);
  if (r.vocabulary) {
    lines.push(`Vocabulary: ${r.vocabulary.version} · tiers: ${r.vocabulary.tiers.join(', ')} · ${r.vocabulary.term_count} event terms · language: ${r.vocabulary.language}`);
    if (r.vocabulary.experimental) lines.push('EXPERIMENTAL: opt-in; not yet validated against live reporting.');
    lines.push(`Selected event terms: ${r.vocabulary.terms.join(', ') || '(none)'}`,
      `Added vs Legacy v1: ${r.vocabulary.added_vs_legacy.join(', ') || '(none)'}`,
      `Removed vs Legacy v1: ${r.vocabulary.removed_vs_legacy.join(', ') || '(none)'}`);
  }
  if (r.translations?.enabled) lines.push(`Approved multilingual expansion: ${r.translations.languages.join(', ')} · review: ${r.translations.review_id} · original query retained. Translation generation is separate from search credits; no models run during polling.`);
  if ('estimated_credits_per_poll' in r) lines.push(`Nominal estimated credits per poll: ${r.estimated_credits_per_poll ?? 'unknown'}`,
    `30-day scheduled estimate: ${r.estimated_credits_per_30_days ?? 'unknown'} credits / ${r.estimated_requests_per_30_days} requests (excludes retries and manual runs).`);
  if (r.budget) lines.push(`Request limit: ${r.budget.max_requests_per_poll} / poll · nominal credit ceiling: ${r.budget.max_credits_per_poll ?? 'not set'}`);
  lines.push('', ...r.requests.map((request, i) => `Request ${i + 1}: ${request.method} ${request.endpoint}${request.translation_language ? ` · lane: ${request.translation_language}` : ''}\n${JSON.stringify(request.parameters, null, 2)}`), '', r.note || '');
  return lines.join('\n\n');
};

// Searchable, touch-friendly checkbox selectors, with native selects as the data source.
export function enhanceMultiSelects(root) {
  root.querySelectorAll('select[multiple]:not([data-enhanced])').forEach(select => {
    select.dataset.enhanced = 'true';
    select.hidden = true;
    const picker = document.createElement('section'); picker.className = 'multi-picker';
    const summary = document.createElement('div'); summary.className = 'multi-summary small muted';
    summary.setAttribute('aria-live', 'polite');
    const label = select.previousElementSibling?.textContent || select.name;
    const search = document.createElement('input'); search.type = 'search'; search.placeholder = 'Search options…';
    search.setAttribute('aria-label', `Search ${label}`);
    const list = document.createElement('div'); list.className = 'multi-options';
    list.setAttribute('role', 'group'); list.setAttribute('aria-label', label);
    const empty = document.createElement('p'); empty.className = 'small muted'; empty.hidden = select.options.length > 0;
    empty.setAttribute('role', 'status');
    empty.textContent = select.options.length ? 'No matching options. Try a different search.' : 'No options available yet.';
    const clear = document.createElement('button'); clear.type = 'button'; clear.textContent = 'Clear selections';
    const update = () => {
      const selected = Array.from(select.selectedOptions, o => o.textContent);
      summary.textContent = selected.length ? `${selected.length} selected: ${selected.slice(0, 3).join(', ')}${selected.length > 3 ? '…' : ''}` : (select.dataset.emptySummary || 'Any / no restriction — select options');
      summary.title = selected.join(', ');
      clear.disabled = selected.length === 0;
    };
    Array.from(select.options).forEach(option => {
      const row = document.createElement('label'); row.className = 'inline';
      const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = option.selected;
      row.append(checkbox, document.createTextNode(option.textContent));
      row.dataset.search = `${option.textContent} ${option.value}`.toLowerCase();
      checkbox.onchange = () => { option.selected = checkbox.checked; update(); select.dispatchEvent(new Event('change', {bubbles: true})); };
      list.append(row);
    });
    search.oninput = () => {
      const rows = Array.from(list.querySelectorAll('label'));
      rows.forEach(row => row.hidden = !row.dataset.search.includes(search.value.toLowerCase().trim()));
      empty.hidden = rows.some(row => !row.hidden);
    };
    search.onkeydown = event => {
      if (event.key === 'Enter') event.preventDefault();
      if (event.key === 'Escape') { event.preventDefault(); search.value = ''; search.oninput(); }
    };
    clear.onclick = () => {
      Array.from(select.options).forEach(o => o.selected = false);
      list.querySelectorAll('input').forEach(c => c.checked = false); update();
      select.dispatchEvent(new Event('change', {bubbles: true}));
    };
    picker.append(search, summary, list, empty, clear); select.after(picker); update();
  });
}

const listSchema = schema => schema.type === 'array' ? schema : (schema.anyOf || schema.oneOf || []).find(s => s.type === 'array');

export function nativeFilterForm(meta, options, params, esc) {
  const mode = params.endpoint || Object.keys(meta.modes)[0];
  const saved = {...(mode === 'v3' && params.themes?.length ? {theme: params.themes.join(',')} : {}), ...(params.native_filters || {})};
  const modes = Object.keys(meta.modes);
  const selectMode = `<label>NewsCatcher endpoint</label><select name="nc_endpoint">${[...new Set([...modes, mode])].map(m => `<option value="${esc(m)}" ${m === mode ? 'selected' : ''}>${esc(m === 'search' ? 'Search — ranked recent news' : m === 'articles' ? 'Articles — Boolean search & extended filters' : 'Enterprise v3 search')}${modes.includes(m) ? '' : ' (unavailable with configured API key type)'}</option>`).join('')}</select>`;
  const fields = Object.entries(meta.modes).map(([m, properties]) => `<div class="grid-2" data-nc-mode="${m}" ${mode === m ? '' : 'hidden'}>${Object.entries(properties).filter(([key]) => !meta.managed.includes(key)).map(([key, schema]) => {
    const value = m === mode ? saved[key] : undefined;
    const array = listSchema(schema);
    let choices = array?.items?.enum || schema['x-options'];
    if (key === 'not_countries') choices = options.countries;
    if (['not_languages', 'not_lang'].includes(key)) choices = options.languages;
    const name = `nc_${m}_${key}`;
    const label = key.replaceAll('_', ' ');
    const desc = schema.description || '';
    const example = schema.example ?? schema.examples?.[0] ?? '';
    const attr = `name="${esc(name)}" data-native-filter="${esc(key)}" data-filter-mode="${m}"`;
    let control;
    if (choices) {
      const entries = Array.isArray(choices) ? choices.map(v => [v, v]) : Object.entries(choices);
      const selected = Array.isArray(value) ? value : typeof value === 'string' ? value.split(',').map(s => s.trim()) : [];
      entries.push(...selected.filter(v => !entries.some(([k]) => k === v)).map(v => [v,v]));
      control = `<select multiple ${attr} data-filter-type="${array ? 'array' : 'csv'}">${entries.map(([k,v]) => `<option value="${esc(k)}" ${selected.includes(k) ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select>`;
    } else if (schema.enum || schema.type === 'boolean') {
      const entries = schema.enum || ['true','false'];
      control = `<select ${attr} data-filter-type="${schema.type === 'boolean' ? 'boolean' : 'string'}"><option value="">Automatic / provider default</option>${entries.map(v => `<option value="${esc(v)}" ${String(value) === String(v) ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select>`;
    } else if (['integer','number'].includes(schema.type)) {
      control = `<input type="number" ${attr} data-filter-type="number" step="${schema.type === 'integer' ? '1' : 'any'}" ${schema.minimum !== undefined ? `min="${schema.minimum}"` : ''} ${schema.maximum !== undefined ? `max="${schema.maximum}"` : ''} value="${esc(value ?? '')}" placeholder="Automatic / provider default">`;
    } else {
      control = `<input ${attr} data-filter-type="${array ? 'array' : 'string'}" value="${esc(Array.isArray(value) ? value.join(', ') : value ?? '')}" placeholder="${esc(typeof example === 'string' ? example : Array.isArray(example) ? example.join(', ') : '')}">`;
    }
    return `<div class="native-field"><label>${esc(label)} <code>(${esc(key)})</code>${schema.deprecated ? ' — deprecated' : ''}</label>${control}${desc ? `<details class="filter-help"><summary>Help / constraints</summary><p>${esc(desc)}</p></details>` : ''}</div>`;
  }).join('')}</div>`).join('');
  return `${selectMode}<details class="native-filters"><summary>All native API filters & response controls</summary><p class="small muted">Blank means automatic/provider default. On Articles, publisher-country filters are ignored when sources is set. These controls are specific to the selected endpoint; unsupported filters are rejected, not silently ignored. Country/language inclusions, query and result limit have dedicated controls elsewhere. Fixed dates or search_window override automatic polling windows and can replay the same period. One page is fetched per query part; long preset queries may require multiple paid requests per poll. Some filters/enrichments require Enterprise access. Consult each field's help for constraints.</p>${fields}</details>`;
}

export function readNativeFilters(form) {
  const mode = form.elements.nc_endpoint.value, filters = {};
  form.querySelectorAll('[data-native-filter]').forEach(input => {
    if (input.dataset.filterMode !== mode) return;
    const type = input.dataset.filterType;
    let value = input.multiple ? Array.from(input.selectedOptions, o => o.value) : input.value.trim();
    if (value === '' || (Array.isArray(value) && !value.length)) return;
    if (type === 'array' && !Array.isArray(value)) value = value.split(/[,\n]/).map(v => v.trim()).filter(Boolean);
    if (Array.isArray(value) && !value.length) return;
    if (type === 'csv' && Array.isArray(value)) value = value.join(',');
    if (type === 'number') value = Number(value);
    if (type === 'boolean') value = value === 'true';
    filters[input.dataset.nativeFilter] = value;
  });
  return {endpoint: mode, native_filters: filters};
}
