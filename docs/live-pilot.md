# Stage 5 preparation: bounded manual API pilot

Status: **tooling implemented; live calls disabled by default**. Separately approved
diagnostics identified provider language validation and a 50-row account limit.
A subsequent explicitly approved collection-only comparison completed under its
10-request/10-nominal-credit allowance, without model calls. Private ledgers/reports
retain the results; relevance, actual billing and completeness are not established.
This does not complete Stage 4/5, enable a worker, change either app's credentials/
network, or add a live button to the tutorial.

## Isolation and safety contract

The runner is a separate process with its own private SQLite ledger under ignored
`data/pilots/<generated-id>/pilot.sqlite`. It does not import application settings,
source adapters or the application DB; it reads only the existing NewsCatcher
schema snapshot as data. No `.env`, stream database, production configuration,
translation-review ID or API credential is imported. All CLI commands first run
the pinned development isolation validator; that validator does not enable live
access. Existing development provider flags/network and stopped worker remain so.

Transport has fixed NewsCatcher/Anthropic HTTPS hosts and paths, no redirects,
fallbacks, automatic retries, publisher-page fetching, subscription lookup,
SDK model discovery, proxy/netrc inheritance or unattended scheduler. Responses
have a 2 MB cap and connect/read timeouts. This is **process/state/credential
separation and fixed destinations, not a new hostile-code network sandbox**.
Before live use, approve the dedicated runner/runtime/network policy too; do not
weaken the development Compose guard to provide it internet access.

All of these are required for a live dispatch:

1. An explicitly created `mode: live` ledger (default is `simulation`).
2. Separately agreed endpoints, access/reference, reference corpus, requirements/
   model, total request/credit/token allowances, expiry, metrics and stop policy.
3. Explicit operator access confirmation; this is not provider-verified access.
4. Exact frozen-plan hash approval using `arm --approval-hash ... --ack-paid`.
5. Deployment environment flag `INTEL_PILOT_ALLOW_LIVE=true`, default absent/off.
6. Separate test key(s) in `INTEL_PILOT_NEWSCATCHER_KEY` and, only for optional
   classification, `INTEL_PILOT_ANTHROPIC_KEY`. Standard app/production key names
   are never read; no keys go in a plan, CLI argument, ledger or report.
7. A further `--ack-paid` on each manual collection/classification command.

The initial offline implementation took none of those live enablement actions.
A subsequent, separately approved manual test temporarily enabled only its own
runner process and armed one private ledger; it stopped after the first HTTP 422.
Its temporary credential file was removed and the app settings were unchanged.
Approval gates protect against accidents, not an administrator editing code/SQL.
Do not copy production secrets or treat possessing a plan hash as user approval.

## Frozen comparison plan

Use the existing local compiler preview for each baseline/experimental query,
then import its exact reviewed payloads. `import-preview` retains parameters and
language-lane labels, rejects arbitrary hosts/methods/Enterprise v3, and strips
foreign translation-review/database IDs. It does not reconstruct/activate streams,
retranslate terms or assert that a frozen query still matches a subsequently
edited stream. The operator reviews/approves the complete frozen query itself.

Supported collection endpoints: NewsCatcher Search and Articles, POST only.
Search requires explicit effort, limit and relative search window; nominal cost
is low/medium/high = 1/5/10 credits. Articles requires an absolute timezone-aware
fixed date interval, page 1 and page size; nominal cost is 5 credits. No arbitrary
paging/automatic catch-up or unknown-price v3 is allowed. Subscription/filter
entitlement and actual prices still need separate live-pilot verification.

A comparison pilot contains 2–4 named variants, at most 16 requests per variant. Creation
rejects plans whose complete comparison exceeds the overall collection/HTTP/
nominal-credit allowance. It never drops a variant/part to fit. Expiry must be
within the next 24 hours and cannot be extended in place. Any plan change requires
a new ledger and approval, not edited limits or a silently reused approval.

## Hard allowances and stop

- `max_http_requests`: all reserved provider requests, including token counting.
- `max_collection_requests`: collection attempts across every variant/run.
- `max_nominal_credits`: total nominal collection-credit reservations.
- `max_model_calls`: **both** count-token and inference HTTP calls.
- `max_reserved_model_tokens`: cumulative preflight input + maximum output
  reservations before inference; not exact provider billing.

Before a variant batch, reserve its **whole** allowance in a committed SQLite
transaction, then check live/stop/expiry again before each dispatch. Failed,
unknown-charge, crashed or undispatched reserved requests never refund/reset the
allowance. No automatic retry. An OS file lock prevents concurrent manual runs
of the same ledger and releases on process death. Stop/report remain usable
while a run owns the lock. `stop` is permanent for that ledger; re-arming does
not reset counters or undo stop. A stop/expiry cannot cancel an already dispatched
request; the connect/read timeout is not a guarantee of an exact total duration.

These are per-pilot caps, **not an account-wide/monthly spending cap**. New pilots
must require new approval. Nominal prices and provider token-count estimates do
not guarantee actual billed charges. Use provider-side financial controls and
verify pricing before committing money.

## One-request validation diagnostics

After separate approval, `purpose: diagnostic` permits exactly one variant containing
one low-effort Search request. Its entire HTTP/request/nominal-credit ceilings must
be 1; model-call/token allowances must be 0 and classification must be absent.
Comparison plans still require at least two variants. Diagnostic ledgers use the
same exact-plan approval, live flag, separate-key, expiry, reservation and permanent
stop gates. No second attempt or auto-retry fits their allowance. They do not emit
monthly schedule projections or claim a baseline/experimental comparison.

HTTP failures now retain bounded validation diagnostics: at most 16 KiB of JSON
error body is inspected, and only eight bounded field/type/message records survive.
Raw bodies, `input`, contexts, request headers and credentials are not retained.
Known test-key values/encodings, URLs and long token-like values are scrubbed before
messages are truncated/stored. Invalid/oversized/non-JSON bodies yield no details.
No additional subscription/debugging/provider request is made to obtain errors.
This cannot retroactively recover the error body from the earlier HTTP 422.

To diagnose that failure, retain the failed payload unchanged rather than guessing
which language codes to remove. A provider response can identify the invalid field;
only then propose stream changes and obtain fresh translation review if needed.
The saved stream and previously stopped ledger are never silently modified/rearmed.
These diagnostics were verified offline; no further live request was made while
adding them. Pilot-focused tests: 28 passed, including redaction, retained fields,
strict one-request bounds, no retry and legacy frozen-plan hash compatibility.

## Optional classification sample

Classification is `null`/off by default. When explicitly configured, each command
attempts at most one unique normalized URL shared across variants, under one fixed
model and requirements prompt. It uses only the returned headline/excerpt, not a
publisher fetch. Identical titles at different URLs remain separate reports.

Two calls are reserved first: token counting and inference. Token-count endpoint
billing is unknown, not assumed free; it is included in call allowance, not in the
reported inference-token/USD sample. Verify that endpoint's billing before a live
financial commitment. The counted input plus
`max_output_tokens` must fit the remaining token reservation ceiling before any
inference is sent. Count failures/exhaustion do not create an inference retry.
Full inference reservations survive unknown charges/crashes; that URL is not
automatically reclassified. Missing or excess reported inference usage permanently
stops further pilot calls. The model has no tools or fallback model and must return
a simple relevant/rationale JSON label. Labels are machine judgments, not analyst
precision or proof of relevance. They are not the full production PIR-scoring
pipeline; a later production-model comparison needs explicit equivalent settings.

Optional `classification` fields:

```json
{
  "model": "EXPLICIT-APPROVED-AVAILABLE-MODEL",
  "requirements": "Fixed plain-language requirements for both variants",
  "max_output_tokens": 256,
  "max_article_chars": 2000,
  "input_usd_per_million": null,
  "output_usd_per_million": null
}
```

Model availability/permissions and real token/pricing behaviour have not been
validated live. Token preflight is a provider estimate, not a promise of an exact
billed-token ceiling. Unexpected usage is detected/stopped, not retroactively
prevented. Prices are optional operator declarations, not downloaded quotes.

## Offline use

With the project's Python dependencies installed, from development on a Linux/macOS
runner (the concurrency guard uses Unix `flock`):

```bash
python scripts/pilot.py --help
python scripts/pilot.py example > /path/to/private/simulation-plan.json
# Review/edit the template. It expires one hour after generation.
python scripts/pilot.py init --config /path/to/private/simulation-plan.json
# Returns PILOT_ID and plan hash; remains disarmed and makes zero calls.
python scripts/pilot.py show-plan --pilot PILOT_ID
```

The template is intentionally simulation-only. A fixture response file is a JSON
array of mocked responses, one per planned request, for example:

```json
[{"results":[{"url":"https://example.test/report","title":"Synthetic report","language":"en","summary":"Synthetic evidence"}]}]
```

```bash
python scripts/pilot.py collect --pilot PILOT_ID --variant baseline --fixtures /path/to/fixture.json
python scripts/pilot.py collect --pilot PILOT_ID --variant experimental --fixtures /path/to/other-fixture.json
python scripts/pilot.py report --pilot PILOT_ID
python scripts/pilot.py stop --pilot PILOT_ID
```

Fixtures are allowed only for simulation ledgers. Omitting `--fixtures` cannot
turn a simulation into live mode. To extract a variant from a locally obtained
compiler preview JSON, without invoking a provider:

```bash
python scripts/pilot.py import-preview --name experimental --file /path/to/preview.json
```

`classify-one --fixtures /path/to/responses.json` accepts a token-count response
and then a model response only in a configured simulation pilot. No live command
is needed to test accounting. Do not seed persistent app databases with fixtures.
Keep pilot files/reports private: they contain queries, reporting and requirements.

## Reviewing the collected candidates locally

The pilot database is separate from the application's article feed. To create a
self-contained private review page and spreadsheet annotation file:

```bash
python3 scripts/export_pilot_review.py --pilot PILOT_ID
```

Open `data/pilots/PILOT_ID/articles-review.html` locally in a browser. Candidates
additional to the first/baseline variant appear first, then baseline candidates.
Titles link to original publishers; metadata includes language, publication time,
publisher hostname, finding variant/query lane and a short expandable returned
excerpt. No external assets/scripts/requests load automatically. Following a source
link loads that publisher and may require a subscription. It does not call a model
or NewsCatcher. Use browser Find to search titles; metadata is not verified article
relevance or independent-source corroboration.

The page links to `articles-review.csv`. Add `review_label` and `reviewer_notes` in
a spreadsheet (suggested labels: relevant / partly_relevant / irrelevant / uncertain).
The HTML itself does not save annotations. Spreadsheet formula prefixes are
neutralised, HTML is escaped, unsafe source-link schemes are refused, and a
restrictive CSP prevents embedded scripts/assets. Both files are owner-readable/
writable only; the exporter reads SQLite in read-only mode and refuses to overwrite
existing review files, preserving possible human annotations. Keep these files
private and out of Git. The exporter does not import candidates into the app DB.

Five offline tests cover HTML/CSV safety, groups, immutable source DB and annotation
preservation. A read-only Chromium check verified counts, mobile layout and no
external requests on opening the actual review page. Latest pinned suites after
this addition: **148 backend + 53 frontend = 201 passed**.

## Reading the report

- Returned rows and normalized unique URLs per variant; repeated URL rows, cap
  warnings, publisher/language sets and paired shared/exclusive URLs.
- Matches against explicitly supplied reference URLs. This is URL matching, not
  semantic evidence matching or recall over all news.
- Each reservation and actual dispatch timestamp/status, including unknown/failure/
  incomplete outcomes. Reserved requests are distinguished from dispatched requests.
- Model labels/reasons and provider-reported input/output tokens. Operator-declared
  token prices optionally produce an estimated USD sample cost.
- Per-variant 30-day scheduled request/nominal-credit estimates, with no claim that
  the frozen plan should be scheduled. Retries/manual runs are extra.
- A monthly classification range only when the operator explicitly supplies
  `projected_new_unique_per_poll: [low, high]` and measured inference usage exists.
  This is conditional modelling, not a rate inferred from an overlapping pilot
  sample. No USD range without declared prices; no DKK conversion assumed.

Actual NewsCatcher billing/quota deltas are **null/unknown**: the snapshotted
contract does not provide a verified billing measurement here. Search uses relative
windows and provider ranking, so sequential runs are not identical universes.
Articles fixed windows improve comparability but do not remove indexing delay.
Repeated copies cannot be treated as independent corroboration. Review model
labels manually and agree thresholds before claiming a useful coverage improvement.

## Verification and current limits

Added `backend/app/pilot.py`, `scripts/pilot.py`, `backend/tests/test_pilot.py`;
no app endpoint/model/schema/worker/frontend was changed. Tests use temporary
SQLite ledgers, fake responses, fake key names and blocked network transports.
Fresh pinned-helper result: **138 backend + 53 frontend = 191 passed**. A CLI
simulation template was exercised through a disposable paired-comparison ledger,
coverage/usage report and stop. Import isolation, live gates, request/model/token
caps, crashes, stop/expiry, concurrent-run refusal, malformed responses, shared
classification and unknown-charge accounting were verified without providers.

No pilot credentials configured, live flag enabled, ledger armed, paid request,
production/development app record mutation, migration, worker start, running-app
rebuild, commit or push was performed. This is a first manual toolkit, not a full
live comparison, UI integration, independent-source assessment or measured savings.
