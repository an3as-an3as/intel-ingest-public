// Read-only collection diagnostics. Loading this panel never runs ingestion.
import {catchUpPreviewForm, wireCatchUpPreview} from './catchup.js';
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time = value => value ? new Date(value).toLocaleString() : 'never';

export function collectionDiagnostics(profile) {
  const state = profile.ingestion || {};
  return `<details data-collection-profile="${esc(profile.id)}" data-collection-source="${esc(profile.source)}" data-collection-endpoint="${esc(profile.params?.endpoint || 'search')}" style="margin-top:12px">
    <summary>Collection diagnostics</summary>
    <p class="small muted">Last attempt: ${esc(time(state.last_attempt_at))} · Last successful poll: ${esc(time(state.last_success_at))}
      · Consecutive failures: ${esc(state.failures || 0)}${state.retry_at ? ` · Retry: ${esc(time(state.retry_at))}` : ''}</p>
    <p class="small muted">Successful polls do not guarantee complete provider coverage. Credits are estimates, not billing; classifier statuses are not analyst-validated relevance.</p>
    <button type="button" data-collection-refresh>Load / refresh recent polls</button>
    <div data-collection-runs aria-live="polite"></div>
  </details>`;
}

export function collectionRunsHtml(runs) {
  if (!runs.length) return '<p class="muted small">No recorded polls yet. Loading this panel does not fetch articles.</p>';
  return `<div style="overflow-x:auto"><table><thead><tr><th>Started / result</th><th>Returned / new</th><th>Duplicates URL / title</th><th>Excluded / invalid</th><th>Requests</th><th>Estimated credits</th><th>New article statuses</th></tr></thead><tbody>${runs.map(run => `<tr>
    <td>${esc(time(run.started_at))}<br>${esc(run.status)}${run.error_code ? ` · ${esc(run.error_code)}` : ''}<br>${esc(run.duration_ms)} ms${run.cap_warnings ? `<br><strong>⚠ ${esc(run.cap_warnings)} response(s) at cap — articles may be missing</strong>` : ''}</td>
    <td>${esc(run.returned_articles)} / ${esc(run.new_articles)}</td>
    <td>${esc(run.duplicate_urls)} / ${esc(run.duplicate_titles)}</td>
    <td>${esc(run.excluded_articles)} / ${esc(run.invalid_articles)}</td>
    <td>${esc(run.tracked_requests)} tracked / ${esc(run.planned_requests ?? 'unknown')} planned<details><summary>Request details</summary>${(run.requests || []).map(request => `<p class="small">Part ${esc(request.part)} · ${esc(request.endpoint)} · ${esc(request.status)} · ${esc(request.http_status ?? 'no HTTP status')}<br>Returned ${esc(request.returned)} / limit ${esc(request.limit)} · ${esc(request.duration_ms)} ms<br>Query revision: <code>${esc(request.query_hash)}</code><br>Language lane: ${esc(request.translation_language || 'original')} · approval: ${esc(request.translation_review_id || 'none')}${request.window_overridden ? '<br><strong>Explicit date/window override — scheduling window may not apply</strong>' : ''}${request.history_clamped ? '<br><strong>History limit shortened the requested recovery window</strong>' : ''}<br>Sent time filters: ${esc(JSON.stringify(request.time_parameters || {}))}</p>`).join('') || '<p class="small">Per-request metrics unavailable for this adapter.</p>'}</details></td>
    <td>${esc(run.estimated_credits ?? 'unknown')}<br><span class="small">${run.new_articles_per_estimated_credit == null ? '' : `${esc(Number(run.new_articles_per_estimated_credit).toFixed(2))} new / estimated credit`}</span></td>
    <td>${Object.entries(run.new_article_statuses || {}).map(([status, count]) => `${esc(status)}: ${esc(count)}`).join('<br>') || 'none'}</td>
  </tr>`).join('')}</tbody></table></div>`;
}

export function wireCollectionDiagnostics(root, load) {
  root.querySelectorAll('[data-collection-profile]').forEach(panel => {
    const button = panel.querySelector('[data-collection-refresh]');
    button.onclick = async () => {
      button.disabled = true;
      const target = panel.querySelector('[data-collection-runs]');
      try {
        const runs = await load(`/api/profiles/${encodeURIComponent(panel.dataset.collectionProfile)}/ingest-runs?limit=20`);
        const profile = {source: panel.dataset.collectionSource, endpoint: panel.dataset.collectionEndpoint};
        target.innerHTML = collectionRunsHtml(runs) + catchUpPreviewForm(profile, runs);
        wireCatchUpPreview(target, load, panel.dataset.collectionProfile, runs);
      } catch (error) {
        target.innerHTML = `<p class="small">Could not load diagnostics: ${esc(error.message)}</p>`;
      } finally { button.disabled = false; }
    };
  });
}
