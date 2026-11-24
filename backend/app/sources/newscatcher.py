"""NewsCatcher adapter. Requires NEWSCATCHER_API_KEY.

NewsCatcher runs two different News APIs; NEWSCATCHER_API picks one:

* "news" (default): the current API, with keys from platform.newscatcherapi.com.
  POST https://api.newscatcherapi.com/news-api/search, header x-api-key.
  Body: q, effort, limit, collapse, sort_by, search_window (relative, e.g. "90m"),
  languages, countries (ISO codes), ... There is no pagination: you get the best `limit`
  results. The plan cap comes from GET /news-api/subscription (free to call).
* "v3": the older Enterprise v3 API. GET https://v3-api.newscatcherapi.com/api/search,
  header x-api-token.
"""

import hashlib
import json
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests
from dateutil import parser as dtparser

from ..config import get_settings
from .base import FetchResult, NewsSource, QueryBudgetError, RawArticle, SourceError
from .options import COUNTRIES
from .event_vocabulary import selected_terms, settings as vocabulary_settings
from .regions import coverage_countries
from . import legacy_query_planner
from .content_matching import settings as content_matching_settings
from .keyword_translation import ApprovedTranslation, basis_hash as translation_basis_hash
from .newscatcher_filters import mode_for, validate_native_filters, SCHEMAS
from jsonschema import Draft202012Validator

NEWS_API = "https://api.newscatcherapi.com/news-api"
V3_API = "https://v3-api.newscatcherapi.com/api/search"

_lock = threading.Lock()
_last_call = 0.0
_MIN_INTERVAL = 1.1  # plans allow ~1 request/second
_plan: dict | None = None  # cached GET /subscription


def _keywords(params: dict) -> list[str]:
    kws = [k.strip() for k in params.get("keywords", []) if k.strip()]
    if not kws and not params.get("event_presets") and not params.get("query", "").strip():
        raise SourceError("NewsCatcher stream needs keywords or an event preset (q is required)")
    return kws


def _query_groups(params):
    return [list(dict.fromkeys(_keywords(params))) if not params.get('query', '').strip() else [],
            selected_terms(params),
            list(dict.fromkeys(COUNTRIES[c] for c in coverage_countries(params)))]


def _render_query(params, query_groups, escape_quotes=False):
    def quote(t: str) -> str:
        if '"' in t or '\\' in t:
            raise ValueError('Keyword/exclusion lists contain literal phrases, without quotation marks or backslashes. '
                             'Use Advanced query for custom Boolean/escaped syntax.')
        if not any(c.isspace() or c in '()' for c in t) and t not in {'AND', 'OR', 'NOT'}:
            return t
        return f'\\"{t}\\"' if escape_quotes else f'"{t}"'

    raw_query = params.get("query", "").strip()
    kws = [quote(k) for k in query_groups[0]] if not raw_query else []
    groups = [f"({raw_query})"] if raw_query else []
    if kws:
        groups.append(kws[0] if len(kws) == 1 else "(" + " OR ".join(kws) + ")")
    events = [quote(term) for term in query_groups[1]]
    if events:
        groups.append("(" + " OR ".join(events) + ")")
    places = [quote(term) for term in query_groups[2]]
    if places:
        groups.append("(" + " OR ".join(places) + ")")
    q = " AND ".join(groups)
    for x in params.get("exclude_keywords", []):
        if x.strip():
            q += f" NOT {quote(x.strip())}"
    return q


def query_planner_version(params):
    vocabulary_settings(params)
    matching, _ = content_matching_settings(params, params.get('endpoint', 'search'))
    enhanced = (params.get('event_vocabulary_version', 'legacy-v1') != 'legacy-v1'
                or bool(params.get('coverage_regions')) or bool(params.get('multilingual_enabled'))
                or matching == 'english-translated-v1')
    version = params.get('query_planner_version', 'bounded-v1' if enhanced else 'legacy-v1')
    if not isinstance(version, str) or version not in {'legacy-v1', 'bounded-v1'}:
        raise ValueError('Unknown query planner version')
    if version == 'legacy-v1' and enhanced:
        raise ValueError('Enhanced matching, regions, new vocabularies and translations require the bounded-v1 planner; preview and opt in explicitly')
    return version


def build_q(params: dict, escape_quotes: bool = False) -> str:
    if query_planner_version(params) == 'legacy-v1':
        return legacy_query_planner.build_q(params, escape_quotes)
    return _render_query(params, _query_groups(params), escape_quotes)


def _parse_dt(s, default: datetime) -> datetime:
    try:
        d = dtparser.parse(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return default


def _throttle():
    global _last_call
    wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def build_request(params: dict, since: datetime, until: datetime, *, api_version=None, plan=None, effort=None, _groups=None, _query=None):
    """Build the complete provider payload for previews and real requests alike."""
    mode = mode_for(params, api_version)
    filters = validate_native_filters(params, api_version)
    _, matching_fields = content_matching_settings(params, mode)
    query = (_query if _query is not None else
             build_q(params, mode == 'v3') if _groups is None else _render_query(params, _groups, mode == 'v3'))
    error = next(Draft202012Validator(SCHEMAS[mode]['q']).iter_errors(query), None)
    if error:
        if error.validator == 'maxLength':
            raise ValueError(f"NewsCatcher query is {len(query)} characters; {mode} allows {error.validator_value}. "
                             "Shorten the advanced query or exclusions, or use fewer presets.")
        raise ValueError(f"NewsCatcher query: {error.message}")
    plan = plan or {}
    if mode == 'v3':
        body = {'q': query, 'from_': since.strftime('%Y-%m-%dT%H:%M:%S'),
                'to_': until.strftime('%Y-%m-%dT%H:%M:%S'), 'sort_by': 'date', 'page': 1,
                'page_size': min(int(params.get('max_records', 100)), 1000)}
        if params.get('themes'):
            body['theme'] = ','.join(params['themes'])
    elif mode == 'articles':
        access = plan.get('articles') or {}
        cap = int(access.get('max_articles_per_page') or 100)
        body = {'q': query, 'from_date': since.isoformat(), 'to_date': until.isoformat(),
                'sort_by': 'published_at', 'page': 1,
                'page_size': max(1, min(int(params.get('max_records', cap)), cap, 100))}
    else:
        cap = int(plan.get('max_articles_per_page') or 20)
        max_minutes = int(plan.get('historical_days') or 30) * 1440
        minutes = min(max(1, math.ceil((until - since).total_seconds() / 60)), max_minutes)
        body = {'q': query, 'effort': effort or get_settings().newscatcher_effort,
                'limit': max(1, min(int(params.get('max_records', cap)), cap, 100)),
                'sort_by': 'published_at', 'search_window': f'{minutes}m', 'content_type': 'news'}
    if params.get('languages'):
        body['lang' if mode == 'v3' else 'languages'] = [l.strip().lower() for l in params['languages']]
    if params.get('source_countries'):
        body['countries'] = [c.strip().upper() for c in params['source_countries']]
    body.update(filters)
    if matching_fields is not None:
        body['search_in'] = matching_fields
    if mode == 'v3':
        body = {k: ','.join(v) if isinstance(v, list) else str(v).lower() if isinstance(v, bool) else v
                for k, v in body.items()}
    return mode, body


MAX_REQUESTS_PER_POLL = 16


def query_budget(params):
    maximum = params.get('max_requests_per_poll', MAX_REQUESTS_PER_POLL)
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= MAX_REQUESTS_PER_POLL:
        raise ValueError(f'max_requests_per_poll must be an integer from 1 to {MAX_REQUESTS_PER_POLL}')
    credits = params.get('max_credits_per_poll')
    if credits is not None and (isinstance(credits, bool) or not isinstance(credits, int) or not 1 <= credits <= 10000):
        raise ValueError('max_credits_per_poll must be a positive integer up to 10000, or omitted')
    return maximum, credits


def request_credit_estimate(mode, body):
    # Nominal published assumptions, not a subscription lookup or billing guarantee.
    if mode == 'articles':
        return 5
    if mode == 'search':
        return {'low': 1, 'medium': 5, 'high': 10}.get(body.get('effort', 'low'))
    return None


def _build_single_lane(params: dict, since: datetime, until: datetime, *, api_version=None, plan=None, effort=None, initial_groups=None):
    """Partition literal OR lists, including terms inside a single preset.

    The union of emitted queries retains the original Boolean scope. Raw advanced
    text and exclusions are immutable, and native filters repeat on every part.
    Validate the entire plan/budget before any paid article request is sent.
    """
    mode = mode_for(params, api_version)
    maximum = SCHEMAS[mode]['q'].get('maxLength')
    request_limit, credit_limit = query_budget(params)
    pending = [_query_groups(params) if initial_groups is None else initial_groups]
    parts = []
    while pending:
        groups = pending.pop(0)
        query = _render_query(params, groups, mode == 'v3')
        if maximum and len(query) > maximum:
            candidates = [(sum(len(term) + 6 for term in terms), index)
                          for index, terms in enumerate(groups) if len(terms) > 1]
            if candidates:
                _, index = max(candidates)
                values = groups[index]
                weights = [len(term) + 6 for term in values]
                total, prefix = sum(weights), 0
                choices = []
                for middle in range(1, len(values)):
                    prefix += weights[middle - 1]
                    choices.append((abs(total - 2 * prefix), middle))
                _, middle = min(choices)
                left, right = list(groups), list(groups)
                left[index], right[index] = values[:middle], values[middle:]
                pending[0:0] = [left, right]
                if len(pending) + len(parts) > request_limit:
                    advice = (f'You may raise this stream’s ceiling up to {MAX_REQUESTS_PER_POLL}, or narrow the selections.'
                              if request_limit < MAX_REQUESTS_PER_POLL else
                              'The global ceiling is already reached; narrow geography/events or split them into separate streams.')
                    raise QueryBudgetError(f'These selections require more than {request_limit} NewsCatcher requests per poll. '
                                           + advice, 'REQUEST_BUDGET_EXCEEDED')
                continue
            # Indivisible raw text/exclusions/terms are rejected, never truncated.
        parts.append(build_request(params, since, until, api_version=api_version, plan=plan, effort=effort, _groups=groups))
    parts = list({body['q']: (m, body) for m, body in parts}.values())
    costs = [request_credit_estimate(m, body) for m, body in parts]
    if credit_limit is not None:
        if any(cost is None for cost in costs):
            raise QueryBudgetError('Cannot enforce a nominal credit ceiling for this endpoint: credit estimate unavailable. Use a request limit.', 'CREDIT_ESTIMATE_UNAVAILABLE')
        if sum(costs) > credit_limit:
            raise QueryBudgetError(f'Query plan estimates {sum(costs)} credits per poll, exceeding max_credits_per_poll={credit_limit}. '
                                   'Reduce terms/effort or explicitly raise the nominal credit ceiling.', 'CREDIT_BUDGET_EXCEEDED')
    return parts


class QueryPlan(list):
    def __init__(self, parts=(), *, lanes=None, review_id=None):
        super().__init__(parts)
        self.lanes = list(lanes) if lanes is not None else ['original'] * len(self)
        self.review_id = review_id


def build_requests(params: dict, since: datetime, until: datetime, *, api_version=None, plan=None, effort=None, translation=None):
    if query_planner_version(params) == 'legacy-v1':
        parts = legacy_query_planner.build_requests(params, since, until, build_request=build_request,
                                                   api_version=api_version, plan=plan, effort=effort)
        limit, credit_limit = query_budget(params)
        if len(parts) > limit:
            raise QueryBudgetError('Legacy plan exceeds configured request ceiling', 'REQUEST_BUDGET_EXCEEDED')
        costs = [request_credit_estimate(mode, body) for mode, body in parts]
        if credit_limit is not None:
            if any(cost is None for cost in costs):
                raise QueryBudgetError('Endpoint credit estimate unavailable', 'CREDIT_ESTIMATE_UNAVAILABLE')
            if sum(costs) > credit_limit:
                raise QueryBudgetError('Legacy plan exceeds configured credit ceiling', 'CREDIT_BUDGET_EXCEEDED')
        return QueryPlan(parts)
    if not params.get('multilingual_enabled', False):
        return QueryPlan(_build_single_lane(params, since, until, api_version=api_version, plan=plan, effort=effort))
    if not isinstance(translation, ApprovedTranslation) or translation.basis_hash != translation_basis_hash(params):
        raise ValueError('A matching approved translation snapshot is required; drafts/client-supplied terms cannot be collected')
    limit, credit_limit = query_budget(params)
    lanes = [('original', params, None)] + [(language, {**params, 'languages': [language]}, translation.groups[language])
                                          for language in translation.languages]
    result = QueryPlan(review_id=translation.review_id)
    seen = set()
    for language, lane_params, groups in lanes:
        parts = _build_single_lane(lane_params, since, until, api_version=api_version, plan=plan, effort=effort, initial_groups=groups)
        for mode, body in parts:
            key = mode, json.dumps(body, sort_keys=True)
            if key not in seen:
                seen.add(key)
                result.append((mode, body))
                result.lanes.append(language)
        if len(result) > limit:
            raise QueryBudgetError(f'Multilingual collection exceeds {limit} requests per poll. Reduce translation targets or '
                                   f'geography/events, or split them into separate streams. The global ceiling is {MAX_REQUESTS_PER_POLL}.', 'REQUEST_BUDGET_EXCEEDED')
    costs = [request_credit_estimate(mode, body) for mode, body in result]
    if credit_limit is not None:
        if any(cost is None for cost in costs):
            raise QueryBudgetError('Multilingual endpoint credit estimate unavailable; use a request limit instead.', 'CREDIT_ESTIMATE_UNAVAILABLE')
        if sum(costs) > credit_limit:
            raise QueryBudgetError(f'Multilingual plan estimates {sum(costs)} credits per poll, above the configured ceiling.', 'CREDIT_BUDGET_EXCEEDED')
    return result


def _retry_at(response):
    value = str((getattr(response, 'headers', None) or {}).get('Retry-After', '')).strip()
    try:
        return datetime.now(timezone.utc) + timedelta(seconds=max(0, int(value)))
    except (ValueError, OverflowError):
        try:
            date = parsedate_to_datetime(value)
            return date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date
        except (TypeError, ValueError, OverflowError):
            return None


def _fetch_part(result, mode, body, key, *, window_overridden=False, history_clamped=False, language='original', review_id=None):
    """One HTTP attempt: no hidden paid retries; preserve earlier successful parts."""
    start = time.monotonic()
    revision = {k: v for k, v in body.items() if k not in {'search_window', 'from_date', 'to_date', 'from_', 'to_'}}
    metric = {'part': len(result.request_metrics) + 1, 'endpoint': mode,
              'query_hash': hashlib.sha256(json.dumps(revision, sort_keys=True).encode()).hexdigest(),
              'limit': int(body.get('limit', body.get('page_size', 0))),
              'returned': 0, 'cap_hit': False, 'status': 'error', 'estimated_credits': None,
              'window_overridden': window_overridden, 'history_clamped': history_clamped,
              'translation_language': language, 'translation_review_id': review_id,
              'time_parameters': {k: v for k, v in body.items() if k in {'search_window', 'from_date', 'to_date', 'from_', 'to_'}}}
    result.request_metrics.append(metric)
    response = None
    try:
        _throttle()
        if mode == 'v3':
            response = requests.get(V3_API, params=body, headers={'x-api-token': key}, timeout=60)
        else:
            response = requests.post(f'{NEWS_API}/{mode}', json=body, headers={'x-api-key': key}, timeout=60)
        metric['http_status'] = response.status_code
        if response.status_code != 200:
            raise SourceError(f'HTTP_{response.status_code}')
        # Nominal published prices, not invoices; failed/unknown-charge calls stay null.
        metric['estimated_credits'] = request_credit_estimate(mode, body)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError('Invalid response object')
        if mode == 'v3':
            rows = payload.get('articles')
            if not rows and isinstance(payload.get('clusters'), list):
                rows = [a for cluster in payload['clusters'] for a in cluster.get('articles', [])]
        else:
            rows = payload.get('results')
        if not isinstance(rows, list):
            raise ValueError('Missing article list')
        metric.update(returned=len(rows), cap_hit=bool(metric['limit'] and len(rows) >= metric['limit']), status='success')
        return rows
    except Exception as exc:
        code = f'HTTP_{response.status_code}' if response is not None and response.status_code != 200 else type(exc).__name__
        metric['error_code'] = code
        raise SourceError(f'NewsCatcher request failed ({code})', partial=result,
                          retry_at=_retry_at(response) if response is not None else None) from exc
    finally:
        metric['duration_ms'] = max(0, round((time.monotonic() - start) * 1000))


def _append_articles(result, rows, until, *, legacy=False):
    seen = {a.url: a for a in result}
    for a in rows:
        url_key = 'link' if legacy else 'url'
        if (not isinstance(a, dict) or not isinstance(a.get(url_key), str) or not a[url_key].strip()
                or not isinstance(a.get('title'), str) or not a['title'].strip()):
            result.invalid_articles += 1
            continue
        if a[url_key] in seen:
            result.duplicate_urls += 1
            parts = seen[a[url_key]].extra['_query_parts']
            if len(result.request_metrics) not in parts:
                parts.append(len(result.request_metrics))
            continue
        source = a.get('source') if isinstance(a.get('source'), dict) else {}
        result.append(RawArticle(
            url=a[url_key], title=a['title'].strip(),
            published_at=_parse_dt(a.get('published_date' if legacy else 'published_at'), until),
            description=a.get('description') if legacy else a.get('summary_en') or a.get('summary') or a.get('snippet'),
            body=a.get('content') if legacy else None,
            source_domain=a.get('domain_url') if legacy else source.get('domain'),
            source_country=a.get('country'), language=a.get('language'),
            image_url=a.get('media' if legacy else 'image_url'),
            extra={'_query_parts': [len(result.request_metrics)],
                   **({} if legacy else {'title_en': a.get('title_en'), 'story': a.get('story')})},
        ))
        seen[a[url_key]] = result[-1]


class NewsCatcherSource(NewsSource):
    name = "newscatcher"

    def fetch(self, params: dict, since: datetime, until: datetime, *, translation=None) -> list[RawArticle]:
        st = get_settings()
        if not st.newscatcher_api_key:
            raise SourceError("NEWSCATCHER_API_KEY is not set")
        if params.get('multilingual_enabled', False) and (not isinstance(translation, ApprovedTranslation)
                or translation.basis_hash != translation_basis_hash(params)):
            raise ValueError('A matching approved translation snapshot is required before provider access')
        with _lock:
            if st.newscatcher_api == "v3":
                return self._fetch_v3(st.newscatcher_api_key, params, since, until, translation=translation)
            return self._fetch_news(st, params, since, until, translation=translation)

    # ---- current News API ----
    def _plan(self, key: str) -> dict:
        global _plan
        if _plan is None:
            try:
                _throttle()
                r = requests.get(f"{NEWS_API}/subscription", headers={"x-api-key": key}, timeout=30)
                _plan = r.json() if r.status_code == 200 else {}
            except (requests.RequestException, ValueError):
                _plan = {}
        return _plan

    def _fetch_news(self, st, params: dict, since: datetime, until: datetime, *, translation=None) -> list[RawArticle]:
        key = st.newscatcher_api_key
        plan = self._plan(key)
        batches = build_requests(params, since, until, api_version='news', plan=plan, effort=st.newscatcher_effort, translation=translation)
        out = FetchResult(provider='newscatcher', planned_requests=len(batches))
        native = params.get('native_filters', {})
        overridden = bool(set(native) & {'search_window', 'from_date', 'to_date', 'from_', 'to_'})
        requested_minutes = max(1, math.ceil((until - since).total_seconds() / 60))
        for index, (mode, body) in enumerate(batches):
            clamped = (mode == 'search' and not overridden and str(body.get('search_window', '')).endswith('m')
                       and int(body['search_window'][:-1]) < requested_minutes)
            rows = _fetch_part(out, mode, body, key, window_overridden=overridden, history_clamped=clamped,
                               language=getattr(batches, 'lanes', ['original'] * len(batches))[index],
                               review_id=getattr(batches, 'review_id', None))
            _append_articles(out, rows, until)
        return out

    # ---- legacy v3 (Enterprise) ----
    def _fetch_v3(self, key: str, params: dict, since: datetime, until: datetime, *, translation=None) -> list[RawArticle]:
        batches = build_requests(params, since, until, api_version='v3', translation=translation)
        out = FetchResult(provider='newscatcher', planned_requests=len(batches))
        overridden = bool(set(params.get('native_filters', {})) & {'from_', 'to_'})
        for index, (_, req) in enumerate(batches):
            rows = _fetch_part(out, 'v3', req, key, window_overridden=overridden,
                               language=batches.lanes[index], review_id=batches.review_id)
            _append_articles(out, rows, until, legacy=True)
        return out
