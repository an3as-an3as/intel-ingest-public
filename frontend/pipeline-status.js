// Pure rendering helper; callers supply their escaping and date-formatting functions.
export function pipelineStatusHtml(s, esc, fmtDate) {
  const workers = s.workers || [];
  const healthy = workers.some(w => w.healthy);
  const counts = s.summaries_by_status || {};
  return `<h2>Worker &amp; summary queue</h2>
    <p><b>${healthy ? 'Worker heartbeat healthy' : workers.length ? 'Worker offline or heartbeat stale' : 'No worker heartbeat yet'}</b></p>
    <p class="small muted">Heartbeat confirms the process is alive, not that work is succeeding. Phase duration and errors below help identify stalled work. Refreshes every 10 seconds.</p>
    ${workers.slice(0, 5).map(w => `<p class="small">${esc(w.phase)}${w.summary_id ? ` · summary #${esc(w.summary_id)}` : ''}
      · since ${esc(fmtDate(w.phase_started_at))} · heartbeat ${esc(fmtDate(w.heartbeat_at))}
      · ${w.healthy ? 'alive' : 'stopped / stale'}
      ${w.last_tick_at ? ` · last completed tick ${esc(fmtDate(w.last_tick_at))}` : ''}
      ${w.last_error ? `<br><b>Last tick error:</b> ${esc(w.last_error)}` : ''}</p>`).join('')}
    <p>Summaries: ${counts.pending || 0} queued / running · ${counts.done || 0} completed · ${counts.failed || 0} failed.</p>
    ${s.oldest_pending_summary_at ? `<p class="small">Oldest queued summary: ${esc(fmtDate(s.oldest_pending_summary_at))}</p>` : ''}
    <p class="small">Classified in last 24h: ${s.classified_24h || 0}.
      ${s.oldest_pending_ingested_at ? `Oldest pending article was ingested ${esc(fmtDate(s.oldest_pending_ingested_at))} (not time queued; reclassification can include older articles).` : 'No pending articles.'}</p>`;
}
