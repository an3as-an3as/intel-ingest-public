# Cyber keyword relevance review — offline preparation

The agreed starting reference is frozen `legacy-v1` Cyber core:
`cyberattack`, `ransomware`, `data breach`. No published vocabulary was edited.

`scripts/prepare_keyword_review.py` prepares a private human-review package from
an existing pilot plus an offline compiler preview of a category-only baseline:

```bash
python3 scripts/prepare_keyword_review.py --pilot PILOT_ID --profile-id PROFILE_ID --category cyber --sample-size 100
```

This first workflow supports Cyber only. It reads the pilot DB read-only, checks
that localhost:8081 is offline development and the chosen Search stream is paused,
and calls only the local preview compiler. It creates no provider/model calls,
app records, stream edits, translation approvals or live ledger. It refuses to
overwrite an existing package. Files are private under the source pilot folder.

The prepared package contains:

- `review-sample.html` / `.csv`: the master 100-candidate reading/annotation set.
- `legacy-metadata-review.html` / `.csv`: the 27-report literal-metadata subset,
  not another set to label twice. IDs/URLs support merging prior labels.
- `README.md`: relevance rubric, provenance and sampling cautions.
- `manifest.json`: source, seed, strata/population/sample sizes and weights.
- `legacy-baseline-preview.json`: an offline proposed one-request baseline.

The actual preparation used 236 existing Expanded-search URL candidates: all 27
literal Legacy hits in returned title/excerpt metadata and 73 controls balanced
across language/pilot-cohort strata. It leaves 136 URLs unselected, not guaranteed
unseen. English provider summaries can contain a phrase absent from original
local-language text. A literal metadata hit does not establish provider retrieval
attribution or a full-text match; missing metadata hits do not prove irrelevance.
This package is NOT a newly collected Legacy-only corpus.

Human labels are deliberately blank. Label `cyber_relevance` as direct / context /
irrelevant / uncertain and `geography_relevance` separately as dk_no_se_related /
outside / unclear. Add `reason_code`, `evidence_basis` and `reviewer_notes` as useful.
Use original sources where needed; inability to access a source is uncertainty,
not negative relevance. The HTML does not save annotations; CSV is the master.

Sampling is deterministic with a fixed seed and retains every literal hit. It is
enriched, not simple-random sampling: do not interpret unweighted labels as corpus
precision. Weights apply only to the already-returned, capped pilot corpus, never
to recall over all news. Analyse topic, geography and language independently.
Do not claim individual-term causation from query-part attribution or metadata
occurrence. Candidate term removals need positive examples they might lose,
prospective freezing and fresh/held-out validation before adoption.

The proposed category-only baseline removes custom keyword/advanced-query groups,
selects only frozen Cyber core, disables multilingual expansion, preserves the
other geography/language/native/exclusion controls and uses the verified 50-row
account cap. Changes are documented in the private manifest, NOT saved to the
stream. Local compilation produced one low-effort Search request / one nominal
credit; no paid test is authorised or executed by this preparation. Further
collection/classification requires a separate bounded approval. A refined library
must be a new explicit experimental version, not an edit to frozen Legacy/Expanded.

Verification: four new offline tests cover metadata screening, deterministic
stratification, sampling bounds, source/annotation preservation and local-only
preview integration. Pinned suites passed **152 backend + 53 frontend = 205**.
Read-only Chromium checks verified the 100/27 reading sets, mobile layout, blank
labels and zero external requests on opening. No running services were rebuilt,
no commits/pushes were made, and no persistent app data was modified.
