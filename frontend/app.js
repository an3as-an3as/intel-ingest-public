import { renderDashboardSetup } from './setup.js';
import { collectionDiagnostics, wireCollectionDiagnostics } from './collection.js';
import { eventVocabularyForm, eventBudgetForm, readEventVocabulary, wireEventVocabulary } from './event-vocabulary.js';
import {newStreamParams, contentMatchingForm, wireContentMatching} from './content-matching.js';
import { wireStreamTutorial } from './stream-tutorial.js';
import { keywordTranslationForm, readKeywordTranslation, wireKeywordTranslation } from './keyword-translation.js';
import { createWireframeGlobe, eventDetailsHtml, validLocation } from './wireframe-globe.js';
import { renderModelSettings } from './models.js';
import { applyTheme, storedTheme, renderBrand, summaryBrandHtml, renderAppearanceSettings } from './appearance.js';
import { renderOverview } from './overview.js';
import { pipelineStatusHtml } from './pipeline-status.js';
import { enhanceMultiSelects, nativeFilterForm, readNativeFilters, queryPreviewText } from './filters.js';

// Intel Ingest – single-page UI (no build step). Hash routes:
//   #/stream   #/dash/<setId>   #/settings[/<tab>]

const $ = (sel, root = document) => root.querySelector(sel);
const view = $("#view");
const state = { meta: null, sets: [], profiles: [], timers: [] };
let overviewCleanup = () => {};

// ---------- helpers ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");

async function api(path, opts = {}) {
  const r = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    body: opts.body && typeof opts.body !== "string" ? JSON.stringify(opts.body) : opts.body,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try { const detail = (await r.json()).detail; msg = Array.isArray(detail) ? detail.map(d => d.msg).join('; ') : detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

function toast(msg, ms = 3000) {
  const t = $("#toast");
  t.textContent = msg; t.style.display = "block";
  clearTimeout(t._h); t._h = setTimeout(() => (t.style.display = "none"), ms);
}

function ago(iso) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}
const fmtDate = (iso, withTime = true) =>
  new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}) });

function every(ms, fn) { const h = setInterval(fn, ms); state.timers.push(h); }
function clearTimers() { state.timers.forEach(clearInterval); state.timers = []; }
const evLabel = (k) => state.meta?.event_types?.[k] || k || "Unclassified";
const regLabel = (k) => state.meta?.regions?.[k] || k || "Unknown";

// ---------- theme ----------
(function initTheme() {
  const saved = storedTheme();
  if (saved !== 'system') document.documentElement.dataset.theme = saved;
  $("#theme-toggle").onclick = () => {
    const cur = document.documentElement.dataset.theme ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    applyTheme(cur === "dark" ? "light" : "dark");
    if (location.hash === '#/settings/appearance') route();
  };
})();

// ---------- collapsible dashboard pane ----------
(function initSidebar() {
  const button = $('#sidebar-toggle'), sidebar = $('#dashboard-sidebar'), layout = $('.app-layout');
  if (!button || !sidebar || !layout) return;
  let collapsed = false;
  try { collapsed = localStorage.getItem('sidebar-collapsed') === 'true'; } catch {}
  const apply = () => {
    layout.classList.toggle('sidebar-collapsed', collapsed); sidebar.hidden = collapsed;
    button.setAttribute('aria-expanded', String(!collapsed));
    button.setAttribute('aria-label', collapsed ? 'Show dashboards sidebar' : 'Hide dashboards sidebar');
    button.title = collapsed ? 'Show dashboards' : 'Hide dashboards';
    button.textContent = collapsed ? '☰' : '◧';
    requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
  };
  button.onclick = () => { collapsed = !collapsed; try { localStorage.setItem('sidebar-collapsed', String(collapsed)); } catch {} apply(); };
  apply();
})();

// ---------- nav & status ----------
function renderNav() {
  const route = location.hash || '#/home';
  const links = [["#/home", "Main dashboard"], ["#/ingestion", "Pre-ingestion"], ["#/setup", "Set up dashboard"], ["#/stream", "Articles"], ["#/settings", "Settings"]];
  $("#nav").innerHTML = links
    .map(([h, l]) => `<a href="${h}" class="${route === h || (["#/settings", "#/setup"].includes(h) && route.startsWith(h)) ? "active" : ""}">${esc(l)}</a>`)
    .join("");
  const dashboards = $('#dashboard-nav');
  if (dashboards) dashboards.innerHTML = state.sets.map(s => {
    const active = route === `#/dash/${s.id}`;
    return `<a href="#/dash/${s.id}" class="${active ? 'active' : ''}" ${active ? 'aria-current="page"' : ''}>${esc(s.name)}</a>`;
  }).join('') || '<p class="small muted">No dashboards yet. Use Set up dashboard to create one.</p>';
}

async function refreshPill() {
  try {
    const s = await api("/api/status");
    const c = s.articles_by_status || {};
    const pending = c.pending || 0;
    const pill = $("#pipeline-pill");
    const ready=state.meta?.classify_configured ?? state.meta?.claude_configured;
    pill.textContent = ready
      ? `${s.ingested_24h} ingested 24h · ${pending} pending`
      : `Classification provider not configured · ${pending} pending`;
    pill.style.color = ready ? "" : "var(--status-critical)";
  } catch {}
}

// ---------- article card ----------
function articleCard(a, { compact = false } = {}) {
  const loc = a.location_name ? `📍 ${esc(a.location_name)}` : "";
  const status = a.status !== "enriched"
    ? `<span class="chip status-${a.status}" title="${esc(a.error || "")}">${esc(a.status)}</span>` : "";
  const pirs = a.pirs.map((m) =>
    `<span class="chip pir" title="${esc(m.rationale)}"><b>${esc(m.code)}</b> ${m.score.toFixed(2)}</span>`).join("");
  return `<article class="card article">
    <h3><a href="${esc(safeUrl(a.url))}" target="_blank" rel="noopener noreferrer">${esc(a.title)}</a></h3>
    <div class="meta">
      <span title="${esc(a.published_at)}">${ago(a.published_at)}</span>
      <span>${esc(a.source_domain || "")}</span>
      ${loc ? `<span>${loc}</span>` : ""}
      ${a.event_type ? `<span>${esc(evLabel(a.event_type))}</span>` : ""}
    </div>
    ${a.summary && !compact ? `<p class="summary">${esc(a.summary)}</p>` : ""}
    ${a.summary && compact ? `<p class="summary small">${esc(a.summary)}</p>` : ""}
    <div class="chips">${status}${pirs}</div>
  </article>`;
}

// ================= STREAM =================
const streamFilters = { window: "7d", q: "", event_type: "", region: "", country: "", profile_id: "", set_id: "", pir_id: "", include_irrelevant: false };

async function renderStream() {
  view.innerHTML = `<div class="stream-layout">
    <aside class="card pad filters" id="filters"></aside>
    <section>
      <div class="row" style="margin-bottom:10px"><h1>Stream</h1><span class="muted" id="stream-count"></span>
        <span class="spacer"></span><button id="refresh">Refresh</button></div>
      <div class="articles" id="articles"></div>
      <div style="text-align:center;margin:14px"><button id="more" style="display:none">Load more</button></div>
    </section></div>`;
  let offset = 0;
  const load = async (append = false) => {
    if (!append) offset = 0;
    const p = new URLSearchParams();
    Object.entries(streamFilters).forEach(([k, v]) => v !== "" && v !== false && p.set(k, v));
    p.set("limit", 50); p.set("offset", offset);
    const r = await api(`/api/articles?${p}`);
    $("#stream-count").textContent = `${r.total} articles`;
    const html = r.items.map((a) => articleCard(a)).join("");
    $("#articles").innerHTML = append ? $("#articles").innerHTML + html
      : html || `<div class="empty">No articles match. New articles arrive as the worker runs (every ~1 min); check Settings → Pipeline.</div>`;
    offset += r.items.length;
    $("#more").style.display = offset < r.total ? "" : "none";
    renderFilters(r.facets);
  };
  const renderFilters = (facets) => {
    const facetList = (key, labels) => {
      const entries = Object.entries(facets[key] || {}).sort((a, b) => b[1] - a[1]);
      if (streamFilters[key] && !facets[key]?.[streamFilters[key]]) entries.unshift([streamFilters[key], 0]);
      return entries.map(([k, n]) =>
        `<button data-facet="${key}" data-val="${esc(k)}" class="${streamFilters[key] === k ? "on" : ""}">
          <span>${esc(labels(k))}</span><span class="n">${n}</span></button>`).join("") || `<span class="faint small">–</span>`;
    };
    const pirOpts = state.sets.flatMap((s) => s.pirs.map((p) =>
      `<option value="${p.id}" ${String(streamFilters.pir_id) === String(p.id) ? "selected" : ""}>${esc(p.code)} – ${esc(p.title)}</option>`)).join("");
    $("#filters").innerHTML = `
      <input id="f-q" placeholder="Search headline, summary, place" value="${esc(streamFilters.q)}">
      <label>Time window</label>
      <div class="seg" id="f-window">${["24h", "7d", "30d", "90d"].map((w) =>
        `<button data-w="${w}" class="${streamFilters.window === w ? "on" : ""}">${w}</button>`).join("")}</div>
      <label>Ingest profile</label>
      <select id="f-profile"><option value="">All profiles</option>${state.profiles.map((p) =>
        `<option value="${p.id}" ${String(streamFilters.profile_id) === String(p.id) ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select>
      <label>PIR set</label>
      <select id="f-set"><option value="">Any</option>${state.sets.map((s) =>
        `<option value="${s.id}" ${String(streamFilters.set_id) === String(s.id) ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select>
      <label>PIR</label>
      <select id="f-pir"><option value="">Any</option>${pirOpts}</select>
      <label>Country (ISO code, e.g. FI)</label>
      <input id="f-country" maxlength="2" value="${esc(streamFilters.country)}">
      <label class="inline"><input type="checkbox" id="f-irr" ${streamFilters.include_irrelevant ? "checked" : ""}> Include items marked not relevant</label>
      <label>Event type</label><div class="facet-list">${facetList("event_type", evLabel)}</div>
      <label>Region</label><div class="facet-list">${facetList("region", regLabel)}</div>
      <div style="margin-top:12px"><button id="f-clear">Clear filters</button></div>`;
    const f = $("#filters");
    f.querySelectorAll("[data-facet]").forEach((b) => (b.onclick = () => {
      const k = b.dataset.facet; streamFilters[k] = streamFilters[k] === b.dataset.val ? "" : b.dataset.val; load();
    }));
    f.querySelectorAll("#f-window button").forEach((b) => (b.onclick = () => { streamFilters.window = b.dataset.w; load(); }));
    let deb; $("#f-q").oninput = (e) => { clearTimeout(deb); deb = setTimeout(() => { streamFilters.q = e.target.value; load(); }, 350); };
    $("#f-profile").onchange = (e) => { streamFilters.profile_id = e.target.value; load(); };
    $("#f-set").onchange = (e) => { streamFilters.set_id = e.target.value; load(); };
    $("#f-pir").onchange = (e) => { streamFilters.pir_id = e.target.value; load(); };
    $("#f-country").onchange = (e) => { streamFilters.country = e.target.value.trim().toUpperCase(); load(); };
    $("#f-irr").onchange = (e) => { streamFilters.include_irrelevant = e.target.checked; load(); };
    $("#f-clear").onclick = () => { Object.assign(streamFilters, { q: "", event_type: "", region: "", country: "", profile_id: "", set_id: "", pir_id: "", include_irrelevant: false }); load(); };
  };
  $("#refresh").onclick = () => load();
  $("#more").onclick = () => load(true);
  await load();
  every(60000, () => { if (window.scrollY < 200 && !document.activeElement?.matches("input,select")) load(); });
}

// ================= SPARKLINE (single series, hover tooltip) =================
function sparkline(el, series) {
  const counts = series.counts, n = counts.length;
  const W = 300, H = 56, padT = 6, padB = 4;
  const max = Math.max(1, ...counts);
  const x = (i) => (n === 1 ? W / 2 : (i / (n - 1)) * W);
  const y = (v) => padT + (1 - v / max) * (H - padT - padB);
  const pts = counts.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `M0,${H - padB} L${pts.split(" ").join(" L")} L${W},${H - padB} Z`;
  const fmt = (iso) => series.bucket === "hour"
    ? new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
    : new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img"
      aria-label="Articles per ${series.bucket}, peak ${max}">
      <line x1="0" x2="${W}" y1="${H - padB}" y2="${H - padB}" stroke="var(--grid)" stroke-width="1" vector-effect="non-scaling-stroke"/>
      <path d="${area}" fill="var(--series-1-fill)"/>
      <polyline points="${pts}" fill="none" stroke="var(--series-1)" stroke-width="2" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>
      <line class="xh" y1="0" y2="${H}" stroke="var(--text-3)" stroke-width="1" vector-effect="non-scaling-stroke" style="display:none"/>
    </svg><div class="tip"></div>
    <div class="row small faint" style="justify-content:space-between;margin-top:2px">
      <span>${fmt(series.start[0])}</span><span>peak ${max}/${series.bucket}</span><span>now</span></div>`;
  const svg = el.querySelector("svg"), tip = el.querySelector(".tip"), xh = el.querySelector(".xh");
  svg.addEventListener("mousemove", (e) => {
    const r = svg.getBoundingClientRect();
    const i = Math.max(0, Math.min(n - 1, Math.round(((e.clientX - r.left) / r.width) * (n - 1))));
    xh.setAttribute("x1", x(i)); xh.setAttribute("x2", x(i)); xh.style.display = "";
    tip.style.display = "block";
    tip.style.left = `${(x(i) / W) * r.width}px`;
    tip.textContent = `${fmt(series.start[i])}: ${counts[i]} article${counts[i] === 1 ? "" : "s"}`;
  });
  svg.addEventListener("mouseleave", () => { tip.style.display = "none"; xh.style.display = "none"; });
}

const TREND = {
  rising: ["▲", "Rising"], falling: ["▼", "Falling"], steady: ["▬", "Stable"], insufficient: ["·", "Low volume"],
};
function trendBadge(s) {
  const [icon, label] = TREND[s.direction];
  const pct = s.change_pct != null ? ` ${s.change_pct > 0 ? "+" : ""}${Math.round(s.change_pct)}%` : (s.direction === "rising" ? " new" : "");
  return `<span class="trend ${s.direction}" title="vs previous equal period: ${s.previous_count}">${icon} ${label}${s.direction === "insufficient" ? "" : pct}</span>`;
}

// ================= DASHBOARD =================
const dashState = { window: "7d", focusPir: null, map: null, summaryId: null };

async function renderDashboard(setId) {
  const set = state.sets.find((s) => String(s.id) === String(setId));
  if (!set) { view.innerHTML = `<div class="empty">Dashboard not found.</div>`; return; }
  dashState.focusPir = null;
  view.innerHTML = `
    <div class="dash-head">
      <div><h1>${esc(set.name)}</h1><div class="muted">${esc(set.description)}</div><div class="small muted" id="dashboard-streams"></div></div>
      <span class="spacer"></span>
      <div class="seg" id="d-window">${["24h", "7d", "30d", "90d"].map((w) =>
        `<button data-w="${w}" class="${dashState.window === w ? "on" : ""}">${w}</button>`).join("")}</div>
    </div>
    <div class="card pad small" id="dashboard-processing" role="status" style="margin-bottom:14px">Checking article processing…</div>
    <div class="pir-grid" id="pir-grid"></div>
    <div class="dash-body">
      <div class="card globe-card"><div class="row pad globe-toolbar"><h2>Event globe</h2><span class="muted small" id="map-note"></span><span class="spacer"></span>
          <button data-dashboard-globe-action="left" aria-label="Rotate globe left">←</button><button data-dashboard-globe-action="right" aria-label="Rotate globe right">→</button>
          <button data-dashboard-globe-action="in" aria-label="Zoom in on globe">+</button><button data-dashboard-globe-action="out" aria-label="Zoom out on globe">−</button><button data-dashboard-globe-action="reset">Reset view</button></div>
        <div id="map" class="wireframe-globe" role="img" aria-label="Wireframe event globe with coloured event dots. Drag to rotate, scroll to zoom, or use the buttons above."></div>
        <div class="pad small muted">Numbers show how many articles are grouped at a place; dots grow to a fixed size, then only the number increases. Zoom in to separate nearby reports. Locations are model-estimated and approximate. <span id="nogeo"></span></div>
        <div id="dashboard-globe-selection" class="pad small globe-selection" aria-live="polite">Click a dot to inspect its reports.</div></div>
      <div class="card"><div class="row pad" style="padding-bottom:0"><h2>Reporting</h2><span class="muted small" id="list-note"></span></div>
        <div class="dash-list" id="dash-list"></div></div>
    </div>
    <div class="card pad" id="summaries-panel"></div>`;

  const host = $('#map'), selection = $('#dashboard-globe-selection');
  dashState.map?.dispose();
  const map = createWireframeGlobe(host, {esc,
    onSelect: point => { selection.innerHTML = eventDetailsHtml(point, esc, safeUrl); },
    onChange: ({points, reportCount}) => { if(host.isConnected) $('#map-note').textContent = `${reportCount} geolocated · ${points.length} area${points.length === 1 ? '' : 's'}`; },
  });
  dashState.map = map;
  view.querySelectorAll('[data-dashboard-globe-action]').forEach(button => button.onclick = () => map.action(button.dataset.dashboardGlobeAction));

  let data, refocus = true, requestId = 0;
  const draw = () => {
    if (!host.isConnected || !data) return;
    const focus = dashState.focusPir;
    const arts = focus ? data.articles.filter((a) => a.pirs.some((m) => m.pir_id === focus)) : data.articles;
    const focusP = set.pirs.find((p) => p.id === focus);
    $("#list-note").textContent = `${arts.length} articles${focusP ? ` · ${focusP.code}` : ""}`;
    $("#dash-list").innerHTML = arts.map((a) => articleCard(a, { compact: true })).join("")
      || `<div class="empty">No matched reporting in this window.</div>`;

    map.setDashboards([{id: set.id, name: set.name, points: arts}], new Set(), {focus: refocus});
    refocus = false;
    selection.textContent = 'Click a dot to inspect its reports.';
    const geo = arts.filter(validLocation).length;
    $('#nogeo').textContent = arts.length - geo ? `${arts.length - geo} without coordinates (reporting list only).` : '';

    document.querySelectorAll('.pir-card').forEach(c => {
      const selected = Number(c.dataset.pir) === focus;
      c.classList.toggle('on', selected); c.setAttribute('aria-pressed', String(selected));
    });
  };

  const load = async () => {
    const version = ++requestId;
    const result = await api(`/api/dashboards/${set.id}?window=${dashState.window}`);
    if (!host.isConnected || version !== requestId) return;
    data = result;
    $('#dashboard-streams').textContent = data.streams.length ? `Linked streams: ${data.streams.map(p => p.name).join(', ')}` : 'All streams (no explicit links)';
    const grid = $("#pir-grid");
    grid.innerHTML = data.stats.map((s) => `
      <div class="card pir-card" data-pir="${s.pir_id}" tabindex="0" role="button" aria-pressed="false">
        <div class="row"><span class="code">${esc(s.code)}</span><span class="prio">P${s.priority}</span><span class="spacer"></span>${trendBadge(s)}</div>
        <div class="title">${esc(s.title)}</div>
        <div class="row" style="align-items:baseline"><span class="num">${s.count}</span>
          <span class="prev">articles in ${dashState.window} · previous ${s.previous_count}</span></div>
        <div class="spark"></div>
      </div>`).join("") || `<div class="empty">This set has no active PIRs. Add some in Settings.</div>`;
    grid.querySelectorAll(".pir-card").forEach((card, i) => {
      sparkline(card.querySelector(".spark"), data.stats[i].series);
      const toggle = () => { const id = Number(card.dataset.pir); dashState.focusPir = dashState.focusPir === id ? null : id; refocus = true; draw(); };
      card.onclick = toggle;
      card.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } };
    });
    draw();
  };

  view.querySelectorAll("#d-window button").forEach((b) => (b.onclick = () => {
    dashState.window = b.dataset.w; refocus = true;
    view.querySelectorAll("#d-window button").forEach((x) => x.classList.toggle("on", x === b));
    load();
  }));
  const processing = async () => {
    if (!host.isConnected) return;
    const status = await api(`/api/dashboards/${set.id}/processing`);
    if (!host.isConnected) return;
    const panel = $('#dashboard-processing'); if (!panel) return;
    const c = status.counts;
    panel.textContent = `${(status.classify_configured ?? status.claude_configured) ? '' : 'Classification provider not configured — classification is waiting. '}${c.pending || 0} pending · ${c.enriched || 0} classified · ${c.irrelevant || 0} marked irrelevant · ${c.failed || 0} failed · ${status.matched} matched to this dashboard. ${c.pending ? 'The worker will process queued articles; results refresh automatically.' : 'New articles follow the configured stream schedules.'}`;
  };
  await load();
  if (!host.isConnected) return;
  await processing();
  if (!host.isConnected) return;
  renderSummaries(set);
  every(10000, () => processing().catch(() => {}));
  every(30000, load);
}

// ---------- summaries ----------
function renderReport(summary) {
  const refs = summary.references || {};
  let html = DOMPurify.sanitize(marked.parse(summary.content || ""));
  html = html.replace(/\[(A\d+)\]/g, (m, id) => {
    const r = refs[id];
    return r ? `<a class="cite" href="${esc(safeUrl(r.url))}" target="_blank" rel="noopener noreferrer" title="${esc(r.title)} — ${esc(r.source || "")}, ${fmtDate(r.date, false)}">[${id}]</a>` : m;
  });
  return html;
}

async function renderSummaries(set) {
  const panel = $("#summaries-panel");
  panel.innerHTML = `
    <div class="row" style="margin-bottom:12px"><h2>Intelligence summaries</h2><span class="spacer"></span>
      <span class="muted small">Generate for:</span>
      <button data-p="7d">Last week</button><button data-p="30d">Last month</button><button data-p="90d">Last quarter</button></div>
    <div class="summaries"><div class="summary-list" id="sum-list"></div><div class="report" id="sum-view"></div></div>`;
  const list = async () => {
    const rows = await api(`/api/pir-sets/${set.id}/summaries`);
    $("#sum-list").innerHTML = rows.map((r) => `
      <button data-id="${r.id}" class="${dashState.summaryId === r.id ? "on" : ""}">
        <div><b>${esc(r.period_label)}</b></div>
        <div class="small muted">${fmtDate(r.created_at)} · ${r.status === "done" ? `${r.article_count} reports` : esc(r.status)}</div>
      </button>`).join("") || `<div class="muted small">No summaries yet.</div>`;
    $("#sum-list").querySelectorAll("button").forEach((b) => (b.onclick = () => show(Number(b.dataset.id))));
    return rows;
  };
  const show = async (id) => {
    dashState.summaryId = id;
    $("#sum-list").querySelectorAll("button").forEach((b) => b.classList.toggle("on", Number(b.dataset.id) === id));
    const s = await api(`/api/summaries/${id}`);
    const head = summaryBrandHtml(state.meta?.branding, set.name, esc) + `<div class="row small muted"><span>${fmtDate(s.period_start, false)} – ${fmtDate(s.period_end, false)}</span>
      <span>${s.article_count} reports reviewed</span><span>${esc(s.model || "")}</span><span class="spacer"></span>
      <button data-del class="danger">Delete</button></div>${s.status === 'done' ? `<div class="row summary-exports small"><b>Export:</b>${[['html','HTML'],['md','Markdown'],['txt','Plain text'],['json','JSON']].map(([format,label]) => `<a class="btn" href="/api/summaries/${s.id}/export?format=${format}" download>${label}</a>`).join('')}<span class="faint">HTML is self-contained and can be printed to PDF.</span></div>` : ''}`;
    if (s.status === "pending") $("#sum-view").innerHTML = head + `<p class="muted">Writing summary… queued for the worker; generation can take a minute or two. Check Settings → Pipeline if it stays pending.</p>`;
    else if (s.status === "failed") $("#sum-view").innerHTML = head + `<p style="color:var(--status-critical)">Failed: ${esc(s.error)}</p><button data-retry-summary>Retry summary (uses API credits)</button>`;
    else $("#sum-view").innerHTML = head + `<p class="small faint">Machine-generated from open-source reporting. Source reliability is unverified; check cited reports before relying on a judgment.</p>` + renderReport(s);
    const retryButton = $('#sum-view [data-retry-summary]');
    if (retryButton) retryButton.onclick = async () => {
      if (!confirm('Retry this summary? This makes another paid model call.')) return;
      try {
        await api(`/api/summaries/${id}/retry`, {method: 'POST'});
        await list(); await show(id);
      } catch (err) { toast(err.message, 5000); }
    };
    $("#sum-view [data-del]").onclick = async () => {
      if (!confirm("Delete this summary?")) return;
      try {
        await api(`/api/summaries/${id}`, { method: "DELETE" });
        dashState.summaryId = null; $("#sum-view").innerHTML = ""; list();
      } catch (err) { toast(err.message, 5000); }
    };
  };
  panel.querySelectorAll("[data-p]").forEach((b) => (b.onclick = async () => {
    try {
      const s = await api(`/api/pir-sets/${set.id}/summaries`, { method: "POST", body: { period: b.dataset.p } });
      toast("Summary requested"); await list(); show(s.id);
    } catch (e) { toast(e.message, 5000); }
  }));
  const rows = await list();
  if (rows.length) show(dashState.summaryId && rows.some((r) => r.id === dashState.summaryId) ? dashState.summaryId : rows[0].id);
  every(5000, async () => {
    const rows = await list();
    const cur = rows.find((r) => r.id === dashState.summaryId);
    if (cur && $("#sum-view")?.textContent.includes("Writing summary") && cur.status !== "pending") show(cur.id);
  });
}

// ================= SETTINGS =================
async function renderSettings(tab = "pirs") {
  view.innerHTML = `<div class="row" style="margin-bottom:12px"><h1>Settings</h1><span class="spacer"></span><a class="btn" href="#/setup">Create dashboard with guided setup</a></div>
    <div class="tabs seg">${[["pirs", "Intelligence requirements"], ["profiles", "Ingest profiles"], ["models", "Models"], ["appearance", "Appearance"], ["pipeline", "Pipeline"]]
      .map(([k, l]) => `<button class="${k === tab ? "on" : ""}" onclick="location.hash='#/settings/${k}'">${l}</button>`).join("")}</div>
    <div id="settings-body"></div>`;
  const body = $("#settings-body");
  if (tab === "pirs") return settingsPirs(body);
  if (tab === "profiles") return settingsProfiles(body);
  if (tab === "models") return renderModelSettings({api, state, esc, toast}, body);
  if (tab === "appearance") return renderAppearanceSettings({api, state, esc, toast}, body);
  await settingsPipeline(body);
  every(10000, async () => {
    const panel = $('#pipeline-health', body);
    if (!panel?.isConnected) return;
    try {
      const s = await api('/api/status');
      if (panel.isConnected) panel.innerHTML = pipelineStatusHtml(s, esc, fmtDate);
    } catch (err) {
      if (panel.isConnected) panel.textContent = `Unable to refresh worker health: ${err.message}`;
    }
  });
}

const lines = (s) => s.split(/[,\n]/).map((x) => x.trim()).filter(Boolean);

function pirForm(p = {}) {
  return `<div class="grid-3">
      <div><label>Code (unique)</label><input name="code" value="${esc(p.code || "")}" placeholder="e.g. BAL-4"></div>
      <div><label>Priority</label><select name="priority">${[1, 2, 3].map((n) => `<option ${p.priority === n ? "selected" : ""} value="${n}">P${n}${n === 1 ? " (highest)" : ""}</option>`).join("")}</select></div>
      <div><label class="inline" style="margin-top:28px"><input type="checkbox" name="active" ${p.active !== false ? "checked" : ""}> Active</label></div>
    </div>
    <label>Title</label><input name="title" value="${esc(p.title || "")}">
    <label>Requirement (the question to answer)</label><textarea name="question">${esc(p.question || "")}</textarea>
    <label>Indicators (what counts as relevant reporting; helps the classifier)</label><textarea name="indicators">${esc(p.indicators || "")}</textarea>`;
}
const readPirForm = (f) => ({
  code: f.code.value.trim(), title: f.title.value.trim(), question: f.question.value.trim(),
  indicators: f.indicators.value.trim(), priority: Number(f.priority.value), active: f.active.checked,
});

async function settingsPirs(body) {
  state.sets = await api("/api/pir-sets"); renderNav();
  body.innerHTML = `<div class="stack">
    <div class="card pad muted small">Each <b>PIR set</b> gets its own dashboard. The classifier reads the requirement and indicators
      text directly (zero-shot), so wording matters: be specific about actors, places and the kinds of events that count.
      Changes apply to new articles; use <a href="#/settings/pipeline">Pipeline → Reclassify</a> to re-score recent ones.</div>
    ${state.sets.map((s) => `
      <div class="card pad" data-set="${s.id}">
        <form class="set-form grid-2"><div><label>Set name</label><input name="name" value="${esc(s.name)}"></div>
          <div><label>Description</label><input name="description" value="${esc(s.description)}"></div></form>
        <div class="row" style="margin-top:8px"><button data-save-set>Save set</button><button class="danger" data-del-set>Delete set</button></div>
        <table style="margin-top:12px"><thead><tr><th style="width:90px">Code</th><th>Requirement</th><th style="width:50px">Prio</th><th style="width:140px"></th></tr></thead>
          <tbody>${s.pirs.map((p) => `<tr data-pir="${p.id}"><td><b>${esc(p.code)}</b>${p.active ? "" : ' <span class="faint small">(off)</span>'}</td>
            <td><div><b>${esc(p.title)}</b></div><div class="muted small">${esc(p.question)}</div></td><td>P${p.priority}</td>
            <td><button data-edit>Edit</button> <button class="danger" data-del>Delete</button></td></tr>`).join("")}</tbody></table>
        <details style="margin-top:10px"><summary>Add PIR</summary><form class="add-pir">${pirForm()}<div style="margin-top:10px"><button class="primary">Add PIR</button></div></form></details>
      </div>`).join("")}
    <div class="card pad"><h2>New PIR set</h2><form id="new-set" class="grid-2">
      <div><label>Name</label><input name="name" required></div><div><label>Description</label><input name="description"></div></form>
      <div style="margin-top:10px"><button class="primary" id="create-set">Create set</button></div></div>
  </div>`;

  body.querySelectorAll("[data-set]").forEach((card) => {
    const sid = card.dataset.set, set = state.sets.find((s) => String(s.id) === sid);
    card.querySelector("[data-save-set]").onclick = async () => {
      const f = card.querySelector(".set-form");
      await api(`/api/pir-sets/${sid}`, { method: "PUT", body: { name: f.elements.name.value, description: f.elements.description.value } });
      toast("Saved"); settingsPirs(body);
    };
    card.querySelector("[data-del-set]").onclick = async () => {
      if (!confirm(`Delete "${set.name}" and all its PIRs?`)) return;
      await api(`/api/pir-sets/${sid}`, { method: "DELETE" }); settingsPirs(body);
    };
    card.querySelector(".add-pir").onsubmit = async (e) => {
      e.preventDefault();
      try { await api(`/api/pir-sets/${sid}/pirs`, { method: "POST", body: readPirForm(e.target) }); toast("PIR added"); settingsPirs(body); }
      catch (err) { toast(err.message, 5000); }
    };
    card.querySelectorAll("tr[data-pir]").forEach((tr) => {
      const p = set.pirs.find((x) => String(x.id) === tr.dataset.pir);
      tr.querySelector("[data-del]").onclick = async () => {
        if (!confirm(`Delete ${p.code}? Its article matches are removed too.`)) return;
        await api(`/api/pirs/${p.id}`, { method: "DELETE" }); settingsPirs(body);
      };
      tr.querySelector("[data-edit]").onclick = () => {
        tr.innerHTML = `<td colspan="4"><form>${pirForm(p)}<div class="row" style="margin-top:10px"><button class="primary">Save</button><button type="button" data-cancel>Cancel</button></div></form></td>`;
        tr.querySelector("[data-cancel]").onclick = () => settingsPirs(body);
        tr.querySelector("form").onsubmit = async (e) => {
          e.preventDefault();
          try { await api(`/api/pirs/${p.id}`, { method: "PUT", body: readPirForm(e.target) }); toast("Saved"); settingsPirs(body); }
          catch (err) { toast(err.message, 5000); }
        };
      };
    });
  });
  $("#create-set").onclick = async () => {
    const f = $("#new-set");
    if (!f.elements.name.value.trim()) return toast("Name required");
    await api("/api/pir-sets", { method: "POST", body: { name: f.elements.name.value.trim(), description: f.elements.description.value.trim() } });
    settingsPirs(body);
  };
}

function profileForm(p = { source: "newscatcher", params: {}, enabled: false, interval_minutes: 30 }) {
  const pr = p.id ? (p.params || {}) : newStreamParams(p.params || {});
  const j = (k) => esc((pr[k] || []).join(", "));
  const opts = state.meta.ingestion_options;
  const multi = (name, options, selected = []) => `<select name="${name}" multiple size="6">${Object.entries({...options, ...Object.fromEntries(selected.filter(k => !options[k]).map(k => [k, k]))}).map(([k, label]) => `<option value="${esc(k)}" ${selected.map(String).includes(String(k)) ? "selected" : ""}>${esc(label)}</option>`).join("")}</select>`;
  const nc = p.source === "newscatcher";
  return `<details data-profile-section data-stream-step="0" open><summary>Topic and exclusions</summary><div class="grid-2">
      <div><label>Name</label><input name="name" required value="${esc(p.name || "")}"></div>
      <div data-stream-manual-only><label>Source</label><select name="source">
        <option value="gdelt" ${p.source === "gdelt" ? "selected" : ""}>GDELT (free)</option>
        <option value="newscatcher" ${p.source === "newscatcher" ? "selected" : ""}>NewsCatcher${state.meta.newscatcher_configured ? "" : " (no API key set)"}</option></select></div>
    </div>
    <label>Keywords / literal phrases (comma-separated, no quotation marks; any matches)</label><input name="keywords" value="${j("keywords")}">
    <div class="grid-2" data-gdelt ${nc ? 'hidden' : ''}>
      <div><label>Themes (GDELT only: GKG themes like ARMEDCONFLICT, TERROR, PROTEST, CYBER_ATTACK, MARITIME_INCIDENT)</label><input name="themes" value="${j("themes")}"></div>
      <div><label>Keywords + themes</label><select name="combine">
        <option value="and" ${pr.combine !== "or" ? "selected" : ""}>Must match both a keyword and a theme</option>
        <option value="or" ${pr.combine === "or" ? "selected" : ""}>Either is enough</option></select></div>
    </div>
    <label>Exclude keywords (optional)</label><input name="exclude_keywords" value="${j("exclude_keywords")}">
    <p class="small muted">An exclusion removes matching reports before classification. Keep exclusions narrow so useful reporting is not lost.</p></details>
    <div data-newscatcher ${nc ? '' : 'hidden'}>
      <details data-profile-section data-stream-manual-only><summary>Provider, endpoint and advanced query</summary>
      ${nativeFilterForm(state.meta.newscatcher_filters, opts, pr, esc)}
      <label>Advanced query (optional; replaces the keyword list)</label><textarea name="nc_query" placeholder="e.g. (shipping OR ports) AND strike NOT sport">${esc(pr.query || '')}</textarea>
      </details>
      <details data-profile-section data-stream-step="1"><summary>Coverage geography</summary>
        <label>Regional focus (choose one or more)</label>${multi("coverage_regions", opts.coverage_regions || {}, pr.coverage_regions)}
        <p class="small muted">For example, select Armed conflict with Europe and Asia. Regions add all their country names to one OR group, alongside any countries below. This is approximate coverage, not verified event location. Large regions can require more paid requests; preview first.</p>
        <label>Additional coverage countries</label>${multi("coverage_countries", opts.countries, pr.coverage_countries)}
        <p class="small muted">Leaving both regions and countries empty adds no country-name requirement. Selecting countries matches their names in reporting; this is approximate, not a provider event-location filter.</p>
        <details><summary>Optional: restrict where publishers are based</summary><label>Publisher country (where the outlet is based)</label>${multi("nc_countries", opts.countries, nc ? pr.source_countries : [])}<p class="small muted">This restricts outlets, not event locations, and can exclude valuable international reporting.</p></details>
      </details>
      <details data-profile-section data-stream-step="2"><summary>Developments and event vocabulary</summary>
        <label>Event type (keyword presets)</label>${multi("event_presets", opts.event_presets, pr.event_presets)}
        <p class="small muted">For example, Cyber looks for cyberattack, ransomware or data-breach reporting. Selected event terms must match alongside your keywords and country names. No event selection adds no event restriction.</p>
        <details><summary>Keyword library (one list per category by default)</summary>${eventVocabularyForm(opts.event_vocabularies || {}, p.id ? pr : {event_vocabulary_version:'optimized-v1', ...pr}, {includeBudget:false})}</details>
      </details>
      <details data-profile-section data-stream-step="3"><summary>Reporting languages and content matching</summary>
        ${contentMatchingForm(pr)}
        <label>Article language</label>${multi("nc_languages", opts.languages, nc ? pr.languages : [])}
        <p class="small muted">Leaving this empty permits any article language. English translated-content mode can find non-English reporting without translated keyword sets. Language filters are not silently widened; matching does not guarantee complete coverage.</p>
        ${keywordTranslationForm(opts.keyword_translation || {}, opts.languages, pr)}
      </details>
      <p class="small muted" data-stream-manual-only>Empty country/language/event selection means unrestricted. Use the search bar above each category to find options, then tick your choices — no Ctrl/Cmd key required. Searching does not clear checked options. Geography and event presets add English keyword groups to the API query; they are approximate, not provider-native event/location filters. Keywords, events and geography are ANDed; choices within each group are ORed. Long preset queries are automatically split into multiple requests (up to 16 per poll), with every selection retained. Each request consumes API quota/credits. Preview the request count before enabling.</p>
    </div>
    <div class="grid-2" data-gdelt data-stream-manual-only ${nc ? 'hidden' : ''}>
      <div><label>Publisher countries (GDELT names, e.g. finland)</label><input name="source_countries" value="${nc ? '' : j("source_countries")}"></div>
      <div><label>Languages (GDELT names, e.g. english)</label><input name="languages" value="${nc ? '' : j("languages")}"></div>
    </div>
    <details data-profile-section data-stream-manual-only><summary>Dashboard links</summary>
    <label>Link stream to dashboards</label>${multi("dashboard_ids", Object.fromEntries(state.sets.map(s => [s.id, s.name])), p.dashboard_ids)}
    <p class="small muted">Linked dashboards use articles from their linked streams, still requiring a PIR match. Dashboards with no linked streams keep using all articles. Links affect existing articles too; saved summaries are not rewritten.</p>
    </details>
    <details data-profile-section data-stream-step="4"><summary>Schedule and collection limits</summary>
      <label>Check for new articles</label><select name="interval_minutes">${Object.entries({...opts.intervals, [p.interval_minutes]: opts.intervals[p.interval_minutes] || `Every ${p.interval_minutes} minutes`}).map(([n, label]) => `<option value="${n}" ${Number(n) === p.interval_minutes ? "selected" : ""}>${esc(label)}</option>`).join("")}</select>
      <div data-newscatcher ${nc ? '' : 'hidden'}>${eventBudgetForm(pr)}</div>
    <details><summary>Optional: first poll and result limits</summary><p class="small muted">Lookback sets the initial time window. The article cap applies to each request, not the entire poll; it does not guarantee complete coverage.</p><div class="grid-3">
      <div><label>First-run lookback (hours)</label><input name="lookback_hours" type="number" required min="1" max="720" value="${pr.lookback_hours ?? 24}"></div>
      <div><label>Max articles per API request / page (capped by plan; split queries can return more per poll)</label><input name="max_records" type="number" min="1" max="1000" value="${pr.max_records ?? 100}"></div>
    </div></details>
      <div data-stream-manual-only><label class="inline"><input type="checkbox" name="enabled" ${p.enabled ? "checked" : ""} ${p.id ? '' : 'disabled'}> ${p.id ? 'Enabled' : 'New streams are saved paused'}</label></div>
    </details>`;
}
const selections = (f, name) => Array.from(f.elements[name].selectedOptions, o => o.value);
const readProfileForm = (f) => ({
  dashboard_ids: selections(f, "dashboard_ids").map(Number),
  name: f.elements.name.value.trim(), source: f.elements.source.value, enabled: f.id === 'new-prof' ? false : f.elements.enabled.checked, interval_minutes: Number(f.elements.interval_minutes.value),
  params: {
    ...(f.elements.source.value === 'newscatcher' ? {...readNativeFilters(f), ...readEventVocabulary(f), ...readKeywordTranslation(f), content_matching:f.elements.content_matching.value} : {}),
    query: f.elements.source.value === 'newscatcher' ? f.elements.nc_query.value.trim() : '',
    keywords: lines(f.elements.keywords.value), themes: f.elements.source.value === 'gdelt' ? lines(f.elements.themes.value) : [], combine: f.elements.combine.value,
    source_countries: f.elements.source.value === "newscatcher" ? selections(f, "nc_countries") : lines(f.elements.source_countries.value),
    languages: f.elements.source.value === "newscatcher" ? selections(f, "nc_languages") : lines(f.elements.languages.value),
    coverage_regions: f.elements.source.value === "newscatcher" ? selections(f, "coverage_regions") : [],
    coverage_region_version: 'coverage-regions-v1',
    coverage_countries: f.elements.source.value === "newscatcher" ? selections(f, "coverage_countries") : [],
    event_presets: f.elements.source.value === "newscatcher" ? selections(f, "event_presets") : [],
    exclude_keywords: lines(f.elements.exclude_keywords.value), lookback_hours: Number(f.elements.lookback_hours.value), max_records: Number(f.elements.max_records.value),
  },
});

async function reviewExperimentalVocabulary(form, payload) {
  if (payload.source !== 'newscatcher' || (payload.params.query_planner_version === 'legacy-v1' && !payload.params.multilingual_enabled)) return true;
  const preview = await api('/api/profiles/preview-query', {method:'POST', body:payload});
  const target = form.querySelector('[data-q]');
  target.hidden = false; target.style.display = 'block'; target.textContent = queryPreviewText(preview);
  if (JSON.stringify(payload) !== JSON.stringify(readProfileForm(form))) {
    toast('The form changed during preview. Save again to review the current settings.', 5000); return false;
  }
  return confirm(`Apply ${preview.query_planner_version} request planning, ${preview.content_matching?.mode || 'existing'} content matching, and experimental ${preview.vocabulary.version} (${preview.vocabulary.tiers.join(', ')})?\n\n${preview.request_count} requests / poll; nominal estimate ${preview.estimated_credits_per_poll ?? 'unknown'} credits / poll and ${preview.estimated_credits_per_30_days ?? 'unknown'} credits / 30 days.\n\nMultilingual targets: ${preview.translations?.languages.join(', ') || 'disabled'}; original query retained. Approved snapshot: ${preview.translations?.review_id || 'none'}.\n\n${preview.vocabulary.removed_vs_legacy.length} legacy terms removed; expanded core is not a strict superset. Retries/manual runs are extra. Cancel to inspect the complete term/query preview before applying.`);
}

async function settingsProfiles(body, {allowCreate = false} = {}) {
  state.profiles = await api("/api/profiles");
  body.innerHTML = `<div class="stack">
    <div class="card pad"><h2>${allowCreate ? 'Configure article streams' : 'Manage existing streams'}</h2><p class="muted small">${allowCreate ? 'Build a stream step by step, then inspect its full settings. New streams are saved paused. Unsaved answers stay while moving between steps or advanced mode, but are not retained after leaving or reloading this page.' : 'Modify saved stream filters, schedules, dashboard links and enabled status here. To create a new stream, go to Pre-ingestion.'} Polling fetches new articles, not a separate catalogue of publishers. Each poll consumes API quota; the worker checks schedules approximately once a minute.</p>${state.meta.newscatcher_configured ? '' : '<p>NewsCatcher API key is missing. Set NEWSCATCHER_API_KEY before enabling a NewsCatcher stream.</p>'}</div>
    ${allowCreate ? `<div class="card pad"><h2>New article stream</h2><form id="new-prof">${profileForm()}<div class="qpreview mono" data-q hidden></div><div data-stream-actions class="row" style="margin-top:10px"><button type="submit" class="primary">Create stream</button> <button type="button" data-preview>Refresh request preview</button></div></form></div>` : ''}
    ${!allowCreate && !state.profiles.length ? '<div class="card pad muted">No streams have been configured. <a href="#/ingestion">Create your first stream in Pre-ingestion</a>.</div>' : ''}
    ${state.profiles.length ? '<h2>Saved streams</h2>' : ''}
    ${state.profiles.map((p) => `
      <div class="card pad" data-prof="${p.id}"><form>${profileForm(p)}
        <div class="qpreview mono" data-q style="display:none"></div>
        <div class="row" style="margin-top:10px"><button class="primary">Save</button><button type="button" data-run ${p.enabled ? '' : 'disabled title="Enable and save this stream first"'}>Run now</button>
          <button type="button" data-preview>Preview query</button><span class="spacer"></span><button type="button" class="danger" data-del>Delete</button></div>
        <div class="small muted" style="margin-top:8px">${p.enabled ? 'Enabled' : 'Paused'} · Last successful poll: ${p.last_run_at ? fmtDate(p.last_run_at) : "never"} · Next: ${!p.enabled ? 'paused' : p.next_run_at ? fmtDate(p.next_run_at) : 'next worker tick'} · ${esc(p.last_status || "")}<br><a href="#/stream" data-articles="${p.id}">View stream articles</a> · <a href="#/setup/${p.id}">Next: guided dashboard setup</a></div></form>${collectionDiagnostics(p)}</div>`).join("")}
  </div>`;
  enhanceMultiSelects(body);
  wireCollectionDiagnostics(body, api);
  body.querySelectorAll('form').forEach(f => {
    if (!f.elements.source) return;
    wireEventVocabulary(f, state.meta.ingestion_options.event_vocabularies || {});
    wireKeywordTranslation(f, state.meta.ingestion_options.keyword_translation || {}, api, () => readProfileForm(f).params, async () => {
      const result = await api('/api/profiles/preview-query', {method:'POST', body:{...readProfileForm(f), name:f.elements.name.value.trim() || 'Translation preview'}});
      const target = f.querySelector('[data-q]'); target.hidden = false; target.style.display = 'block'; target.textContent = queryPreviewText(result);
    });
    f.elements.nc_endpoint.onchange = () => f.querySelectorAll('[data-nc-mode]').forEach(el => el.hidden = el.dataset.ncMode !== f.elements.nc_endpoint.value);
    f.elements.source.onchange = () => {
      f.querySelectorAll('[data-newscatcher]').forEach(el => el.hidden = f.elements.source.value !== 'newscatcher');
      f.querySelectorAll('[data-gdelt]').forEach(el => el.hidden = f.elements.source.value !== 'gdelt');
      f.querySelectorAll('[data-event-vocabulary] input, [data-event-vocabulary] select, [data-event-budget] input').forEach(el => el.disabled = f.elements.source.value !== 'newscatcher');
    };
    wireContentMatching(f);
    f.elements.source.onchange();
  });
  body.querySelectorAll('[data-articles]').forEach(a => a.onclick = () => { streamFilters.profile_id = a.dataset.articles; streamFilters.set_id = ''; streamFilters.pir_id = ''; });
  body.querySelectorAll("[data-prof]").forEach((card) => {
    const id = card.dataset.prof, f = card.querySelector("form");
    f.onsubmit = async (e) => { e.preventDefault(); try { const payload = readProfileForm(f); if (!await reviewExperimentalVocabulary(f, payload)) return; await api(`/api/profiles/${id}`, { method: "PUT", body: payload }); toast("Saved"); settingsProfiles(body, {allowCreate}); } catch (err) { toast(err.message, 5000); } };
    card.querySelector("[data-run]").onclick = async () => { await api(`/api/profiles/${id}/run`, { method: "POST" }); toast("Queued — the worker respects any active retry cooldown"); };
    card.querySelector("[data-del]").onclick = async () => { if (confirm("Delete this profile? Its articles are kept.")) { await api(`/api/profiles/${id}`, { method: "DELETE" }); settingsProfiles(body, {allowCreate}); } };
    card.querySelector("[data-preview]").onclick = async () => {
      const q = card.querySelector("[data-q]"); q.style.display = "block";
      try { const r = await api("/api/profiles/preview-query", { method: "POST", body: readProfileForm(f) }); q.textContent = queryPreviewText(r); }
      catch (err) { q.textContent = err.message; }
    };
  });
  const focused = body.querySelector(`[data-prof="${Number(location.hash.split('/')[3])}"]`);
  if (focused) focused.scrollIntoView({block:'start'});
  if (!allowCreate) return;
  const newForm = $('#new-prof');
  const tutorial = wireStreamTutorial(newForm, {readProfile:readProfileForm, api, previewText:queryPreviewText, options:state.meta.ingestion_options});
  newForm.onsubmit = async (e) => {
    e.preventDefault();
    const f = e.currentTarget;
    if (f.dataset.saving) return;
    f.dataset.saving = 'true';
    try {
      if (!await tutorial.prepareSave()) return;
      const b = readProfileForm(f), snapshot = tutorial.fingerprint();
      if (!await reviewExperimentalVocabulary(f, b)) return;
      if (!tutorial.isCurrent(snapshot)) { toast('Settings changed. Review the current preview before saving.', 5000); return; }
      const profile = await api('/api/profiles', {method:'POST', body:{...b, enabled:false}});
      toast('Stream saved paused. Inspect the sections below, or follow Set up dashboard when ready.', 6000);
      location.hash = `#/settings/profiles/${profile.id}`;
    } catch (err) { toast(err.message, 5000); }
    finally { delete f.dataset.saving; }
  };
}

async function settingsPipeline(body) {
  const [s, models] = await Promise.all([api('/api/status'), api('/api/settings/models')]);
  state.meta.models = {classify: models.effective.classify.model, summary: models.effective.summary.model};
  const c = s.articles_by_status || {};
  body.innerHTML = `<div class="stack">
    <div class="card pad" id="pipeline-health">${pipelineStatusHtml(s, esc, fmtDate)}</div>
    <div class="card pad"><h2>Articles</h2>
      <table style="max-width:480px;margin-top:8px"><tbody>
        ${["pending", "enriched", "irrelevant", "failed"].map((k) => `<tr><td>${k}</td><td class="tabnum">${c[k] || 0}</td></tr>`).join("")}
        <tr><td>Ingested in last 24h</td><td class="tabnum">${s.ingested_24h}</td></tr></tbody></table>
      <p class="small muted">Classifier: <code>${esc(state.meta.models.classify)}</code> · Summaries: <code>${esc(state.meta.models.summary)}</code>
        · Classification provider ${(state.meta.classify_configured ?? state.meta.claude_configured) ? "configured" : "<b style='color:var(--status-critical)'>not configured</b>"}</p></div>
    <div class="card pad"><h2>Reclassify</h2>
      <p class="muted small">Re-run classification for articles published in the last N days, for example after editing PIRs. This uses the selected classification provider for each article and may incur API costs.</p>
      <div class="row"><input id="rc-days" type="number" value="7" min="1" max="90" style="width:90px"> days
        <label class="inline"><input type="checkbox" id="rc-irr" checked> include items marked not relevant</label>
        <button class="primary" id="rc">Reclassify</button><button id="retry">Retry failed (${c.failed || 0})</button></div></div>
    <div class="card pad"><h2>Profiles</h2><table><thead><tr><th>Profile</th><th>Source</th><th>Last run</th><th>Status</th></tr></thead><tbody>
      ${s.profiles.map((p) => `<tr><td>${esc(p.name)}</td><td>${esc(p.source)}</td><td>${p.last_run_at ? fmtDate(p.last_run_at) : "never"}</td><td class="small">${esc(p.last_status || "")}</td></tr>`).join("")}
    </tbody></table></div></div>`;
  $("#rc").onclick = async () => {
    const days = Number($("#rc-days").value);
    if (!confirm(`Queue all articles from the last ${days} days for reclassification?`)) return;
    const r = await api("/api/admin/reclassify", { method: "POST", body: { days, include_irrelevant: $("#rc-irr").checked } });
    toast(`${r.queued} articles queued`); settingsPipeline(body);
  };
  $("#retry").onclick = async () => { const r = await api("/api/admin/retry-failed", { method: "POST" }); toast(`${r.queued} queued`); settingsPipeline(body); };
}

// ================= ROUTER =================
async function route() {
  clearTimers();
  overviewCleanup(); overviewCleanup = () => {};
  dashState.map?.dispose(); dashState.map = null;
  renderNav();
  const h = location.hash || '#/home';
  try {
    if (h === "#/ingestion" || h.startsWith("#/settings/profiles")) { state.sets = await api('/api/pir-sets'); renderNav(); }
    if (h === '#/home') overviewCleanup = await renderOverview({api, view, esc, safeUrl, sparkline, trendBadge, every});
    else if (h === "#/setup" || h.startsWith("#/setup/")) await renderDashboardSetup({api, state, view, esc, toast, renderNav}, h.split('/')[2]);
    else if (h.startsWith("#/dash/")) await renderDashboard(h.split("/")[2]);
    else if (h === "#/ingestion") { view.innerHTML = '<h1 style="margin-bottom:12px">Pre-ingestion</h1><div id="ingestion-body"></div>'; await settingsProfiles($('#ingestion-body'), {allowCreate: true}); }
    else if (h.startsWith("#/settings")) await renderSettings(h.split("/")[2] || "pirs");
    else await renderStream();
  } catch (e) {
    view.innerHTML = `<div class="empty">Something went wrong: ${esc(e.message)}</div>`;
  }
  every(30000, refreshPill);
}

(async function boot() {
  [state.meta, state.sets, state.profiles] = await Promise.all([api("/api/meta"), api("/api/pir-sets"), api("/api/profiles")]);
  renderBrand(state.meta.branding);
  window.addEventListener("hashchange", route);
  window.addEventListener('themechange', () => window.dispatchEvent(new Event('resize')));
  refreshPill();
  route();
})();
