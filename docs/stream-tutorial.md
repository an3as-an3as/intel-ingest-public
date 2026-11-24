# Guided stream creation

Status: implemented, verified and rebuilt into **development only** after explicit
user approval. Read-only browser verification at localhost:8081 confirmed Step 1
of 6 is visible. Production is unchanged; worker/provider safeguards remain active.
This is onboarding/UI work before Stage 5, not completion of Stage 4 or permission
for live API calls. Existing uncommitted stages and separate production-checkout
reliability changes are preserved; no backend API or ingestion algorithm changed.

## Beginner flow

Pre-ingestion starts a six-step NewsCatcher tutorial:

1. **Purpose:** name, optional literal keywords and narrow exclusions. Explain
   that collection finds candidates; PIR classification decides relevance later.
2. **Geography:** coverage-country names, with the approximate matching explained.
   Publisher-country restrictions are separate and optional, in a disclosure.
3. **Developments:** event choices and examples. Experimental vocabulary/tiers
   are optional; Legacy v1 remains the default and broad discovery is not enabled.
4. **Languages:** article-language restrictions and optional multilingual search.
   Reuse country suggestions and the full existing translation review. Missing
   rows, conflicts, explicit inclusion/approval and disabled model generation
   remain visible; continuing requires approval or turning multilingual search off.
5. **Collection limits:** schedule, request/optional nominal-credit ceilings.
   Optional first-poll lookback/result caps have a separate disclosure. Explain
   per-request caps, uncertainty, extra classification costs and no monthly cap.
6. **Review:** plain-language summary, totals and cost caveats. Retained advanced
   settings and full technical payloads/terms/warnings are separately expandable.
   A current successful request preview and explicit review acknowledgement are
   required. Experimental saves still use the existing final confirmation.

A completed new stream is always **saved paused**, including advanced-mode saves.
Its enable checkbox is unavailable until it is an existing stream. Backend save
behaviour for other clients/existing streams is unchanged; this is a new-stream UI
safeguard, not a global server policy or spend controller.

After save, navigate to `#/settings/profiles/{id}` and scroll to the saved stream's
manual editor. Settings are organised in collapsible sections. The existing
separate dashboard/PIR wizard is available through the stream's dashboard-setup
link; stream creation no longer redirects straight into that wizard.

## Draft and validation contract

One actual form owns the draft throughout guided and advanced modes. Steps hide
or reveal existing controls rather than rebuilding/serializing another form.
Back/Next and mode switching preserve inputs, native false/zero values, selected
endpoint, exclusions, dashboard links and valid translation approval IDs. GDELT
remains available in advanced mode; returning to the NewsCatcher-only guide does
not silently convert a GDELT draft. The user must deliberately choose NewsCatcher
first if that is intended. No draft survives leaving/reloading the page.

The guide does not reinterpret or drop advanced queries/native filters. It flags
their presence in the guide and lists them in Review. Existing endpoint/translation
validation remains authoritative. Semantic changes invalidate translation approval
through the existing review module; returning async responses cannot restore old
approvals. Multilingual opt-in may create/cache offline review drafts as before,
but does not save or activate a stream by itself.

Only the current step's fields are validated on Continue. Final review validates
applicable fields across the form and reveals an invalid field's step/disclosure.
Inactive source/endpoint native fields are not validated as if they were active.

New-stream review fingerprints the complete serialized payload. Any input change
invalidates acknowledgement and preview; old/in-flight previews cannot approve a
newer draft. Async results are checked for latest request, revision, payload and
form lifetime. Enter during earlier steps advances/validates rather than creating
a stream. Duplicate submissions are guarded. Cancelled experimental confirmation
leaves the saved streams unchanged and retains the draft/approval.

Preview uses the existing compiler endpoint. No provider request, model generation,
worker run, polling change or catch-up execution is added. Manual existing-stream
edits keep their existing API/save behaviour and explicit experimental confirmation.

## Implementation

- `frontend/stream-tutorial.js`: step copy, summary, progressive disclosure,
  mode changes, validation, preview freshness and review gate.
- `frontend/app.js`: grouped form sections, new-stream integration, paused saves
  and manual-editor landing. Existing read/translation/API contracts are reused.
- `frontend/event-vocabulary.js`: vocabulary and budget markup can be rendered
  separately so each appears in its appropriate step; the standalone default
  still includes both, and serialization/compiler semantics are unchanged.
- `frontend/styles.css`: disclosure, progress, summary and mobile layout.
- `frontend/tests/stream-tutorial.test.mjs`: seven offline helper/summary tests.
- `scripts/test_stream_tutorial_browser.py`: actual UI/API acceptance with a
  disposable SQLite database, blocked external transports and synthetic fixtures.
- `scripts/test_stages_browser.py`: adjusted to enter advanced mode/open manual
  sections, acknowledge new-stream review and expect the new post-save landing.
  Existing stages 2–3 assertions remain; catch-up browser regression also passes.

## Fresh verification

```bash
./scripts/development.sh check
./scripts/development.sh test
git diff --check
# Host test environment with Playwright; setup is documented in the scripts:
python scripts/test_stream_tutorial_browser.py
python scripts/test_stages_browser.py
python scripts/test_catchup_browser.py
```

**115 backend + 53 frontend = 168 automated tests passed.** All three Chromium
scripts passed, covering desktop/mobile, navigation and preservation, advanced
false/zero/query round-trip, stale returning preview, budget refusal, required
acknowledgement, duplicate prevention, paused save/manual landing/reload,
multilingual conflict/approval, approval retained through mode changes,
experimental cancel/confirm, and prior stages/catch-up behaviour.

Zero provider calls/page errors in the fixture browser tests; no articles created.
No persistent development/production fixture records, live relevance/cost test,
new PostgreSQL smoke, migration, commits, pushes or production deployment were performed.
The first tutorial smoke attempts needed harness corrections (use the existing
180-minute option, and wait for the async manual editor to render after navigation).
These were harness errors, not reported application failures. Test image builds do
not update running services. The user subsequently approved a development-only
rebuild; it was performed using the pinned helper and checked read-only in Chromium,
without saving configuration. Production container identities/start times were
unchanged; no development worker was started. Future rebuilds need approval.
