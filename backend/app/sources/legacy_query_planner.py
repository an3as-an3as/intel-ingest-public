"""Frozen production query renderer/partitioner from main at 91b68b2.

Used for existing, unversioned streams. Do not reorder, deduplicate or repartition
terms here: Search is semantic and each part has an independent result cap.
Payload construction is shared, but receives this renderer's exact query text.
"""
from .options import COUNTRIES, EVENT_QUERIES
from .newscatcher_filters import mode_for, SCHEMAS
from .base import SourceError


def build_q(params, escape_quotes=False):
    def quote(term):
        if ' ' not in term:
            return term
        return f'\\"{term}\\"' if escape_quotes else f'"{term}"'

    keywords = [k.strip() for k in params.get('keywords', []) if k.strip()]
    if not keywords and not params.get('event_presets') and not params.get('query', '').strip():
        raise SourceError('NewsCatcher stream needs keywords or an event preset (q is required)')
    raw = params.get('query', '').strip()
    kws = [quote(k) for k in keywords] if not raw else []
    groups = [f'({raw})'] if raw else []
    if kws:
        groups.append(kws[0] if len(kws) == 1 else '(' + ' OR '.join(kws) + ')')
    events = [quote(term) for event in params.get('event_presets', []) for term in EVENT_QUERIES[event]]
    if events:
        groups.append('(' + ' OR '.join(events) + ')')
    places = [quote(COUNTRIES[c]) for c in params.get('coverage_countries', [])]
    if places:
        groups.append('(' + ' OR '.join(places) + ')')
    query = ' AND '.join(groups)
    for term in params.get('exclude_keywords', []):
        if term.strip():
            query += f' NOT {quote(term.strip())}'
    return query


def build_requests(params, since, until, *, build_request, api_version=None, plan=None, effort=None):
    mode = mode_for(params, api_version)
    maximum = SCHEMAS[mode]['q'].get('maxLength')
    pending, parts = [params], []
    while pending:
        part = pending.pop(0)
        query = build_q(part, escape_quotes=mode == 'v3')
        if maximum and len(query) > maximum:
            candidates = []
            for key in ('keywords', 'event_presets', 'coverage_countries'):
                values = part.get(key, [])
                if len(values) < 2 or (key == 'keywords' and part.get('query', '').strip()):
                    continue
                terms = ([t for event in values for t in EVENT_QUERIES[event]] if key == 'event_presets'
                         else [COUNTRIES[c] for c in values] if key == 'coverage_countries' else values)
                candidates.append((sum(len(t) + 6 for t in terms), key))
            if candidates:
                _, key = max(candidates)
                values = part[key]
                middle = len(values) // 2
                pending[0:0] = [{**part, key: values[:middle]}, {**part, key: values[middle:]}]
                if len(pending) + len(parts) > 16:
                    raise ValueError('These selections require more than 16 NewsCatcher '
                                     'requests per poll. Narrow the selections or create separate streams.')
                continue
        parts.append(build_request(part, since, until, api_version=api_version, plan=plan,
                                   effort=effort, _query=query))
    return list({body['q']: (mode, body) for mode, body in parts}.values())
