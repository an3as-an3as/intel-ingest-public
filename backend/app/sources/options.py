"""Curated query presets, not provider-native event classifications."""
import pycountry

from ..taxonomy import EVENT_TYPE_LABELS
from .event_vocabulary import LEGACY_QUERIES, catalog
from .regions import REGIONS, REGION_VERSION

# Backward-compatible import used by older code/tests; frozen in legacy-v1.
EVENT_QUERIES = LEGACY_QUERIES
LANGUAGES = {l.alpha_2: l.name for l in sorted(pycountry.languages, key=lambda l: l.name)
             if hasattr(l, 'alpha_2')}
LANGUAGES.update({'cn': 'Chinese (simplified)', 'tw': 'Chinese (traditional)', 'zh': 'Chinese (provider alias)'})
COUNTRIES = {c.alpha_2: c.name for c in sorted(pycountry.countries, key=lambda c: c.name)}


def ingestion_options():
    from .keyword_translation import metadata as translation_metadata
    return {"countries": COUNTRIES, "languages": LANGUAGES,
            "coverage_regions": {k: v['label'] for k, v in REGIONS.items()},
            "coverage_region_version": REGION_VERSION,
            "event_presets": {k: EVENT_TYPE_LABELS[k] for k in EVENT_QUERIES},
            "event_vocabularies": catalog(),
            "keyword_translation": translation_metadata(),
            "query_limits": {"max_requests_per_poll": 16, "default_version": "legacy-v1"},
            "intervals": {5: "Every 5 minutes", 15: "Every 15 minutes", 30: "Every 30 minutes",
                          60: "Hourly", 180: "Every 3 hours", 360: "Every 6 hours", 720: "Every 12 hours", 1440: "Daily"}}
