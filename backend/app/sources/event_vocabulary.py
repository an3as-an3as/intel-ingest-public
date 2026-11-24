"""Immutable, explicitly selected English event-query libraries, not classifications."""
import json
from pathlib import Path

LIBRARIES = json.loads(Path(__file__).with_name('event_vocabularies.json').read_text())
DEFAULT_VERSION = 'legacy-v1'
TIER_LABELS = {'core': 'Core — specific event phrases',
               'indicators': 'Indicators — related signals (optional)',
               'discovery': 'Discovery — broad terms, more noise (optional)'}
LEGACY_QUERIES = {event: list(tiers['core']) for event, tiers in LIBRARIES[DEFAULT_VERSION]['events'].items()}


def settings(params):
    version = params.get('event_vocabulary_version', DEFAULT_VERSION)
    if not isinstance(version, str) or version not in LIBRARIES:
        raise ValueError('Unknown event vocabulary version')
    tiers = params.get('event_vocabulary_tiers', ['core'])
    allowed = [tier for tier in TIER_LABELS
               if any(tier in entry for entry in LIBRARIES[version]['events'].values())]
    if not isinstance(tiers, list) or not tiers or any(not isinstance(t, str) or t not in allowed for t in tiers):
        raise ValueError(f'Event vocabulary tiers must be a non-empty list drawn from {allowed}')
    tiers = [t for t in allowed if t in tiers]  # Stable, canonical order, independent of checkbox order.
    events = params.get('event_presets', [])
    if not isinstance(events, list) or any(not isinstance(e, str) or e not in LEGACY_QUERIES for e in events):
        raise ValueError('Unknown event preset')
    return version, tiers


def selected_terms(params):
    version, tiers = settings(params)
    events = LIBRARIES[version]['events']
    return list(dict.fromkeys(term for event in params.get('event_presets', [])
                              for tier in tiers for term in events[event].get(tier, [])))


def summary(params):
    version, tiers = settings(params)
    terms = selected_terms(params)
    legacy = selected_terms({**params, 'event_vocabulary_version': DEFAULT_VERSION, 'event_vocabulary_tiers': ['core']})
    return {'version': version, 'tiers': tiers, 'term_count': len(terms), 'terms': terms,
            'events': {event: selected_terms({**params, 'event_presets': [event]})
                       for event in dict.fromkeys(params.get('event_presets', []))},
            'added_vs_legacy': [t for t in terms if t not in legacy],
            'removed_vs_legacy': [t for t in legacy if t not in terms],
            'language': 'en', 'experimental': version != DEFAULT_VERSION}


def catalog():
    return {key: {'label': library['label'], 'description': library['description'],
                  'tiers': {tier: ('Original terms — unchanged' if key == DEFAULT_VERSION else TIER_LABELS[tier])
                            for tier in TIER_LABELS
                            if any(tier in entry for entry in library['events'].values())}}
            for key, library in LIBRARIES.items()}
