# Phase 2: versioned event vocabularies and bounded query plans

Status: development-only, offline evaluation. No production configuration changes,
provider calls, automatic translations or live workers are enabled by this feature.

## Libraries

`backend/app/sources/event_vocabularies.json` contains two explicit versions:

- **legacy-v1**: the frozen original 16 event presets. Missing version/tier settings
  resolve to this library's original terms. Existing ordinary literal searches
  remain unchanged; there is no automatic upgrade on deployment or preview.
- **expanded-v1**: experimental English vocabulary for the same 16 categories,
  with 343 entries across categories/tiers before cross-category deduplication.
  These are curated search concepts, not provider-native event classifications
  and not empirically validated reporting coverage.

Expanded v1 separates:

1. **Core**: specific phrases/events, selected by default after choosing Expanded.
2. **Indicators**: related signals, enabled explicitly.
3. **Discovery**: broad terms with greater noise risk, enabled explicitly.

Expanded core is intentionally NOT a strict superset of Legacy v1. For example,
`military` is a legacy term but is only in Expanded's discovery tier. Preview
lists every effective event term and additions/removals versus the legacy preset.

Treat published version keys as immutable: add a new version to change accepted
search behaviour rather than editing an existing version in place. A regression
snapshot protects the original legacy dictionary. Article classification's
`other` category is not a meaningful catch-all ingestion preset.

## Try it without collecting articles

1. Open development at http://localhost:8081 → **Pre-ingestion**.
2. Configure a test stream or edit an existing development stream. Production
   profiles are not present unless manually recreated; do not copy private data.
3. Select one or two event types. Change **Event keyword library** to Expanded v1.
4. Choose core and, optionally, indicators/discovery in the searchable checkbox
   list. At least one tier is required. Switching back to Legacy restores its
   supported original tier; changing versions invalidates the visible preview.
5. Set the request limit and optional nominal credit ceiling, then click
   **Preview query**. This uses only the local compiler, with no provider call.
6. Inspect terms, removals, endpoint payloads, request counts, and estimated costs.
7. Save only after review. Experimental saves show a confirmation with request
   and credit estimates; Cancel leaves the stored configuration unchanged.
   Reloading preserves the selected library, tiers and limits.

The development environment still has no live API credentials, no running
collection worker and an internal-only application network. Saving/enabling a
stream does not bypass those safeguards. No sample streams are created by startup.

## Query compiler

Generated keywords, event terms and coverage-country names remain separate OR
lists combined using AND. Exclusions repeat on every query part. To stay under
endpoint limits, the compiler can now split terms inside ONE event preset, not
only split a list of selected event types. Splits are weighted by term length.

The union of emitted queries preserves all combinations across split AND groups.
No term/filter is silently truncated or dropped; native filters, countries,
languages, exclusions and raw advanced text repeat on every part. Inputs are not
mutated. Search uses the documented 500-character maximum; Articles uses 1,000.
Enterprise v3 has no query-length limit encoded in the current provider contract;
its URI/server/plan limits still apply and are not live-verified here.

Advanced query text is kept intact and never split internally. If it cannot fit
with required filters, the compiler reports an actionable error. Keyword/exclusion
lists are literal phrases: do not add quotation marks/backslashes or raw Boolean
expressions there. Use **Advanced query** for custom syntax. Standalone Boolean
words/parenthesised literal terms are quoted safely. Ambiguous formerly accepted
quote/escape syntax now fails clearly rather than corrupting query structure.

Partitioning is a deterministic heuristic, not a globally optimal packing solver;
some large configurations can exceed the request limit even if a different manual
query design would be cheaper. Narrow or restructure the stream instead of
assuming all selected tiers can always fit.

## Budget controls and estimates

Per-stream JSON settings are:

```json
{
  "event_vocabulary_version": "expanded-v1",
  "event_vocabulary_tiers": ["core", "indicators"],
  "max_requests_per_poll": 3,
  "max_credits_per_poll": 5
}
```

The request limit defaults to the existing global maximum of 16; a stream may
choose a lower limit but cannot exceed 16. The credit ceiling is optional and is
checked against nominal estimates after the complete plan is built and before
paid article requests. Save/preview and runtime collection use the same compiler.
The existing free subscription-metadata lookup may precede runtime compilation;
it is not an article search and is not included in estimated paid request counts.
Runtime refusals are recorded with safe codes such as `REQUEST_BUDGET_EXCEEDED`
and `CREDIT_BUDGET_EXCEEDED`, preserving the successful-poll watermark. A locally
rejected plan has zero accepted article requests/estimated article credits; this
is distinct from a failed HTTP call with unknown charges.

Nominal assumptions match Phase 1: Search low/medium/high 1/5/10 credits, Articles
5 per request. Native per-stream effort overrides affect the estimate. Enterprise
credit cost is unknown; setting a nominal credit ceiling there is rejected rather
than pretending the cost is zero. A request-count limit is still available.

Preview shows estimated credits per poll and a 30-day continuous-schedule estimate,
plus request totals. It does not retrieve a live subscription or promise actual
billing. Retry polls, manual runs, extra backfills, pauses and schedule drift are
not included in the 30-day estimate. This is NOT a monthly quota/spend controller,
and does not estimate additional downstream classification costs or publisher
coverage. Free credits apply across the account, not separately per stream.

Larger vocabulary may produce more noise, duplicate results, query parts and
classification costs rather than a better corpus. Relevance and useful reporting
per credit must be measured during the separately approved bounded live pilot.

## Regression checks and next stage

Offline tests cover the frozen baseline, category/tier integrity, opt-in discovery,
single-preset splitting, full filter/term retention, exhaustive Boolean-equivalence
checks over split AND groups, endpoint limits, budgets before paid calls,
unknown-cost handling, raw-query preservation and save/reload/preview behaviour.
Browser checks cover the actual controls and confirmation without seeding records.

Next is automatic country-aware language suggestions and cached, reviewed keyword
translation. That work must use this compiler and its limits, preserve original
terms, reconcile article-language filters and never silently activate translations
on existing production streams.
