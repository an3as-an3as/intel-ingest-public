import test from 'node:test';
import assert from 'node:assert/strict';
import { pipelineStatusHtml } from '../pipeline-status.js';

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const render = data => pipelineStatusHtml(data, esc, s => s);

test('empty installation makes missing worker visible', () => {
  const html = render({});
  assert.match(html, /No worker heartbeat yet/);
  assert.match(html, /0 queued \/ running/);
  assert.match(html, /No pending articles/);
});

test('stale or stopped workers are not labelled healthy', () => {
  const html = render({workers: [{phase:'stopped',healthy:false,heartbeat_at:'old',phase_started_at:'earlier'}]});
  assert.match(html, /offline or heartbeat stale/);
  assert.doesNotMatch(html, /heartbeat healthy/);
});

test('live worker shows phase, progress, queue age and escaped errors', () => {
  const html = render({
    workers: [{phase:'summarising',healthy:true,summary_id:42,phase_started_at:'start',heartbeat_at:'now',
      last_tick_at:'last tick',last_error:'<script>bad()</script>'}],
    summaries_by_status: {pending:2,done:3,failed:1},
    classified_24h:12,oldest_pending_summary_at:'queued at',oldest_pending_ingested_at:'ingested at',
  });
  assert.match(html, /heartbeat healthy/);
  assert.match(html, /summary #42/);
  assert.match(html, /2 queued \/ running · 3 completed · 1 failed/);
  assert.match(html, /Classified in last 24h: 12/);
  assert.match(html, /not time queued/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
});
