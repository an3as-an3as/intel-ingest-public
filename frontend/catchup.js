// Offline preview only. There is deliberately no execute/save/run control.
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const localDate = value => {
  const date = new Date(value);
  return Number.isFinite(date.getTime())
    ? new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 23) : '';
};

export function catchUpPreviewForm(profile, runs) {
  if (profile.source !== 'newscatcher' || profile.endpoint !== 'articles') {
    return '<p class="small muted">Catch-up preview supports saved Articles streams only. Search has no arbitrary historical paging; endpoints and saved filters are never converted automatically.</p>';
  }
  const evidence = runs.filter(r => r.finished_at && (r.cap_warnings || ['partial','error'].includes(r.status)
    || (r.requests || []).some(part => part.history_clamped)));
  if (!evidence.length) return '<p class="small muted">No finished capped, history-clamped, partial or failed poll available for catch-up preview.</p>';
  return `<details data-catchup><summary>Offline catch-up plan preview (no collection)</summary>
    <p class="small muted">Uses saved settings, not unsaved stream edits. No provider calls, subscription lookup, paging or watermark changes. One page per query/language part per date window. Coverage remains uncertain.</p>
    <form data-catchup-form>
      <label>Evidence poll</label><select name="catchup_run">${evidence.map(r => `<option value="${esc(r.id)}">Poll #${esc(r.id)} · ${esc(r.status)} · ${esc(r.started_at)}</option>`).join('')}</select>
      <p class="small muted">Dates use your browser timezone; the preview shows exact timestamps. The complete interval must lie within the selected poll's requested window and declared archive access.</p>
      <div class="grid-2"><div><label>Interval start</label><input type="datetime-local" step="0.001" name="catchup_start" required value="${esc(localDate(evidence[0].window_since))}"></div>
      <div><label>Interval end</label><input type="datetime-local" step="0.001" name="catchup_end" required value="${esc(localDate(evidence[0].window_until))}"></div></div>
      <label>Window length (minutes, 1–1440)</label><input type="number" name="catchup_minutes" min="1" max="1440" required value="60">
      <div class="grid-2"><div><label>Total request ceiling (1–16)</label><input type="number" name="catchup_requests" min="1" max="16" required value="1"></div>
      <div><label>Total nominal credit ceiling</label><input type="number" name="catchup_credits" min="1" max="10000" required value="5"></div></div>
      <p class="small muted">One total budget covers every window, query split and language lane. Saved stream ceilings still apply. An oversized plan is rejected, never truncated.</p>
      <h3>Articles access evidence — operator-declared, not live-verified</h3>
      <p class="small muted">Do not guess plan access. Supply a non-secret reference to recently checked subscription information, not an API key. Unknown access blocks preview; this declaration is not permission to collect.</p>
      <label>Evidence reference</label><input name="catchup_reference" maxlength="200" required>
      <div class="grid-2"><div><label>Access checked at (past 24 hours)</label><input type="datetime-local" step="0.001" name="catchup_observed" required></div>
      <div><label>Earliest accessible archive timestamp</label><input type="datetime-local" step="0.001" name="catchup_history" required></div></div>
      <label>Maximum articles per page permitted (1–100)</label><input type="number" name="catchup_page_size" min="1" max="100" required>
      <label class="inline"><input type="checkbox" name="catchup_confirmed" required> I checked Articles access, archive start and page-size limits; this is an offline declaration only.</label>
      <button type="submit" data-catchup-preview>Preview only — do not fetch</button>
      <pre class="qpreview mono" data-catchup-result role="status" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre>
    </form></details>`;
}

export function readCatchUpForm(form) {
  const e = form.elements;
  const date = name => new Date(e[name].value).toISOString();
  return {
    evidence_run_id: Number(e.catchup_run.value), window_start: date('catchup_start'), window_end: date('catchup_end'),
    window_minutes: Number(e.catchup_minutes.value), max_requests: Number(e.catchup_requests.value), max_credits: Number(e.catchup_credits.value),
    entitlement: {confirmed: e.catchup_confirmed.checked, reference: e.catchup_reference.value.trim(),
      observed_at: date('catchup_observed'), history_start: date('catchup_history'), max_articles_per_page: Number(e.catchup_page_size.value)},
  };
}

export function catchUpPreviewText(plan) {
  return `PREVIEW ONLY — no requests sent; no state changed. Coverage remains uncertain.\n`
    + `${plan.request_count} requests / ${plan.estimated_credits} nominal credits TOTAL (not billing).\n`
    + `Access: ${plan.entitlement.status}.\n\n${plan.warnings.join('\n')}\n\n${JSON.stringify(plan, null, 2)}`;
}

export function wireCatchUpPreview(root, api, profileId, runs) {
  const form = root.querySelector?.('[data-catchup-form]');
  if (!form) return;
  const output = form.querySelector('[data-catchup-result]'), button = form.querySelector('[data-catchup-preview]');
  let revision = 0;
  const invalidate = () => { revision++; output.textContent = 'Inputs changed; request a fresh preview. No saved settings were changed.'; };
  form.addEventListener('input', invalidate);
  form.addEventListener('change', invalidate);
  form.elements.catchup_run.addEventListener('change', () => {
    const run = runs.find(r => String(r.id) === form.elements.catchup_run.value);
    if (!run) return;
    form.elements.catchup_start.value = localDate(run.window_since);
    form.elements.catchup_end.value = localDate(run.window_until);
  });
  form.onsubmit = async event => {
    event.preventDefault();
    if (button.disabled) return;
    button.disabled = true;
    const current = ++revision;
    output.textContent = 'Compiling locally. No provider requests are made…';
    try {
      const body = readCatchUpForm(form);
      const plan = await api(`/api/profiles/${encodeURIComponent(profileId)}/catch-up-preview`, {method:'POST', body});
      if (revision === current && form.isConnected) output.textContent = catchUpPreviewText(plan);
    } catch (error) {
      if (revision === current && form.isConnected) output.textContent = `Preview refused: ${error.message}`;
    } finally { button.disabled = false; }
  };
}
