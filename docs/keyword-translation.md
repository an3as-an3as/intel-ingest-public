# Phase 3: country-aware keyword translation (development only)

Status: implemented for offline evaluation. Production is unchanged. Live model
translation and NewsCatcher collection remain disabled in the development stack.
No sample streams/dashboards/articles are created by this feature.

## What is automatic, and what requires review?

After opting into **Multilingual collection** in a development stream, changing
**coverage countries** automatically suggests reporting languages and prepares
cached/offline translation proposals. Publisher countries do not drive this map.
Finland suggests Finnish and Swedish, Denmark Danish; English/original search
terms and the original query lane are retained separately.

The versioned country map is a practical starting point, not a census, exhaustive
minority-language list, provider-coverage promise or event-geolocation mechanism.
Use manual language overrides where needed. At most eight additional languages
and 400 phrase/language review rows are allowed. Unmapped countries are flagged;
no country selection does not mean translating into every world language.

The offline starter pack contains reviewable suggestions for selected cyber and
infrastructure phrases, legacy military/maritime phrases, Baltic Sea and NATO,
in Danish, Swedish, Finnish, German, Estonian, Latvian, Lithuanian and Russian.
It is NOT a complete dictionary for all event types/languages, nor independently
validated translation quality. Missing phrases remain blank and must be completed
manually or explicitly retained unchanged. No fake "automatic translation" is
invented when a model is unavailable.

Country-name suggestions use the installed pycountry ISO country-name catalogues.
An unchanged country name can be legitimate or a missing catalogue translation;
review it. Inflections, transliterations, domain terminology and the provider's
exact-phrase behaviour still need evaluation against real reporting.

## Try the offline workflow

1. Open http://localhost:8081 → **Pre-ingestion**. Create/configure a paused test
   stream; select a coverage country and an event type.
2. For a complete starter example, use coverage **Denmark**, event **Cyber** with
   Legacy v1 or Expanded v1 core, and optionally keyword **Baltic Sea** or **NATO**.
3. Enable **Multilingual collection**. Suggestions are prepared automatically;
   the refresh button can explicitly create another review.
4. Choose the source language of custom keywords (English by default). Event and
   country presets remain English. This prevents ambiguous words in different
   source languages from sharing the same translation cache entry.
5. If the article-language filter permits English only, the review flags Danish
   as conflicting. Explicitly include Danish using the provided button, broaden
   the filter yourself, or change targets. A positive unrestricted filter stays
   unrestricted. Native language exclusions must be resolved manually.
6. Inspect every row. Edit one to three phrases per row, one per line, or choose
   **Keep original only (intentional)**. Missing rows are never dropped silently.
7. Confirm the review checkbox and select **Approve translations & preview
   requests**. Approval creates a frozen snapshot, not a saved/activated stream.
8. Inspect the full query and nominal credit preview, then Save and confirm the
   experimental configuration. New test streams can remain paused.
9. Reload: the saved approval, language choices and reviewed terms are loaded,
   not regenerated or translated again.

Changing keywords, event vocabulary/tiers, coverage geography, endpoint or
article-language restrictions invalidates the approval. Existing stored stream
configuration remains unchanged until a valid replacement is saved. Approved
snapshots are immutable; editing requires a new review. Drafts expire after one
day; approved snapshots do not expire. Keep the v1 country mapping immutable.
Future mapping versions must retain backward compatibility or explicitly plan
reapproval, never silently change existing approved searches.

## Search semantics and limits

The compiler emits the unchanged original query lane plus language-specific lanes.
Each translated lane retains original keywords/event phrases/country names and
adds approved positive translations/local country aliases to the respective OR
groups. Keyword/event/geography groups remain ANDed. Native filters, publisher
restrictions and original exclusions repeat on every lane. Article-language filters
are scoped to each additional lane; user restrictions/exclusions are never widened
silently. The original lane retains the original language filters too: preserving
English terms does not automatically include English-language reports.

Raw **Advanced query** is deliberately not rewritten: disable multilingual
collection or use the structured keyword/event controls instead. Negative search
terms are not translated automatically. Review local-language exclusions as a
separate deliberate change; avoid losing relevant reporting through overbroad NOTs.

Every lane uses the Phase 2 compiler. Character limits and the global/per-stream
request and nominal credit ceilings apply across the complete plan, not separately
as unlimited allowances per language. Over-budget approval/preview/collection fails
without dropping languages/terms or making paid article requests. Duplicate full
request payloads are removed. Enterprise v3 fetches all emitted language lanes;
its unknown credit pricing remains unknown, not zero. Chinese alias handling is
endpoint-specific (`zh` maps differently on Search/Articles; v3 uses `zh`).

Query request metrics record language lane and approval ID. Cross-lane URL overlap
is deduplicated and attributed to all finding query parts without reclassifying
already stored articles. Expanded collection can still increase article volume,
noise, NewsCatcher credits and downstream classification costs.

## Cache, approval and privacy

Two additive tables store suggestions and review snapshots:

- `keyword_translation_cache`
- `keyword_translation_reviews`

Cache keys include source phrase/language, concept/context, target language, vocabulary,
country-map/pack/prompt versions and translation model. Reused cache entries are
proposals, never implicit approval. Human edits are cached for future review.
Approval is bound to the source terms, geography, targets, endpoint and language
restrictions. Budget/filter changes still pass the compiler before application.
Unknown/stale/client-supplied snapshots cannot bypass approval. Review IDs belong
to their environment's database: promote approved code, then review the target
production stream separately, not by copying development IDs or databases.
Server row locking
prevents concurrent approval/generation from amending an approved snapshot.

These tables contain private user search terms and reviewed translations, not API
keys. Keep database dumps private and out of Git. Suggested words come from local
files/catalogues unless a separately authorised model call is explicitly requested.
Draft/cache retention cleanup is future work; no automatic deletion is performed.

## Optional live model generation: implemented but disabled

The Generate button and backend require BOTH an explicit deployment setting
`KEYWORD_TRANSLATION_ALLOW_LIVE=true` and an Anthropic key. Development Compose
forces the setting false, forces keys empty, and keeps the application on an
internal network. Do not bypass these safeguards to test casually. A bounded live
pilot still requires separate approval, test credentials and an overall allowance.

When authorised later, generation is an explicit user action, never an automatic
consequence of country changes, saving, previewing or polling. It uses
`KEYWORD_TRANSLATION_MODEL` (default Haiku 5.5), independently of classifier/summary
model settings. The SDK has no automatic retries or fallback, a 30-second timeout,
one request per review, at most 40 missing phrase/language rows and a 4,000-output-
token ceiling. Model output must include every requested ID and valid literal
phrases; changed numbers, query syntax and partial/malformed output are rejected.
Names/acronyms need review; original terms are always retained.

The model attempt is reserved/committed before calling the provider. Failures or
unknown charges do not reset the counter or trigger a retry. Candidates remain
unapproved; no partial invalid batch is applied. A draft approved during generation
cannot be overwritten by the returning model response. This is a per-review call
limit, NOT a global monthly token/spend cap; new reviews can make additional calls
when live mode is enabled. Add the overall pilot budget/usage controls before
allowing live testing. Search-credit estimates do not include translation-model
charges. No real model availability/quality/cost has been validated by offline tests.

## API and validation

- `POST /api/ingestion/translation-plans`: cached/offline draft, no provider calls.
- `GET /api/ingestion/translation-plans/{id}`: read-only draft/approval inspection.
- `POST /api/ingestion/translation-plans/{id}/approve`: complete reviewed decisions,
  explicit confirmation, language checks and full query-budget preflight.
- `POST /api/ingestion/translation-plans/{id}/generate`: deployment-gated model call.

Normal profile save/preview and worker polling load matching approved snapshots
from the database. They NEVER call a translation model. Ordinary streams without
`multilingual_enabled` remain on their previous query behaviour.

Tests use synthetic terms, SQLite and mocked providers. Browser checks exercise
country suggestions, language-filter conflicts, approval, cost preview, save/reload,
manual completion and invalidation without collecting real news. PostgreSQL schema
creation is additive; back up development before applying it, and require a
separate production migration/release review before promotion.
