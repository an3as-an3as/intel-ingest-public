# Regional focus and provisional keyword baseline (development only)

Checkpoint before this integration: `280f83a`.

New streams created in Pre-ingestion use `optimized-v1`, with one `core` keyword
list per event category and no tier decision. Existing saved streams keep their
library; select Optimized v1 explicitly to migrate them after previewing.
Legacy v1 and Expanded v1 remain available, unchanged.

All 16 categories have baseline lists. Batch 1 (cyber, armed_conflict, terrorism,
civil_unrest, crime) came from the keyword-automation experiment. It did NOT
complete holdout validation; recorded F2 values are provisional, not evidence of
validated coverage. Other categories use Expanded v1 core + indicators. Further
optimization is deferred until the next credit billing cycle. Do not run paid
collection/optimization as part of this deployment.

## Europe and Asia example

1. Create a paused NewsCatcher stream in Pre-ingestion.
2. In Coverage geography, select **Europe** and **Asia** under Regional focus.
3. In Developments, choose **Armed conflict**.
4. Preview requests and check request/credit ceilings, then save.

Regions expand to a versioned country-code list in `sources/regions.py`.
Explicit additional countries are unioned and deduplicated with regional countries.
Country names form one OR group, ANDed with event terms and any keywords. This is
approximate textual coverage, not event geolocation and not publisher location.
Some reporting omits country names and will be missed. Large selections can split
into multiple paid requests or exceed existing budgets; no terms are truncated.

The six practical regions are Europe, Asia, Africa, North America (including
Central America and Caribbean), South America and Oceania. Russia is assigned to
Europe; Turkey, Cyprus and the Caucasus to Asia. These are practical groupings,
not a claim about disputed borders. Antarctica is not included. Region-version
changes must not silently alter saved streams.

Region countries also feed translation proposals and approval fingerprints.
Existing safety limits (eight extra languages and 400 review rows per stream)
remain: a large region may need a smaller manual translation-language selection.
This does NOT yet provide the planned pretranslated packs for all 58 mapped
language codes (English plus 57 targets). That is the next task; reusable packs
must be generated/reviewed once, versioned with the English lists, and never
require translation API calls on each poll. Missing translations must be explicit.

Production configuration, credentials, ingestion workers and data remain unchanged.
