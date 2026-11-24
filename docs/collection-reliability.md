# Phase 1: collection reliability (development only)

Status: implemented locally for offline evaluation; not promoted to production.
No live provider calls, automatic translations or larger keyword libraries are
required/enabled by this change.

## Unicode title deduplication

- New fingerprints use Unicode NFKC normalisation and case folding, preserving
  letters, marks and numbers instead of reducing non-Latin headlines to an empty
  ASCII hash. Whitespace/punctuation boundaries are normalised.
- Titles with fewer than eight letters, numeric/punctuation-only titles and a
  small set of generic headlines are not used for title-based deduplication.
  Exact canonical URL matching still applies.
- The 72-hour title-matching window is retained. Exact URLs match older records.
  Identical informative titles still can merge across publishers, as before;
  independent-report-versus-syndication analysis is a later stage, not solved here.
- Legacy `articles.title_hash` values, article IDs, classification and stream
  memberships are preserved. New title fingerprints live in a separate table.
  On an informative-title poll, recent unindexed legacy rows are indexed lazily
  and matched using the Unicode digest, never the unsafe legacy hash alone.
  The first such poll may take extra database time; no model/provider calls are
  involved in indexing. This cannot restore articles previously discarded.

## Attempts, successes and retries

Scheduling state is separate from `SourceProfile.last_run_at`, which is updated
only after every requested query part succeeds. A manual Run now request queues
work without altering the successful timestamp and respects retry cooldowns.

Failures preserve the previous successful window, including the 15-minute overlap.
Before a stream's first success, the first lookback start is pinned across retries
instead of sliding forward during an outage. Existing legacy timestamps are used
as the initial anchor; historical failed timestamps/unknown gaps cannot be
reconstructed automatically and may require a separately approved backfill.

Retries happen on future worker ticks, with 1/2/4/8-minute exponential delay capped
at 60 minutes. Provider `Retry-After` seconds or HTTP dates can extend that delay.
There are no immediate hidden HTTP retries. Pausing a stream stops scheduled work;
repeated failures continue at the bounded cadence while it remains enabled.

If one query part fails, successful earlier parts are stored with a partial-run
record. Later parts are not requested. The next scheduled poll replays the whole
window; URL/title dedupe and stream membership prevent duplicate classification
for articles already stored. The success watermark advances only after full poll
success. This costs additional credits when successful parts are replayed; it is
not a per-part resume protocol.

A successful poll means the requests completed, not that every relevant article
was returned. Result-cap warnings, explicit date/window overrides and recovery
windows shortened by provider history limits are visible. No automatic paging,
extra catch-up calls or poll-frequency increases are introduced here.

## Collection diagnostics

In **Pre-ingestion** or **Settings → Ingest profiles**, expand **Collection
diagnostics** for a saved stream and load its recent polls. This is a read-only
operation and never queues/fetches articles. The same data is available at:

```
GET /api/profiles/{id}/ingest-runs?limit=20
```

The panel records returned/new articles, URL/title duplicates, exclusions, invalid
records, elapsed time, failure codes, request/cap counts and query-revision hashes.
It distinguishes attempts, successful polls and scheduled retries. Per-request
telemetry covers the current NewsCatcher endpoints and Enterprise v3; GDELT and
unmodified adapters do not yet provide per-request instrumentation. Subscription
metadata lookups are not included in article-request counts.

Run/article attribution preserves query-part membership where the adapter
supplies it, without reclassifying overlap. Current classification statuses for
new articles can be inspected later. `enriched` is the classifier's judgement,
not analyst-validated relevance, independent corroboration or ground truth.

Credit figures use nominal pricing assumptions: Search low/medium/high 1/5/10,
Articles 5. They are estimates, not invoices or a hard budget mechanism. Enterprise
pricing and unsuccessful/unknown-charge requests remain unknown (`null`), not
zero. Successful HTTP 200 calls can incur estimated credits even when parsing
fails. Each request retains its own estimate when a whole-poll estimate is unknown.
Provider price changes and account entitlements require separate verification.

Neither query text, raw provider bodies nor API credentials are copied into this
ledger. Errors are stored as codes rather than arbitrary provider/exception text.
The ledger is committed with the poll's stored articles. A process crash or
transaction/storage failure can roll it back, so it is not a durable financial
billing log. Retention/pruning and analyst labels remain future work.

## Schema and release safety

Only new tables are introduced by `init_db()`:

- `article_fingerprints`
- `ingest_states`
- `ingest_runs`
- `ingest_run_articles`

No existing columns or article hashes are rewritten. The existing application can
still read its old tables after a code rollback; reverting to the old code also
restores its known collection limitations. Retain database backups and test
upgrade/rollback before any production release. New audit rows are retained with
a null stream ID if their stream is deleted; source articles are preserved.

## Offline checks

Run `./scripts/development.sh test`, then check the UI in Chrome. Regression tests
cover multiple scripts, canonical Unicode equivalence, weak titles, legacy hash
collisions, the 72-hour window, cross-stream memberships, retries/cooldowns,
partial multi-query failure/replay, malformed responses, credit uncertainty,
query attribution, safe diagnostics rendering and additive schema creation.

Production remains on its separate checkout/containers/database. The development
worker and live credentials remain disabled. Automatic translation is the next
retrieval stage after the query compiler/event-library work is approved.
