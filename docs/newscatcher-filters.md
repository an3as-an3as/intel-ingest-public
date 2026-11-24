# NewsCatcher pre-ingestion filter coverage

## Official documentation checked

- [News API filters and sorting](https://www.newscatcherapi.com/docs/news/filters)
- [News API OpenAPI contract](https://github.com/NewscatcherAPI/docs/blob/main/api-reference/news-api/openapi.json), version **1.3.9**
- [Enterprise v3 search reference](https://www.newscatcherapi.com/docs/news-api/api-reference/search/search-articles-get), version **3.26.0**
- [Migration / endpoint differences](https://www.newscatcherapi.com/docs/resources/migrate-from-v3)

The app exposes the documented request parameters for the three **article search**
endpoints below. It does not claim to cover other NewsCatcher products/endpoints such
as Agent research, Local News geographic search, or the publisher-discovery endpoint.

## Multiple selections

All pre-ingestion multiple-choice lists show an always-visible search bar above a
scrollable checkbox list (not a collapsed dropdown). Click or tap options to
add/remove choices, without holding Ctrl/Cmd. The summary shows the
selection count and selected names; searching does not clear existing selections.
**Clear selections** removes the restriction. This includes publisher countries,
article languages, event presets, coverage presets, dashboard links and native
multi-value filters.

Country choices are ISO 3166-1; language choices cover ISO 639-1, plus NewsCatcher's
`cn`/`tw` Chinese codes and `zh` alias. They are vocabularies, not a guarantee that
NewsCatcher currently has publishers/articles for every choice. The provider accepts
at most 100 values in country/language filters.

Publisher countries describe **the outlet**, not event location. Event and coverage
presets remain approximate English keyword groups added to the query. They are not
native NewsCatcher event/location categories. Enterprise v3's native `theme` and
entity filters are separate controls.

## News API: `/search` (15 parameters)

| UI control | API parameter |
|---|---|
| Keywords, optional advanced query, event/coverage presets, exclusions | `q` |
| Publisher countries, article languages | `countries`, `languages` |
| Maximum articles per request/page (plan capped) | `limit` |
| Native filter controls | `effort`, `collapse`, `sort_by`, `search_window`, `sources`, `not_sources`, `not_languages`, `not_countries`, `min_newsrooms`, `content_type`, `include` |

Effort is configurable per stream (low/medium/high), falling back to the environment
setting when blank. `include` offers the documented Enterprise response fields:
description, entities, sentiment, themes, translation and embedding. Paid fields may
return 403 without the appropriate plan. Requesting these fields does not replace
the app's Claude classifier or add new dashboard visualisations.

## News API: `/articles` (20 parameters)

Select **Articles — Boolean search & extended filters** to expose this endpoint.

| UI control | API parameter |
|---|---|
| Query builder / advanced query | `q` |
| Publisher countries, article languages | `countries`, `languages` |
| Maximum articles per request/page (plan capped) | `page_size` |
| Native filter controls | `search_in`, `from_date`, `to_date`, `sources`, `not_sources`, `predefined_sources`, `not_languages`, `not_countries`, `sort_by`, `page`, `ranked_only`, `from_rank`, `to_rank`, `word_count_min`, `word_count_max`, `exclude_duplicates` |

Unlike `/search`, this endpoint supports search fields, rank/word-count filters and
an extended archive (subject to plan). `search_in` accepts at most two fields. Country
filters are **ignored by the provider when `sources` is set**. `zh` matches both `cn`
and `tw`; on `/search` it means `cn`. `/search` effort, grouping and newsroom-coverage
controls are not available here and are not forwarded.

## Enterprise v3: `/api/search` (59 parameters)

Shown when the server uses `NEWSCATCHER_API=v3`; current News API endpoint controls
are not mixed with Enterprise v3 controls.

| Group | Parameters |
|---|---|
| Dedicated query, country/language, size controls | `q`, `countries`, `lang`, `page_size` |
| Query fields / translations | `search_in`, `include_translation_fields` |
| Publisher and author selection | `predefined_sources`, `source_groups`, `source_name`, `sources`, `not_sources`, `not_lang`, `not_countries`, `not_author_name` |
| Time and sorting | `from_`, `to_`, `published_date_precision`, `by_parse_date`, `sort_by` |
| Rank and article flags | `ranked_only`, `from_rank`, `to_rank`, `is_headline`, `is_opinion`, `is_paid_content` |
| Links and domain metadata | `parent_url`, `all_links`, `all_domain_links`, `all_links_text`, `additional_domain_info`, `is_news_domain`, `news_domain_type`, `news_type` |
| Word count / page | `word_count_min`, `word_count_max`, `page` |
| Clustering | `clustering_enabled`, `clustering_variable`, `clustering_threshold` |
| NLP and topic | `include_nlp_data`, `has_nlp`, `theme`, `not_theme`, `content_type` |
| Named entities | `ORG_entity_name`, `PER_entity_name`, `LOC_entity_name`, `MISC_entity_name` |
| Sentiment | `title_sentiment_min`, `title_sentiment_max`, `content_sentiment_min`, `content_sentiment_max` |
| Taxonomies | `iptc_tags`, `not_iptc_tags`, `iab_tags`, `not_iab_tags`, `custom_tags` |
| Duplicates and compliance | `exclude_duplicates`, `robots_compliant` |

`clustering_variable` is retained but marked deprecated: the docs say it is ignored
for articles published from 2026-01-01. Boolean controls are tri-state (omitted,
true, false). Known vocabularies use checkbox selectors; domains, source-group slugs,
entity queries and other open-ended values use text inputs rather than invented
option lists. Field help preserves the official descriptions and constraints.

## Scheduling, preview and limits

**Preview query** now shows the full method, endpoint and provider parameters, not
just `q`, plus the number of API requests per poll. It makes no provider call and consumes no search credits; credentials are
never included. Automatic dates shown in a preview are a first-run example.

By default the worker uses the first-run lookback or the previous poll time with an
overlap. The development reliability implementation uses the last successful poll,
not the last failed attempt; see [collection reliability](collection-reliability.md).
A configured `search_window`, `from_date`/`to_date` or `from_`/`to_` overrides
that window. Fixed dates can replay the same historical period on every poll;
deduplication prevents duplicate rows but does not prevent repeated API charges.

NewsCatcher limits `/search` queries to 500 characters and `/articles` queries to
1,000. Long generated OR groups (keywords, event presets, coverage countries) are
automatically partitioned into multiple requests while repeating the AND groups,
exclusions and native filters. No selected presets are silently removed or truncated.
The development compiler also splits individual event presets internally and
supports opt-in, versioned English keyword libraries and lower per-stream request
limits/nominal credit ceilings. Optional [reviewed multilingual expansion](keyword-translation.md)
adds language-specific query lanes; original terms/filters remain and budgets apply
to the combined plan. No translation model is called during collection.
Existing streams default to the frozen original
vocabulary. See [Phase 2 details](event-vocabulary.md).
Arbitrary advanced-query text is never rewritten: an indivisible oversized query
gets a concise error asking you to shorten it. To bound cost, more than 16 query
parts per poll is refused; narrow the selections or create separate streams.

Each part consumes API quota/credits and can return up to the configured article
limit. Combined results are deduplicated. Only **one page per query part** is fetched.
The page selector is explicit, not an automatic pagination loop. Search results can
be truncated or missed on busy streams.
Use narrow queries or shorter polling intervals. Runtime page sizes are capped using
the subscription response (`articles` has its own limits). Provider history,
entitlements, quotas and any constraints not encoded in the published schema are
ultimately enforced by NewsCatcher.

## Implementation and maintenance

- `backend/app/sources/newscatcher_filters.json`: versioned snapshot of official
  request schemas/descriptions, shared by UI metadata and backend validation.
- `backend/app/sources/newscatcher_filters.py`: endpoint restrictions, schema validation,
  include/exclude conflicts, ranges and cross-field checks.
- `backend/app/sources/newscatcher.py`: shared complete request builder for preview
  and ingestion, including array/CSV and boolean encoding for Enterprise v3.
- `frontend/filters.js`: schema-driven controls and checkbox-based multi-selects.

For v3 time fields, two overlapping string `oneOf` branches in the upstream schema
are represented as a single string accepting both documented date and relative
formats. Theme/search-field option lists are taken from the reference prose.
The Articles `search_in` cap is two, as specified in the filter guide (the raw array
schema lists a looser generic cap). On documentation updates, refresh all three
schemas and their versions, compare the parameter inventories, and rerun tests.

Tests cover every snapshotted non-managed parameter being validated and forwarded,
all fields being rendered by the UI, multi-value save/load, full request previews,
endpoint restrictions and false/zero preservation. They use mocked provider calls;
no live plan entitlement is assumed.
