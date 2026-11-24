// Guided answers compile directly into the PIR prompts used by classification.
let draft = null;
const freshDraft = (profileId) => ({name: '', objective: '', geography: '', actors: '', exclusions: '',
  profile_ids: profileId ? [Number(profileId)] : [], reclassify_days: 7,
  questions: [{title: '', question: '', indicators: '', exclusions: '', priority: 2}]});

export async function renderDashboardSetup({api, state, view, esc, toast, renderNav}, profileId) {
  state.profiles = await api('/api/profiles');
  if (!draft) draft = freshDraft(profileId);
  else if (profileId && !draft.profile_ids.includes(Number(profileId))) draft.profile_ids.push(Number(profileId));
  let step = 0;
  const steps = ['Select streams', 'Define the objective', 'Set the scope', 'Ask specific questions', 'Review & launch'];
  const field = (name, label, hint, required = false, max = 4000) => `<label for="setup-${name}">${label}${required ? ' *' : ' (optional)'}</label>
    <textarea id="setup-${name}" name="${name}" maxlength="${max}" ${required ? 'required' : ''} placeholder="${esc(hint)}">${esc(draft[name])}</textarea>`;
  const questionForm = (q, i) => `<section class="card pad setup-question" data-question="${i}">
    <div class="row"><h3>Question ${i + 1}</h3><span class="spacer"></span>${draft.questions.length > 1 ? `<button type="button" data-remove="${i}">Remove question</button>` : ''}</div>
    <label for="q-title-${i}">Short dashboard label *</label><input id="q-title-${i}" name="title" required maxlength="300" value="${esc(q.title)}" placeholder="e.g. Disruption to shipping">
    <label for="q-question-${i}">What specific question should reporting help answer? *</label><textarea id="q-question-${i}" name="question" required maxlength="4000" placeholder="e.g. Which attacks or threats are disrupting commercial shipping in the Red Sea?">${esc(q.question)}</textarea>
    <label for="q-indicators-${i}">What evidence would make an article relevant? (optional)</label><textarea id="q-indicators-${i}" name="indicators" maxlength="4000" placeholder="e.g. Vessel attacks, route diversions, port closures; identify actors, dates and affected vessels.">${esc(q.indicators)}</textarea>
    <label for="q-exclusions-${i}">What should not count for this question? (optional)</label><textarea id="q-exclusions-${i}" name="exclusions" maxlength="4000" placeholder="e.g. General commentary with no new incident or operational change.">${esc(q.exclusions)}</textarea>
    <label for="q-priority-${i}">Priority</label><select id="q-priority-${i}" name="priority">${[[1,'High'],[2,'Normal'],[3,'Low']].map(([n,l]) => `<option value="${n}" ${q.priority === n ? 'selected' : ''}>${l}</option>`).join('')}</select>
    </section>`;
  const capture = () => {
    const f = view.querySelector('#setup-form');
    if (step === 0) draft.profile_ids = Array.from(f.querySelectorAll('[name="profile_ids"]:checked'), el => Number(el.value));
    if (step === 1) { draft.name = f.elements.name.value.trim(); draft.objective = f.elements.objective.value.trim(); }
    if (step === 2) ['geography', 'actors', 'exclusions'].forEach(k => draft[k] = f.elements[k].value.trim());
    if (step === 3) draft.questions = Array.from(f.querySelectorAll('[data-question]'), card => {
      const val = name => card.querySelector(`[name="${name}"]`).value.trim();
      return {title: val('title'), question: val('question'), indicators: val('indicators'), exclusions: val('exclusions'), priority: Number(val('priority'))};
    });
    if (step === 4 && f.elements.reclassify_days) draft.reclassify_days = Number(f.elements.reclassify_days.value);
  };
  const draw = async () => {
    view.innerHTML = `<section class="setup-layout stack"><div class="row"><h1>Guided dashboard setup</h1><span class="spacer"></span><button id="setup-reset">Start over</button></div>
      <ol class="setup-steps" aria-label="Setup progress">${steps.map((label, i) => `<li ${i === step ? 'aria-current="step"' : ''} class="${i === step ? 'on' : ''}">${i+1}. ${label}</li>`).join('')}</ol>
      <form id="setup-form" class="card pad"><h2 tabindex="-1" id="setup-heading">${steps[step]}</h2><div id="setup-content"></div>
      <p id="setup-error" role="alert" class="setup-error"></p><div class="row" style="margin-top:16px"><button type="button" id="setup-back" ${step === 0 ? 'hidden' : ''}>Back</button><a href="#/ingestion">Back to streams</a><span class="spacer"></span><button class="primary" id="setup-next">${step === 4 ? 'Create dashboard & start analysis' : 'Continue'}</button></div></form></section>`;
    const content = view.querySelector('#setup-content');
    if (step === 0) content.innerHTML = `<p>Which configured article streams should this dashboard analyse? Their queries, schedules and enabled/paused state will not be changed.</p>
      ${state.profiles.map(p => `<label class="inline"><input name="profile_ids" type="checkbox" value="${p.id}" ${draft.profile_ids.includes(p.id) ? 'checked' : ''}>${esc(p.name)} — ${p.enabled ? `every ${p.interval_minutes} min` : 'paused'}</label>`).join('') || '<p>No streams yet. <a href="#/ingestion">Configure a stream first</a>.</p>'}`;
    if (step === 1) content.innerHTML = `<p>Start with the decision or situation you need to understand. You do not need to write a technical prompt.</p>
      <label for="setup-name">Dashboard name *</label><input id="setup-name" name="name" required maxlength="200" value="${esc(draft.name)}" placeholder="e.g. Red Sea shipping risk">
      ${field('objective', 'What are you trying to understand, and why?', 'e.g. Help our operations team decide whether shipping routes need to change by tracking threats and disruption.', true)}`;
    if (step === 2) content.innerHTML = `<p>Define the boundaries of relevance. These guide the model; they do not change the news API filters. Leave a field blank for no additional restriction.</p>
      ${field('geography', 'Where should the events be taking place?', 'e.g. Red Sea, Gulf of Aden and Bab el-Mandeb; include external actors only when directly involved.', false, 2000)}
      ${field('actors', 'Which actors, organisations or assets matter?', 'e.g. Commercial vessels, shipping operators, Houthis, coalition naval forces.', false, 2000)}
      ${field('exclusions', 'What should be excluded across the dashboard?', 'e.g. Historical retrospectives, unrelated naval exercises and opinion without new developments.')}`;
    if (step === 3) content.innerHTML = `<p>Break the objective into answerable questions. Each becomes a dashboard card and a classification requirement. Give examples of evidence and exclusions to reduce noisy matches.</p><div class="stack">${draft.questions.map(questionForm).join('')}</div>
      <button type="button" id="setup-add" style="margin-top:12px" ${draft.questions.length >= 20 ? 'disabled' : ''}>Add another question</button>`;
    if (step === 4) {
      content.innerHTML = '<p>Preparing your classification instructions…</p>';
      try {
        const preview = await api('/api/dashboard-setup/preview', {method: 'POST', body: draft});
        if (!content.isConnected || step !== 4) return;
        content.innerHTML = `<h3 style="margin-top:12px">${esc(preview.name)}</h3><p class="setup-text">${esc(preview.description)}</p>
          <p><b>Streams:</b> ${preview.streams.map(p => `${esc(p.name)}${p.enabled ? '' : ' (paused)'}`).join(', ')}</p>
          ${preview.requirements.map(q => `<section class="card pad" style="margin-bottom:8px"><h3>${esc(q.title)} · P${q.priority}</h3><p>${esc(q.question)}</p><p class="small setup-text">${esc(q.indicators)}</p></section>`).join('')}
          <details><summary>View the model's classification instructions</summary><p class="small muted">Preview shows this dashboard's instructions. At runtime the classifier also sees the other active dashboards. Draft requirement codes are replaced by unique codes on save.</p><pre class="setup-prompt">${esc(preview.system_prompt)}</pre></details>
          <label for="setup-lookback">Analyse articles already collected</label><select id="setup-lookback" name="reclassify_days">${[[0,'New / pending articles only'],[1,'Last 24 hours'],[7,'Last 7 days'],[30,'Last 30 days'],[90,'Last 90 days']].map(([n,l]) => `<option value="${n}" ${draft.reclassify_days === n ? 'selected' : ''}>${l}</option>`).join('')}</select>
          <p class="small muted">Recent articles from these streams, including previously irrelevant or failed articles, will be queued for reclassification. Existing pending articles are processed regardless of this lookback. Reclassification refreshes all their PIR scores and may temporarily affect other dashboards. Each classified article costs a model call; new articles follow the existing stream schedules. Paused streams stay paused. Your objective and criteria are sent with article text to the selected classification provider (cloud or configured Ollama server).</p>
          ${(state.meta.classify_configured ?? state.meta.claude_configured) ? '' : '<p class="setup-error">The selected classification provider is not configured. You can save this dashboard, but articles remain pending until its server configuration and worker are ready.</p>'}
          <label class="inline"><input type="checkbox" id="setup-consent" required> I have reviewed the instructions and understand the API usage and processing costs.</label>`;
      } catch (err) {
        if (!content.isConnected) return;
        content.textContent = err.message;
        view.querySelector('#setup-next').disabled = true;
      }
    }
    view.querySelector('#setup-reset').onclick = () => {
      if (!confirm('Discard these setup answers and start over?')) return;
      draft = freshDraft(profileId); step = 0; draw();
    };
    view.querySelector('#setup-back').onclick = () => { capture(); step--; draw(); };
    view.querySelector('#setup-add')?.addEventListener('click', () => { capture(); draft.questions.push(freshDraft().questions[0]); draw(); });
    view.querySelectorAll('[data-remove]').forEach(b => b.onclick = () => { capture(); draft.questions.splice(Number(b.dataset.remove), 1); draw(); });
    view.querySelector('#setup-form').onsubmit = async e => {
      e.preventDefault(); capture();
      const error = view.querySelector('#setup-error');
      if (step === 0 && (!draft.profile_ids.length || draft.profile_ids.some(id => !state.profiles.some(p => p.id === id)))) { error.textContent = 'Select at least one existing stream.'; return; }
      if (step === 1 && (!draft.name || !draft.objective)) { error.textContent = 'Enter a dashboard name and analysis objective.'; return; }
      if (step === 3 && draft.questions.some(q => !q.title || !q.question)) { error.textContent = 'Give each question a label and a specific question.'; return; }
      if (step < 4) { step++; await draw(); return; }
      const button = view.querySelector('#setup-next'); button.disabled = true; error.textContent = '';
      try {
        const result = await api('/api/dashboard-setup', {method: 'POST', body: draft});
        draft = null;
        state.sets = [...state.sets, result.set]; renderNav();
        toast(`Dashboard created · ${result.queued} articles queued for reclassification`, 5000);
        location.hash = `#/dash/${result.set.id}`;
      } catch (err) { error.textContent = err.message; button.disabled = false; }
    };
    view.querySelector('#setup-heading').focus();
  };
  await draw();
}
