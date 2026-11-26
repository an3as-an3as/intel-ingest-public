# User guide

Detailed behaviour of each part of Intel Ingest. Start with the [README](../README.md) for an overview and quick start.

## Pre-ingestion: configure article streams

Open **Pre-ingestion** to create a named NewsCatcher stream before pulling articles.
New streams start paused. Select publisher countries, article languages, coverage-country
presets and event-type presets using searchable checkbox selectors. Click/tap multiple
options normally — no Ctrl/Cmd key required. Selected counts remain visible.
Add keywords/exclusions, preview the complete API request, choose a polling interval (5 minutes–daily),
and save. Enable and save the stream when ready; **Run now** queues an enabled stream for
the next worker tick. The API key remains in the server environment.

* Publisher country filters the outlet's country, **not** the event's location.
* Coverage geography and event types are **approximate English keyword presets**, not
  native NewsCatcher location/event classifications. Keywords, selected event presets,
  and coverage countries form AND groups; choices within a group are ORed. English
  presets may miss non-English reporting. Use Preview query to inspect the exact query.
* Empty selections mean unrestricted. Countries and languages use full ISO vocabularies
  (plus NewsCatcher's Chinese aliases), not a live catalogue of available coverage.
* **All native API filters & response controls** exposes the documented parameters for the
  selected endpoint: current `/search`, current `/articles`, or Enterprise v3 when configured.
  This includes exclusions, publishers, coverage/content controls, sorting, dates, and
  endpoint-specific advanced filters. Unsupported fields are rejected rather than ignored.
  Paid filters remain subject to your subscription. Long preset queries are split into
  up to 16 requests per poll without dropping selections; each request consumes credits.
  Preview shows the request count. One page is fetched per query part; the article cap
  applies per request and combined results are deduplicated.
  See [filter coverage and official documentation sources](newscatcher-filters.md).
* Explicit date/search-window filters override automatic polling windows and may repeat
  the same period (and API charges) each poll. Preview shows this distinction.
* Polling checks for **new articles**, not a separate publisher-discovery endpoint. Each
  search consumes quota. Busy streams may exceed the plan's result cap and miss reports;
  narrow the query or poll more often. Scheduling is approximate (worker tick cadence).
* Link streams to one or more existing PIR dashboards. A linked dashboard scopes its
  reporting, map, counts, trends and newly generated summaries to its linked streams,
  still requiring a PIR match. A dashboard **without links uses all streams** (legacy behavior).
  Removing the final link restores this all-stream scope. Create dashboards/PIRs in Settings.
* Overlapping streams share deduplicated articles without losing stream membership.
  Old articles retain their original profile; historical memberships in other streams
  cannot be reconstructed without fetching them again. Link changes apply to existing
  articles, but already-generated summaries are unchanged.

Create new streams only in **Pre-ingestion**. **Settings → Ingest profiles** is for
modifying existing streams (filters, schedules, links, pause/enable, run and delete);
it has no stream-creation form. If no streams exist, it links back to Pre-ingestion.
Existing GDELT profiles remain editable in either place.

Saved dashboards live in the persistent **left-hand Dashboards pane**, rather than
the top navigation. Selecting a dashboard highlights it in the pane. On narrow
screens the pane becomes a compact, scrollable section above the main content.
Use the top-left sidebar button to collapse/restore it; this preference is remembered
in the browser, and maps/globe resize to use the available space.
New link/membership tables are created automatically at startup; existing data is kept.
Rebuild and restart both API and worker together after updating.

## Main dashboard: 3D globe and cross-dashboard trends

**Main dashboard** is the home page. Drag the globe to rotate, scroll to zoom, or use
the rotation/zoom/reset buttons. The slow-rotation checkbox is off by default.

* The globe is a simple monochrome wireframe with country outlines, no satellite
  texture/topography, no filled countries and no coloured atmosphere. Only major
  cities are labelled; labels are decluttered and become more detailed when zooming.
  Natural Earth population rankings are used only for label prioritisation, not as
  current demographic data. Borders are approximate geographic context.
* Events are dots in each dashboard's colour. Nearby articles are grouped per dashboard
  into one dot labelled with the article count; dots grow to a capped size, then only the
  number increases. Dashboards at the same place sit side by side. Zooming in separates
  nearby locations. Click a dot to see its count and source links.
* Last 24 hours/week/month/quarter means rolling **24 hours/7/30/90 days**, and changes both
  globe reporting and the small graphs (hourly counts for 24 hours, daily otherwise). Trends compare against the preceding equal
  period, using the same 25% / minimum-three-report change threshold as the existing
  dashboards. Small samples show **Low volume**, not an unsupported rising/stable claim.
* Each graph counts **unique classified articles answering at least one active PIR
  in that set**, scoped to the dashboard's linked streams. Matching two PIRs in the
  same set does not double-count an article. An article matching two dashboards
  counts in each. Counts describe reporting volume, not unique real-world events.
* Reports without usable coordinates are included in counts/trends but not plotted.
  The globe plots every geolocated article in the period, grouped per place (~1 km), with
  up to 20 recent sources listed per place. Only extremely large periods (over 20,000
  geolocated articles per dashboard) are truncated, and that is labelled.
* The globe refreshes every minute. It requires WebGL and access to the pinned
  `globe.gl` CDN library; if unavailable, graphs and dashboard links remain usable.
  Country outlines and city context are served locally from Natural Earth data;
  the starfield background loads from the pinned `three-globe` CDN package. Globe rendering sends no article data to a mapping
  provider. GPU/animation resources are disposed when leaving the main page.

Every individual dashboard uses this **same wireframe renderer**, rather than a
separate street/tile map. Its initial view focuses on the matched reporting region;
PIR selection and time-window filters update both the reporting list and globe.
Cluster centres summarise nearby locations and do not claim to be exact event sites.
Repeated reports with identical coordinates remain grouped even when zoomed in.

## Guided dashboard setup

After creating a stream, the app opens **Set up dashboard**. For an existing stream,
choose **Next: guided dashboard setup**, or use the navigation link.

The wizard walks through five steps:

1. **Select streams** — reuse configured queries and schedules; paused streams stay paused.
2. **Define the objective** — name the dashboard and explain what decision or situation it supports.
3. **Set the scope** — describe event geography, actors/assets and dashboard-wide exclusions.
4. **Ask specific questions** — add one or more questions, evidence/indicators, exclusions and priorities.
   Each question becomes a dashboard card (a Priority Intelligence Requirement, or PIR).
5. **Review & launch** — inspect the compiled model instructions, choose whether to analyse
   already-collected articles (24 hours–90 days), acknowledge API usage, then create the dashboard.

Answers are compiled directly into the PIR catalogue used by the classifier; no separate
model call or API credits are needed to draft/preview the instructions. The classifier scores
each article against the saved questions, explains matches and supplies the existing map,
reporting, counts and trends. At runtime it sees all active dashboards' requirements, not
only the previewed dashboard. Codes shown as `DRAFT-*` are replaced by unique codes on save.
You can edit the saved requirements under Settings → Intelligence requirements.

Launching links the selected streams without changing their source configuration or removing
existing dashboard links. Optional backfill queues only recent articles in the selected streams,
including previously irrelevant/failed articles. Their full classification is refreshed, so shared
articles may temporarily disappear from other dashboards until processed again. Existing pending
articles are processed regardless of the backfill selection. Each article classification incurs
model API usage. With no backfill, already-classified articles are not scored against the new
requirements; use Pipeline → Reclassify later if needed.

The dashboard shows pending, classified, irrelevant, failed and matched counts, and refreshes
results automatically. These are stream-wide processing counts, not an isolated job progress bar.
The worker and selected classification provider must be configured for classification to run. If streams are
paused and no articles are already collected, enable them in Pre-ingestion to get reporting.
Wizard answers survive Back/Continue and navigation within the page, but unsaved drafts are
not retained after a browser reload.

## How it works

```
 ingest profiles ──► GDELT / NewsCatcher ──► dedupe (URL + headline) ──► fetch article text
   (initial filter:                                                           │
    keywords, themes,                                                         ▼
    countries, language)                         Selected model provider (1 call / article)
                                                 relevant? · event type · region · countries
                                                 location + lat/lon · summary · PIR scores 0–1
                                                                              │
                     ┌────────────────────────────────────────────────────────┤
                     ▼                                                        ▼
   Stream (all relevant items, faceted)        Dashboard per PIR set: map · counts · trend
                                               · on-demand summaries (week / month / quarter)
```

* **Ingest profiles** (Settings → Ingest profiles) are the coarse, source-side filter.
  Make them broad; the selected classifier does the precise sorting. GDELT returns ≤250 articles per run,
  so split busy topics into several profiles.
* **PIRs** (Settings → Intelligence requirements) are written in plain language. The
  requirement and indicator text is the classifier's prompt, so editing a PIR changes how
  new articles are scored, with no retraining. To re-score older articles, use
  **Pipeline → Reclassify**.
* An article counts towards a PIR when its score is at or above `PIR_MATCH_THRESHOLD`
  (default 0.5). Articles matching no PIR and not judged generally relevant are marked
  *irrelevant*. They are hidden from the stream by default but kept.
* **Trend:** each PIR's count in the selected window is compared with the previous window of
  the same length. "Rising"/"Falling" needs a change of at least 25% and at least 3 articles, so small
  counts read as "Steady" or "Low volume" rather than noise.
* **Summaries** are written only from the classified articles in the period (top 40 per
  PIR by relevance). They use estimative language and confidence levels, and every factual
  statement cites the source report, linked in the UI.

## Model selection in Settings

Open **Settings → Models** to choose a **provider + model** independently for
**article classification** and **intelligence summaries**. Cloud providers use
server-side API keys; Ollama lists installed models on the explicitly configured
server. **Refresh available models** runs discovery only: no inference or article
text. Discovery confirms availability, not task quality or schema compatibility;
some listed models cannot perform classification. Save verifies both choices
before changing preferences. Model access/quotas are still enforced at inference.

Choices are stored in Postgres and shared by API and worker. Each new batch/job
snapshots its settings; in-flight work and existing results are not regenerated.
New non-Anthropic results record `provider:model`; old Claude references stay
unchanged. Reclassification is an explicit action and may incur further costs.

Anthropic offers advertised effort levels; alternative adapters currently support
**Auto** only. Classification output is validated locally against the app's JSON
schema. Refusals, malformed output and truncation fail rather than silently marking
articles irrelevant. Model IDs currently have a 64-character storage limit.
There is no automatic cross-provider fallback.

`.env` provides defaults until preferences are saved. **Use environment defaults**
removes that override. Keys and endpoints are not stored in model preferences or
sent to the browser. Editing `.env` requires recreating **both API and worker**;
changing selections in Settings does not. See [API-key setup](api-keys.md)
and [provider capabilities, Ollama networking and rollback](model-providers.md).

## Pipeline health and restart-safe summaries

**Settings → Pipeline** shows the worker heartbeat, current phase and phase start,
last completed tick/error, oldest pending work and summaries by status. The health
panel refreshes every 10 seconds. A heartbeat older than 45 seconds (or a stopped
worker) is labelled stale/offline. A fresh heartbeat means the process is alive,
not that external APIs are succeeding; check phase duration, errors and progress.
Recent crash history is retained for up to seven days. `/healthz` remains API
liveness only; authenticated `/api/status` includes worker/queue information.

Summary requests are saved in PostgreSQL, not scheduled inside the API process.
The worker handles the oldest pending summaries, at most one per tick, followed
by one article-classification batch. This bounds work per tick so an article
backlog cannot indefinitely postpone new polls or summaries. A tick may still take
longer than the configured interval while waiting for external APIs. Summary
creation and processing require the worker and the selected summary provider's
server configuration (a cloud key or reachable Ollama endpoint).

The worker holds a PostgreSQL row lock during summary generation. Other workers
skip the locked job; interrupted transactions leave it pending for recovery on a
later tick. Existing pending summaries are picked up automatically after updating.
Deleting a currently running summary returns a conflict rather than waiting for
the model call. Model failures are saved as failed; use **Retry summary** to queue
another paid attempt. Database failures leave the summary pending for retry.

Recovery is **at least once**, not exactly once: if a process/database connection
dies after a provider has accepted the request but before the result is committed,
recovery may incur another model charge. Long-running summaries hold a transaction
and connection open; a database transaction timeout can interrupt them. Use one
worker replica for this deployment: summary ownership is concurrency-safe, but
article classification and ingestion are not yet multi-worker job queues. SQLite
is only used for single-worker tests, not production queue ownership.

Rebuild **both API and worker** together to enable this feature; the new heartbeat
table is created automatically without replacing existing data. Back up first
(see [repository workflow](repository.md)). No usage/cost accounting or hard
spending limits are included in this milestone.

## Exporting intelligence summaries

Completed reports offer **HTML**, **Markdown (.md)**, **plain text (.txt)** and
**JSON** downloads, preserving period/model metadata and source references.
HTML is a self-contained document with no external scripts, images or fonts; open
it in a browser and use Print → Save as PDF for a PDF copy. HTML output is sanitised
and citations link to the original reporting. Markdown/JSON preserve the original
report text for reuse. Pending/failed reports cannot be exported. Downloads use the
same app authentication and do not trigger a new model call.

## Configuration (`.env`)

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Needed only when selecting Anthropic |
| `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` / `GEMINI_API_KEY` | – | Configure the provider(s) you select |
| `OLLAMA_BASE_URL` | – | Explicit reachable native/Docker/remote Ollama endpoint; no universal host assumed |
| `OLLAMA_API_KEY` | – | Optional Bearer key for a protected Ollama proxy |
| `OPENAI_BASE_URL` / `DEEPSEEK_BASE_URL` / `GEMINI_BASE_URL` | Official HTTPS APIs | Optional trusted server-controlled proxy bases; see `.env.example` |
| `CLASSIFY_PROVIDER` / `SUMMARY_PROVIDER` | `anthropic` | Environment defaults; Settings → Models can override |
| `ALTERNATIVE_MODEL_MAX_TOKENS` | `8192` | App output cap for alternative adapters, further limited by advertised output limits |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `180` | Alternative inference read timeout; discovery uses 15 seconds |
| `NEWSCATCHER_API_KEY` | – | Enables the NewsCatcher source |
| `NEWSCATCHER_API` | `news` | `news` for keys from platform.newscatcherapi.com, `v3` for Enterprise v3 keys |
| `NEWSCATCHER_EFFORT` | `low` | Credits per search: low 1, medium 5, high 10 |
| `APP_PASSWORD` | – | Shared password (HTTP Basic, any username). Set it before exposing the app |
| `CLASSIFY_MODEL` / `CLASSIFY_EFFORT` | `claude-opus-5-5` / `low` | Defaults; choose actual discovered IDs. Alternative providers require effort `auto`; check current provider pricing |
| `SUMMARY_MODEL` / `SUMMARY_EFFORT` | `claude-opus-5-5` / `high` | |
| `PIR_MATCH_THRESHOLD` | `0.5` | |
| `FETCH_ARTICLE_TEXT` / `ARTICLE_TEXT_MAX_CHARS` | `true` / `6000` | Body text is cut to this length before classification |
| `CLASSIFY_CONCURRENCY` / `CLASSIFY_BATCH_SIZE` | `4` / `40` | |
| `MAP_TILE_URL` | OpenStreetMap | Legacy API setting; wireframe dashboard maps no longer request map tiles |

For refusals, Opus/Sonnet models use Anthropic's server-side fallback (`fallbacks: "default"`),
so articles about violence or cyber attacks are not dropped when a safety classifier
declines them. Articles that still fail are marked *failed*; use **Pipeline → Retry failed**.

## Things to know

* **Model data handling:** article text and PIR wording are sent to the selected model
  provider. Cloud APIs and remote Ollama can send this outside your network; a local
  Ollama setup keeps model inference on your chosen host. Profile queries still go to
  GDELT/NewsCatcher. Check privacy, provider terms and costs for your requirements.
* **Map clusters** use the same hollow base circles and thin outward stems on all dashboards.
  Circle radius grows with the mapped-article count (bounded for readability). Click a
  circle/stem to inspect the count and sources; zoom in to separate nearby locations.
  Counts represent articles, not unique real-world events.
* **Coordinates are model-estimated** from the article text. The map draws city-level points
  as filled dots and region/country-level points as rings. Treat both as approximate.
* **GDELT** is free but throttles by IP address (HTTP 429), especially on VPNs and shared IPs.
  On a 429, all GDELT profiles pause together (5 → 10 → 20 → 60 min). If `NEWSCATCHER_API_KEY`
  is set, each GDELT profile's keywords run through NewsCatcher in the meantime. Themes are ignored,
  and languages and countries are converted to ISO codes. The profile status says when the fallback was used.
* Some sites block automated text extraction. Those articles are classified from the headline only.
* The web UI loads marked, DOMPurify and (on dashboard maps) globe.gl from the jsDelivr
  CDN. All maps require WebGL and share local country/city context. No Leaflet or map
  tile requests are made.

## Sharing with the team (later)

1. Set `APP_PASSWORD` in `.env`.
2. In `docker-compose.yml`, change the `api` port from `"127.0.0.1:${APP_PORT:-8080}:8080"` to
   `"${APP_PORT:-8080}:8080"`, then run `docker compose up -d`.
3. The app is served over plain HTTP. Before exposing it beyond a trusted LAN, put it behind
   HTTPS (e.g. a reverse proxy such as Caddy) or a VPN such as Tailscale.

## Developing without Docker

```bash
cd backend
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export DATABASE_URL=sqlite:///./dev.db
# Configure provider keys/endpoints using a private environment or backend/.env.
# For example, Ollama on the same native host: OLLAMA_BASE_URL=http://127.0.0.1:11434
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080 &      # API + UI
python -m app.worker                             # ingestion + classification
```

## Tests

```bash
pip install -r backend/requirements-dev.txt
PYTHONPATH=backend python -m unittest discover -s backend/tests -v
node --test frontend/tests/*.test.mjs
node --check frontend/app.js
```

Tests use disposable SQLite databases and mocked sources/model transports, with no
external inference. Set `TEST_POSTGRES_URL` to a disposable PostgreSQL database to
also run the queue-lock/concurrency tests; never point it at production.

## Layout

```
backend/app/
  main.py              HTTP API + static UI
  worker.py            scheduler loop: run due profiles, classify pending articles
  sources/             gdelt.py, newscatcher.py (add new sources here; register in __init__.py)
  pipeline/            ingest.py, extract.py, classify.py, analytics.py, summarize.py, llm.py
  models.py, sample_cleanup.py, taxonomy.py, config.py
frontend/              index.html, app.js, styles.css (no build step)
```
