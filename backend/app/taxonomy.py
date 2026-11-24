"""Fixed vocabularies the classifier maps every article onto, regardless of source."""

EVENT_TYPES = [
    "armed_conflict",
    "military_activity",
    "terrorism",
    "civil_unrest",
    "political",
    "diplomacy",
    "crime",
    "cyber",
    "economic_sanctions",
    "energy",
    "maritime",
    "infrastructure",
    "disaster_environment",
    "health",
    "migration",
    "technology",
    "other",
]

EVENT_TYPE_LABELS = {
    "armed_conflict": "Armed conflict",
    "military_activity": "Military activity / posture",
    "terrorism": "Terrorism / violent extremism",
    "civil_unrest": "Civil unrest / protest",
    "political": "Politics / governance",
    "diplomacy": "Diplomacy / international relations",
    "crime": "Crime / organised crime",
    "cyber": "Cyber",
    "economic_sanctions": "Economy / trade / sanctions",
    "energy": "Energy / resources",
    "maritime": "Maritime / shipping",
    "infrastructure": "Critical infrastructure / transport",
    "disaster_environment": "Disaster / environment",
    "health": "Health / biosecurity",
    "migration": "Migration / displacement",
    "technology": "Technology / science",
    "other": "Other",
}

REGIONS = [
    "northern_europe",
    "western_europe",
    "eastern_europe",
    "southern_europe",
    "russia_central_asia",
    "middle_east",
    "north_africa",
    "sub_saharan_africa",
    "south_asia",
    "east_asia",
    "southeast_asia",
    "oceania",
    "north_america",
    "latin_america",
    "arctic",
    "global",
    "unknown",
]

REGION_LABELS = {r: r.replace("_", " ").title() for r in REGIONS}
REGION_LABELS.update({"russia_central_asia": "Russia & Central Asia", "unknown": "Unknown"})

GEO_PRECISION = ["exact", "city", "region", "country", "none"]
