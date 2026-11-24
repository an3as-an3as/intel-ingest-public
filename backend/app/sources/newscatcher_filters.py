"""Versioned filter contract, snapshotted from the official NewsCatcher OpenAPI.

The JSON snapshot keeps documented fields, help text and constraints together so the
UI and request validation cannot silently diverge. See docs/newscatcher-filters.md.
"""
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from ..config import get_settings
from .options import COUNTRIES, LANGUAGES

CONTRACT = json.loads(Path(__file__).with_suffix('.json').read_text())
SCHEMAS = CONTRACT['modes']
# These have dedicated controls (or are assembled by the query builder).
MANAGED = {'q', 'countries', 'languages', 'lang', 'limit', 'page_size'}


def mode_for(params: dict, api_version: str | None = None) -> str:
    version = api_version or get_settings().newscatcher_api
    mode = params.get('endpoint', 'v3' if version == 'v3' else 'search')
    if mode not in (['v3'] if version == 'v3' else ['search', 'articles']):
        raise ValueError(f"Endpoint {mode!r} is not available with NEWSCATCHER_API={version}")
    return mode


def validate_native_filters(params: dict, api_version: str | None = None) -> dict:
    mode = mode_for(params, api_version)
    filters = params.get('native_filters', {})
    properties = {k: v for k, v in SCHEMAS[mode].items() if k not in MANAGED}
    validator = Draft202012Validator({'type': 'object', 'properties': properties, 'additionalProperties': False})
    errors = list(validator.iter_errors(filters))
    if errors:
        error = errors[0]
        path = '.'.join(map(str, error.path)) or 'native_filters'
        raise ValueError(f"NewsCatcher {path}: {error.message}")
    for key, value in filters.items():
        if isinstance(value, str) and not value.strip():
            raise ValueError(f"NewsCatcher {key}: omit empty values")
        # Enterprise enumerations described in prose, plus enums on array branches
        # of string-or-array fields (the spec also permits comma-separated strings).
        schema = SCHEMAS[mode][key]
        array = next((s for s in schema.get('anyOf', schema.get('oneOf', [])) if s.get('type') == 'array'), None)
        options = schema.get('x-options') or (array or {}).get('items', {}).get('enum')
        values = [v.strip() for v in value.split(',')] if isinstance(value, str) else value
        if options and any(v not in options for v in values):
            raise ValueError(f"NewsCatcher {key}: unknown option")
        if array and len(values) > array.get('maxItems', 100):
            raise ValueError(f'NewsCatcher {key}: too many values')
        if key == 'search_in' and mode == 'v3' and len(value.split(',')) > 2:
            raise ValueError('NewsCatcher search_in accepts at most two fields')
    for key, options in (('not_countries', COUNTRIES), ('not_lang' if mode == 'v3' else 'not_languages', LANGUAGES)):
        values = filters.get(key, [])
        if isinstance(values, str):
            values = [v.strip() for v in values.split(',')]
        if len(values) > 100 or any((v.upper() if key == 'not_countries' else v.lower()) not in options for v in values):
            raise ValueError(f'NewsCatcher {key}: use at most 100 valid two-letter codes')
    if 'search_window' in filters:
        match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(m|min|minute|minutes|h|hr|hour|hours|d|day|days|w|week|weeks)\s*', filters['search_window'], re.I)
        if not match:
            raise ValueError('NewsCatcher search_window: use a duration such as 15m, 2h or 7d')
        unit = match[2].lower()[0]
        if float(match[1]) * {'m': 1, 'h': 60, 'd': 1440, 'w': 10080}[unit] < 1:
            raise ValueError('NewsCatcher search_window must be at least one minute')
    languages_key = 'lang' if mode == 'v3' else 'languages'
    for include, exclude, values in (
        (languages_key, 'not_lang' if mode == 'v3' else 'not_languages', params.get('languages', [])),
        ('countries', 'not_countries', params.get('source_countries', [])),
        ('sources', 'not_sources', filters.get('sources', [])),
    ):
        excluded = filters.get(exclude, [])
        if isinstance(excluded, str):
            excluded = [s.strip() for s in excluded.split(',')]
        if isinstance(values, str):
            values = [s.strip() for s in values.split(',')]
        if set(v.lower() for v in values) & set(v.lower() for v in excluded):
            raise ValueError(f"NewsCatcher {include} and {exclude} overlap")
    for low, high in (('from_rank', 'to_rank'), ('word_count_min', 'word_count_max'),
                      ('title_sentiment_min', 'title_sentiment_max'), ('content_sentiment_min', 'content_sentiment_max')):
        if low in filters and high in filters and filters[low] > filters[high]:
            raise ValueError(f"NewsCatcher {low} must not exceed {high}")
    if mode == 'articles':
        size = min(params.get('max_records', 100), 100)
        if filters.get('page', 1) * size > 1000:
            raise ValueError('NewsCatcher articles page × page size must not exceed 1000')
    return dict(filters)


def filter_metadata():
    version = get_settings().newscatcher_api
    modes = ['v3'] if version == 'v3' else ['search', 'articles']
    return {'api': version, 'modes': {m: SCHEMAS[m] for m in modes},
            'managed': sorted(MANAGED), 'documentation': CONTRACT['documentation'],
            'source_versions': CONTRACT['source_versions']}
