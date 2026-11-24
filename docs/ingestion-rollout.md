# Proposed ingestion experiments and rollout gates

Status: staged rollout. [Phase 1 collection reliability](collection-reliability.md),
[Phase 2 versioned vocabulary/compiler](event-vocabulary.md) and
[Phase 3 country-aware translation](keyword-translation.md) are implemented locally
in development for offline evaluation. Stage 4 now has one bounded
[offline catch-up preview](catch-up-preview.md) slice implemented locally; actual
catch-up collection, source diversity and provenance work remain proposals.
Stage 5 now has [offline-capable manual pilot tooling](live-pilot.md), disabled
for live calls by default; no live comparison has been authorised/performed.
Stage 6 remains a proposal.
No production streams have changed and paid provider calls are not
authorised/enabled by this work.

## Principle

Improve relevant, diverse reporting per credit, not gross article volume. Keep
existing streams on their existing query behaviour until an experimental version
is explicitly selected. Record configuration/library versions so comparisons are
reproducible. Develop each change in a separate branch and promote only accepted
features, in dependency order.

## Stage 1 — Baseline and corpus integrity

- Record per-poll/per-query-part outcomes: query revision, returned/new articles,
  duplicates, errors, capped responses, elapsed time and estimated credits.
  Do not call estimated credits actual provider billing.
- Fix Unicode-unsafe title hashing before introducing multilingual retrieval.
  Non-Latin headlines must not collapse into the same empty-title hash.
- Separate last attempted poll from last successful coverage. Test failed and
  partially failed multi-part polls, bounded retries and outage recovery.
- Preserve old rows and memberships. Plan hash-version/backfill changes explicitly;
  a new algorithm cannot restore articles discarded before they were saved.

Gate: multilingual fixtures stay distinct, true duplicate memberships are retained,
failed polls do not silently advance coverage, and existing stream tests still pass.

## Stage 2 — Query compiler and richer event vocabulary

- Add versioned, curated event concepts: core phrases, related indicators and
  optional broad discovery terms. Do not enable every broad term by default.
- Split terms within one event preset as well as lists of presets. Preserve Boolean
  semantics and every selected filter across query parts.
- Show language, query text, part count and estimated credits before activation.
- Enforce endpoint character limits, maximum requests per poll and an approved
  per-stream request budget. Report unsatisfied limits; never silently drop terms.
- Add location/actor/asset aliases, recognising that current country-name keywords
  are not event-location filters. Do not accidentally require country names when
  an approved asset/place alias should be sufficient.

Gate: golden query tests prove the intended AND/OR structure, exclusions, length
limits and full term coverage; oversized configurations fail clearly and safely.

## Stage 3 — Automatic country-aware keyword translation

Automatically propose reporting languages when **coverage countries** change, then
translate the positive search concepts for those languages. Publisher-country
filters are separate and must not drive event geography implicitly.

### Behaviour

1. Use a versioned, curated country-to-reporting-language map. A country may have
   multiple languages; there is no reliable one-country/one-language rule.
2. Always retain the original terms and English event vocabulary. Deduplicate
   languages across selected countries. Offer overrides for additional regional
   or minority-language coverage rather than assuming official languages are
   a complete account of reporting.
3. Reconcile suggestions with article-language filters. If the user selects only
   English articles, warn before expanding to non-English reporting; do not
   silently override that restriction or claim translated terms solve it.
4. Translate concepts/phrases with their event context, not a raw Boolean string.
   Use curated translations first; use a model only for missing vocabulary.
   Preserve operators, numbers, acronyms and proper names. Maintain explicit
   transliteration/place aliases rather than blindly translating named entities.
5. Generate a preview automatically, but require review/apply before a saved stream
   changes its live query. Show source phrase, target language, translations,
   request impact and a way to edit/reject a suggestion.
6. Cache translations by source phrase/language, event context, target language,
   model/prompt version and dictionary version. Translate once when configuration
   changes, not on every poll or for every article. Persist the approved result.
7. Treat exclusions separately: translating an exclusion can suppress valuable
   reporting. Do not add translated negative terms without explicit review.
8. Keep effective searches semantically consistent across languages. Prefer
   language-specific query parts when supported and useful, but avoid unnecessary
   country × language × event combinations. Warn when expansion exceeds budget.
9. If translation fails, retain the current approved configuration. Do not save
   partial/unreviewed expansion or silently claim that translation succeeded.

Example: Finland could suggest Finnish and Swedish alongside retained English;
Denmark could suggest Danish. Russian-language regional coverage remains an
explicit additional choice unless justified by the selected-country mapping.
When no coverage country is selected, do not translate into every world language.

Gate: reviewed synthetic multilingual fixtures, unchanged query logic, retained
proper names, explicit language-filter handling, stable caching, visible costs
and tested failure behaviour. Automatic translation is not proof of good recall;
domain translations must be evaluated against real reporting before promotion.

## Stage 4 — Source diversity and collection completeness

First bounded slice: [offline catch-up preview](catch-up-preview.md), implemented
locally with no transport or state changes. It plans page-1 Articles date windows
from matching poll evidence under a single total budget and explicitly declared,
not live-verified, access limits. This is not collection execution or evidence that
the Stage 4 yield/diversity gate has been met. Remaining work includes:

- Pilot complementary international, local/regional and specialist source lanes,
  plus a small discovery allowance. Avoid permanent hard allowlists or multi-outlet
  requirements that exclude credible early single-source reports.
- Detect result-cap saturation. For Search, evaluate narrower partitions or shorter
  polling; it does not offer arbitrary historical paging. For Articles, evaluate
  bounded date windows and paging only where the subscription permits it.
- Measure indexing delay and schedule budgeted catch-up windows where justified.
- Preserve source provenance and independent reports. Group syndication without
  treating multiple copies of one wire story as independent corroboration.

Gate: improved relevant yield or source diversity without unacceptable noise,
collection gaps, duplicate inflation or credit consumption.

## Stage 5 — Controlled live comparison (separate approval)

A first [manual pilot toolkit](live-pilot.md) is implemented for offline simulation,
with a separate private ledger, immutable-plan approval, reservations and stop/expiry
gates. It is not an executed experiment or a live-enabled development stack.

The current development environment deliberately has no live mode. Before enabling
a separate pilot, agree on test credentials, allowed endpoints, a small credit/token ceiling,
a hard request/call limit, expiry and a stop control. Isolate its database, network
and credentials from production. Do not enable unattended polling initially.

Start with one narrowly scoped stream and manual bounded runs. Compare baseline
and experimental queries within comparable windows, accounting for overlap,
provider ranking/availability and differing query-part counts. Classify unique
articles once under the same PIRs/model/settings, then attribute outcomes to the
queries that found them. Use analyst-reviewed labels as well as classifier scores.

Measure:
- Relevant unique articles per credit and classification cost.
- Precision from reviewed samples; coverage of known relevant reference articles.
  Do not claim a measured recall rate against all news without a complete reference.
- Source/language diversity and independent-versus-syndicated reporting.
- Duplicate rates, cap warnings, errors and coverage recovery.
- Translation usefulness/errors and incremental query/translation cost.

Agree thresholds before running the experiment. Promote a feature only if it
improves the intended metric without breaking safety, quality or budget limits.
A larger corpus can improve downstream recall but also increase classification
costs, and longer query libraries can increase NewsCatcher credits even when
few additional articles are found.

## Stage 6 — Selective production canary

Approve features individually. Deploy additive, backward-compatible code after
backup, leaving new behaviour off by default. Enable it on one selected stream,
monitor quality and costs, then expand only after review. Retain the prior approved
query revision and a tested disable/revert path. Other production streams should
not change merely because an experimental dictionary or translation model changed.
