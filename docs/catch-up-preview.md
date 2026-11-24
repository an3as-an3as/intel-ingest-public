# Stage 4, first bounded slice: offline catch-up preview

Status: implemented locally in development; **not deployed** and not a completed
Stage 4 collection/diversity implementation. No real collection, subscription
lookup, translation model call, worker execution or live pilot is added.

## What this adds

Under a saved stream's **Collection diagnostics**, load recent polls and open
**Offline catch-up plan preview**. Only a saved NewsCatcher **Articles** stream
with finished capped/history-clamped/partial/failed poll evidence offers the form.

Choose a bounded interval within that poll's requested window, a window length,
and total request/nominal-credit ceilings. Supply recent operator-declared access
evidence, inspect the complete payloads, and stop there: there is deliberately no
Execute, Save, Run or automatic schedule control. Unsaved stream-form edits are
not used. Editing preview inputs invalidates the displayed result.

Each date window uses page 1 for every query split/approved language lane. All
windows, splits and lanes share **one total budget**. The stricter of the explicit
preview ceiling and saved stream ceiling applies; a saved optional credit ceiling
also applies. The global 16-request maximum cannot be raised. The complete plan
is refused if it cannot fit. Windows, languages, phrases and filters are not dropped.

It preserves the original query compiler's semantics, saved native filters,
exclusions, publisher/language/geography restrictions and reviewed translation
snapshot. It does not create reviews or refresh translations. The effective page
size is explicitly shown: the smaller of the saved article cap, declared access
cap and endpoint maximum of 100.

## Evidence and conservative refusals

- Select a finished poll belonging to this stream, with result-cap/history-clamp
  evidence or a partial/error result. A healthy uncapped poll alone is not evidence
  of indexing delay. Successful coverage watermarks are not completeness proofs.
- The ledger's configuration hash must exactly match the current saved parameters.
  Even a budget-only parameter edit makes old evidence stale. Historical query
  reconstruction and fallback-provider/other-stream evidence are not guessed.
- The interval must be nonempty, timezone-aware, end no later than now and be
  contained within the selected poll's *requested* window.
- Unknown Articles entitlement is refused. The operator must explicitly confirm
  access, provide a non-secret reference, an archive start and a permitted page
  size, with an observation timestamp within the past 24 hours.
- This declaration is labelled **operator-declared; not live-verified**. It is not
  proof of access or authorisation to make paid requests. No subscription endpoint
  is queried, cached plan data assumed, or production credential copied.
- Dates before the declared archive boundary are rejected, never clamped away.
- Saved explicit `from_date`, `to_date` or `page` controls are rejected rather than
  overridden. They remain unchanged. This first slice does not combine/reinterpret
  user-supplied date syntax or pagination.
- Search/v3/GDELT are not converted to Articles. Search has no arbitrary historical
  paging. Switching a saved endpoint is a separate deliberate configuration change,
  and multilingual approval may need renewing.
- The final short window retains the exact requested end. Adjacent windows share
  a boundary; provider-inclusive time semantics may produce overlap.

## API

```text
POST /api/profiles/{id}/catch-up-preview
```

Example request (illustrative timestamps/IDs, not live access evidence):

```json
{
  "evidence_run_id": 12,
  "window_start": "2026-11-18T10:00:00Z",
  "window_end": "2026-11-18T12:00:00Z",
  "window_minutes": 60,
  "max_requests": 4,
  "max_credits": 20,
  "entitlement": {
    "confirmed": true,
    "reference": "Operator subscription note; no credentials",
    "observed_at": "2026-11-18T12:00:00Z",
    "history_start": "2026-10-19T12:00:00Z",
    "max_articles_per_page": 20
  }
}
```

Malformed fields/extra controls (including `execute` or `page`) return 422.
Missing/foreign poll evidence returns 404. Unsafe/ineligible/stale/over-budget
plans return 409 with an explanatory code/message. A successful response contains
`preview_only: true`, `executable: false`, evidence reasons, effective total
budgets, all windows and every request payload/language-lane attribution. It has
no saved job or execution ID. No database commits, articles, ledgers, schedules,
watermarks, stream settings or translation/cache rows are changed by preview.

## What this does not prove or implement

Nominal Articles credits are estimated at **5 per request**, not invoices, a
monthly cap, or downstream classification/translation cost accounting. A preview
can still produce saturated responses if ever run. Coverage remains explicitly
**uncertain** and indexing delay **not measured**. This does not retrieve missing
reports, adaptively partition busy windows, page through results, deduplicate
replays, distinguish syndicated from independent reporting, or add source lanes.
Live entitlement, financial limits, request/call controls and execution still need
separate approval and implementation before the Stage 5 comparison.

## Verification and files

Fresh development checks for this implementation:

```bash
./scripts/development.sh check
./scripts/development.sh test
git diff --check
# Test virtualenv with Playwright installed; see the scripts' docstrings:
python scripts/test_catchup_browser.py
python scripts/test_stages_browser.py
```

Results: **115 backend + 46 frontend tests = 161 passed**, plus Chromium desktop/
mobile acceptance smoke for stages 2–3 and this Stage-4 slice. Provider transports
were blocked. Browser/API fixtures used temporary SQLite databases, not persistent
development/production records; Stage-4 snapshots verify the database is unchanged
on both success and refusal. No PostgreSQL-specific planner smoke or live relevance/
cost comparison is claimed. No schema changes are required.

Implementation is isolated to `backend/app/pipeline/catchup.py`, a new endpoint in
`backend/app/main.py`, `frontend/catchup.js` and integration in
`frontend/collection.js`; tests are `backend/tests/test_catchup_preview.py`,
`frontend/tests/catchup.test.mjs`, `scripts/test_catchup_browser.py`. Other existing
uncommitted stages/reliability work is preserved. Neither stack was restarted;
no production integration, commits, pushes or deployment were performed.
