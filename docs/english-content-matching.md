# English keywords across languages — release preview

New UI-created NewsCatcher streams default to:

```json
{
  "endpoint": "articles",
  "content_matching": "english-translated-v1",
  "query_planner_version": "bounded-v1",
  "event_vocabulary_version": "optimized-v1"
}
```

The compiler emits `search_in: ["title_body", "title_body_translated"]` on every
query part. This searches original content (including English articles) and the
English-translated content of other-language articles with a single English
keyword set. Article-language restrictions, native exclusions and geography remain
unchanged. Empty languages means unrestricted; no English language is inserted
into the filter to force a matching mode.

## Preview workflow

In Pre-ingestion, select developments, regions/countries and desired article
languages. Under Reporting languages and content matching, the default is
**English keywords across languages — Articles**. Keyword-translation controls
are hidden and no translation review is required. Preview the actual payloads and
nominal credit estimate, then save paused. Custom keyword text should be English.

Existing saved streams retain **Existing endpoint settings — unchanged** when
opened, previewed or collected. To opt in deliberately, select the English-content
mode, which selects Articles and turns off local-language keyword expansion in
that unsaved form. Inspect endpoint-specific advanced filters and the request/cost
preview before saving. Search-only filters are not automatically converted into
Articles equivalents. Production profiles are not modified by this preview work.

For an alternative local-language keyword workflow, choose Existing endpoint
settings and then opt into the original translation review controls. The two
modes cannot be combined: English translated-content mode does not create
per-language query lanes.

## Safety and limits

- Server rejects the mode with Search or Enterprise v3, with translated keyword
  expansion, with conflicting advanced `search_in`, or with an explicit legacy
  planner. Unknown mode values are rejected, not silently replaced.
- No `include=translation` enrichment is requested, and there are no translation
  model calls. Article classification tokens remain a separate production cost.
- Articles nominally costs **5 NCC per request/page**, even if it returns nothing.
  Existing request/credit ceilings, query splitting and result caps remain.
- Runtime currently fetches one page per part, as before; busy streams can miss
  results. This feature does not introduce automatic pagination or extra calls.
- Regions are still approximate country-name keyword coverage, not verified event
  geography. Correct translation matching does not solve that limitation.

## Evidence and remaining uncertainty

Official Articles documentation defines the translated `search_in` fields:
https://www.newscatcherapi.com/docs/news/filters#only-for-articles

A separately approved live pilot used an English cyber query, German-only language
filter and `title_body_translated`. It returned 111 total hits, with 100 German
articles and 100 English-translated titles on page 1, confirming account access.
Page 2 was rate-limited, and the local-language comparison remains incomplete.
Thus this is a working baseline, not proof of equal recall across all languages or
that native-language queries never add relevant reporting. Optimized v1 remains a
provisional keyword vocabulary without completed holdout validation.

No further paid requests were used to implement this mode. Automated checks use
mocked providers/local preview, assert exact existing-stream request compatibility,
and cover new defaults, explicit opt-in, language preservation, split payloads,
conflict rejection, save/reload and absence of translation-review/model calls.
