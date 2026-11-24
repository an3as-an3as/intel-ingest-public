// Progressive disclosure over ONE form. Switching modes never serializes/rebuilds controls.
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const STREAM_STEPS = [
  ['Purpose', 'What reporting do you want to collect?', 'Give this stream a name and, optionally, a few literal phrases. Any phrase can match. Collection finds candidates; intelligence requirements decide relevance later. You can leave keywords empty and choose developments in step 3.'],
  ['Geography', 'Where should the reporting be about?', 'Choose regions and/or countries whose names should appear in reporting. Regions expand to countries, all treated as alternatives; this geography group must match alongside your topic and developments. Publisher country is a separate, optional restriction.'],
  ['Developments', 'What kinds of developments matter?', 'Choose relevant developments, or leave events unrestricted if your keywords are enough. More or broader terms can find more reporting, but also more noise and paid requests. New streams use the provisional single-list Optimized v1 baseline; saved streams keep their existing library.'],
  ['Languages', 'Which reporting languages should we include?', 'Article language restricts which reports may be returned. New streams search original and English-translated content with English keywords; no keyword translations or review are required. Existing streams keep their endpoint settings. We never silently widen article-language restrictions. Local-language keyword expansion remains an optional alternative.'],
  ['Collection limits', 'How often should we check, and how much collection should we allow?', 'More frequent checks consume more search quota. Limits apply across all query parts and languages per poll, not per month. Translation and later article classification have separate costs.'],
  ['Review', 'Does this describe the stream you intended?', 'Inspect the summary, warnings and full request preview. Saving creates a paused stream: it does not start collection. You can edit every setting afterward and set up an intelligence dashboard separately.'],
];

export const pausedStream = payload => ({...payload, enabled:false});
export const streamFingerprint = payload => JSON.stringify(pausedStream(payload));

export function streamSummaryHtml(payload, options = {}) {
  const p = payload.params, list = (values, catalog = {}) => (values || []).map(v => catalog[v] || v).join(', ') || 'Unrestricted / none selected';
  const row = (label, value) => `<dt>${esc(label)}</dt><dd>${esc(value)}</dd>`;
  return `<dl class="stream-summary">
    ${row('Name', payload.name)}${row('Source', payload.source)}${row('Saved state', 'Paused — collection must be enabled separately')}
    ${row('Keywords (any matches)', (p.keywords || []).join(', ') || 'No keyword requirement')}
    ${row('Exclusions', (p.exclude_keywords || []).join(', ') || 'None')}
    ${row('Regional focus', list(p.coverage_regions, options.coverage_regions))}
    ${row('Additional coverage country names', list(p.coverage_countries, options.countries))}
    ${row('Developments', list(p.event_presets, options.event_presets))}
    ${row('Vocabulary', `${p.event_vocabulary_version || 'legacy-v1'} · ${(p.event_vocabulary_tiers || ['core']).join(', ')}`)}
    ${row('Query planning', p.query_planner_version || 'legacy-v1')}
    ${row('Content matching', p.content_matching || 'provider-default')}
    ${row('Article languages', list(p.languages, options.languages))}
    ${row('Multilingual search', p.multilingual_enabled ? `Opted in · approved snapshot: ${p.translation_review_id || 'MISSING — review required'}` : 'Off')}
    ${p.multilingual_enabled ? row('Additional targets', `${p.translation_auto_languages ? 'Country-suggested' : 'Manual'}: ${list(p.translation_languages, options.languages)}`) : ''}
    ${p.query ? row('Advanced query — replaces keywords', p.query) : ''}
    ${row('Polling', `Every ${payload.interval_minutes} minutes, once enabled`)}
    ${row('Request ceiling per poll', p.max_requests_per_poll ?? 'Provider defaults')}
    ${row('Nominal credit ceiling per poll', p.max_credits_per_poll ?? 'Not set — no credit ceiling')}
  </dl><details><summary>All retained settings: endpoint, publisher restrictions and advanced filters</summary><dl class="stream-summary">
    ${row('Custom keyword source language', p.keyword_source_language || 'en')}
    ${row('First-run lookback', `${p.lookback_hours} hours`)}${row('Article cap per request/page', p.max_records)}
    ${row('Publisher countries', list(p.source_countries, options.countries))}
    ${row('Dashboard links', (payload.dashboard_ids || []).join(', ') || 'None selected; dashboards without links use all streams')}
    ${row('Endpoint', p.endpoint || (payload.source === 'gdelt' ? 'GDELT' : 'search'))}
    ${row('Advanced query', p.query || 'None — structured keywords used')}
    ${payload.source === 'gdelt' ? row('GDELT themes / combination', `${(p.themes || []).join(', ') || 'None'} / ${p.combine || 'and'}`) : ''}
    ${row('Native filters (all configured values)', JSON.stringify(p.native_filters || {}))}
  </dl></details><p class="small muted">Keywords, event terms and coverage countries form AND groups; choices within each group are ORed. Advanced query replaces the keyword list. No country filter guarantees event location; no article cap guarantees complete reporting.</p>`;
}

export function wireStreamTutorial(form, {readProfile, api, previewText, options}) {
  form.noValidate = true; // Validate the current step; reveal hidden invalid fields before reporting.
  const sections = [...form.querySelectorAll('[data-stream-step]')];
  const actions = form.querySelector('[data-stream-actions]');
  const create = actions.querySelector('button.primary');
  create.textContent = 'Save paused stream';
  const previewButton = actions.querySelector('[data-preview]');
  const header = document.createElement('div');
  header.className = 'stream-guide-header';
  header.innerHTML = `<div class="row"><b data-stream-progress></b><span class="spacer"></span><button type="button" data-stream-mode>Use advanced configuration instead</button></div>
    <ol class="stream-step-list">${STREAM_STEPS.map(([name], i) => `<li data-stream-marker="${i}">${i+1}. ${esc(name)}</li>`).join('')}</ol>
    <h2 tabindex="-1" data-stream-question></h2><p class="muted" data-stream-explanation></p>
    <p class="small muted" data-stream-advanced-notice></p><p role="status" data-stream-message></p>`;
  form.prepend(header);
  const review = document.createElement('details');
  review.dataset.profileSection = ''; review.dataset.streamStep = '5';
  review.innerHTML = `<summary>Review and request preview</summary><div data-stream-summary></div><p data-stream-costs></p>
    <p class="small muted">Estimates are not billing or a monthly spending cap; classification costs are separate. Reporting coverage is not guaranteed.</p>
    <details data-stream-request-details><summary>Full technical request preview, terms and warnings</summary></details><p data-stream-preview-status role="status"></p>
    <label class="inline"><input type="checkbox" data-stream-review-confirm> I reviewed this configuration, its warnings and estimated request costs. Save it paused.</label>`;
  actions.before(review); sections.push(review);
  review.querySelector('[data-stream-request-details]').append(form.querySelector('[data-q]'));
  const navigation = document.createElement('div'); navigation.className = 'row stream-guide-navigation';
  navigation.innerHTML = '<button type="button" data-stream-back>Back</button><span class="spacer"></span><button type="button" class="primary" data-stream-next>Continue</button>';
  actions.before(navigation);
  let step = 0, advanced = false, revision = 0, previewSerial = 0, previewRevision = null, pending = false;
  const message = header.querySelector('[data-stream-message]');
  const confirmation = review.querySelector('[data-stream-review-confirm]');
  const status = review.querySelector('[data-stream-preview-status]');
  const q = review.querySelector('[data-q]');
  const payload = () => pausedStream(readProfile(form));
  const fingerprint = () => streamFingerprint(payload());
  const invalidate = event => {
    if (!event.target.name && !event.target.matches('[data-translation-text], [data-translation-keep]')) return;
    revision++; previewRevision = null; confirmation.checked = false;
    status.textContent = 'Settings changed. Refresh the preview before saving.';
    review.querySelector('[data-stream-costs]').textContent = '';
    q.textContent = 'Previous request preview is no longer current.';
    if (advanced || step === 5) review.querySelector('[data-stream-summary]').innerHTML = streamSummaryHtml(payload(), options);
  };
  form.addEventListener('input', invalidate); form.addEventListener('change', invalidate);

  function revealInvalid(control) {
    const section = control.closest('[data-stream-step]');
    if (!advanced && section) step = Number(section.dataset.streamStep);
    // An advanced-only invalid control must be exposed rather than trapping the user.
    if (!section) advanced = true;
    render();
    for (let parent = control.parentElement; parent && parent !== form; parent = parent.parentElement) {
      if (parent.tagName === 'DETAILS') parent.open = true;
    }
    control.scrollIntoView({block:'center'}); control.reportValidity();
  }
  function validate(scope) {
    const invalid = [...scope.querySelectorAll('input, select, textarea')].find(c => !c.disabled
      && !c.closest('[data-newscatcher][hidden], [data-gdelt][hidden], [data-nc-mode][hidden]') && !c.checkValidity());
    if (invalid) { revealInvalid(invalid); return false; }
    return true;
  }
  function render(focus = false) {
    form.classList.toggle('stream-guided', !advanced);
    sections.forEach(section => {
      section.hidden = !advanced && Number(section.dataset.streamStep) !== step;
      if (!advanced) section.open = true;
    });
    header.querySelector('[data-stream-mode]').textContent = advanced ? 'Return to guided steps' : 'Use advanced configuration instead';
    header.querySelector('[data-stream-progress]').textContent = advanced ? 'Advanced configuration — same unsaved draft' : `Step ${step+1} of ${STREAM_STEPS.length}`;
    header.querySelector('[data-stream-question]').textContent = advanced ? 'Full manual configuration' : STREAM_STEPS[step][1];
    header.querySelector('[data-stream-explanation]').textContent = advanced ? 'All settings are available in the sections below. Nothing has been saved; return to the guide without losing values. Preview and review before saving paused.' : STREAM_STEPS[step][2];
    header.querySelector('.stream-step-list').hidden = advanced;
    header.querySelectorAll('[data-stream-marker]').forEach((item, i) => {
      if (i === step) item.setAttribute('aria-current','step'); else item.removeAttribute('aria-current');
    });
    const p = payload();
    header.querySelector('[data-stream-advanced-notice]').textContent = p.params.query || Object.keys(p.params.native_filters || {}).length
      ? 'Advanced query/native filters are retained. Inspect them in advanced mode and in the review; guided choices do not remove them.' : '';
    navigation.hidden = advanced;
    navigation.querySelector('[data-stream-back]').disabled = step === 0;
    navigation.querySelector('[data-stream-next]').hidden = step === 5;
    actions.hidden = !advanced && step !== 5;
    if (advanced || step === 5) {
      review.open = true;
      review.querySelector('[data-stream-summary]').innerHTML = streamSummaryHtml(p, options);
    }
    if (focus) header.querySelector('[data-stream-question]').focus();
  }
  async function preview() {
    const requestRevision = revision, requestSerial = ++previewSerial, snapshot = fingerprint(), body = payload();
    pending = true; previewRevision = null; confirmation.checked = false;
    review.querySelector('[data-stream-costs]').textContent = '';
    q.textContent = 'Compiling the current configuration…';
    status.textContent = 'Compiling the request preview locally. No news or model requests are made.';
    q.hidden = false; q.style.display = 'block';
    try {
      const result = await api('/api/profiles/preview-query', {method:'POST', body});
      if (!form.isConnected || requestSerial !== previewSerial || requestRevision !== revision || snapshot !== fingerprint()) return false;
      q.textContent = previewText(result); previewRevision = snapshot;
      review.querySelector('[data-stream-costs]').textContent = result.requests
        ? `${result.request_count} requests each poll; nominal estimate ${result.estimated_credits_per_poll ?? 'unknown'} credits per poll and ${result.estimated_credits_per_30_days ?? 'unknown'} credits over 30 days of scheduled polling. Retries and manual runs are extra.`
        : 'GDELT request preview ready. Provider limits and downstream classification costs still apply.';
      status.textContent = 'Current preview ready. Read the warnings and acknowledge the review before saving paused.';
      return true;
    } catch (error) {
      if (requestSerial === previewSerial && requestRevision === revision && form.isConnected) { status.textContent = `Preview refused: ${error.message}`; q.textContent = ''; }
      return false;
    } finally { if (requestSerial === previewSerial) pending = false; }
  }
  async function next() {
    message.textContent = '';
    if (!validate(sections.find(s => Number(s.dataset.streamStep) === step))) return;
    const p = payload().params;
    if (step === 2 && !p.keywords.length && !p.event_presets.length && !p.query) {
      message.textContent = 'Choose at least one development, add a keyword in Purpose, or use an advanced query.'; return;
    }
    if (step === 3 && p.multilingual_enabled && !p.translation_review_id) {
      message.textContent = 'Review and approve every translation row, resolve language conflicts, or turn multilingual collection off before continuing.'; return;
    }
    step = Math.min(5, step + 1); render(true);
    if (step === 5) await preview();
  }
  navigation.querySelector('[data-stream-next]').onclick = next;
  navigation.querySelector('[data-stream-back]').onclick = () => { step = Math.max(0, step - 1); message.textContent=''; render(true); };
  header.querySelector('[data-stream-mode]').onclick = () => {
    if (advanced && form.elements.source.value !== 'newscatcher') {
      message.textContent = 'The guided flow supports NewsCatcher. Keep GDELT settings in advanced mode, or deliberately choose NewsCatcher first.'; return;
    }
    advanced = !advanced; message.textContent = ''; render(true);
  };
  previewButton.onclick = async () => { if (validate(form)) await preview(); };
  render();
  return {
    async prepareSave() {
      if (!advanced && step < 5) { await next(); return false; }
      if (!validate(form)) return false;
      if (pending) { status.textContent = 'Wait for the current preview to finish, then review it.'; return false; }
      if (previewRevision !== fingerprint()) { await preview(); status.textContent += ' Check the review acknowledgement, then save again.'; return false; }
      if (!confirmation.checked) { status.textContent = 'Acknowledge that you reviewed this configuration and its costs before saving.'; return false; }
      return true;
    },
    isCurrent: snapshot => form.isConnected && snapshot === fingerprint() && previewRevision === snapshot && confirmation.checked,
    fingerprint,
  };
}
