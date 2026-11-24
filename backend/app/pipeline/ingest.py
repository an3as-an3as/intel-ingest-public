"""Collect with Unicode dedupe, successful-poll watermarks and an additive audit ledger."""
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Article, ArticleFingerprint, ArticleProfile, IngestRun, IngestRunArticle, IngestState, SourceProfile
from ..sources import SOURCES, SourceError
from ..sources.base import FetchResult, QueryBudgetError
from ..sources.gdelt import GdeltRateLimited
from .deduplication import VERSION, legacy_title_hash, recent_title_matches, title_hash

log = logging.getLogger(__name__)
_fallback_blocked_until = datetime.min.replace(tzinfo=timezone.utc)
_TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|cmpid)")


def normalize_url(url: str) -> str:
    p = urlsplit(url.strip())
    q = [(k, v) for k, v in parse_qsl(p.query) if not _TRACKING.match(k)]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/') or '/', urlencode(q), ''))


_LANG_ISO = {
    'english': 'en', 'french': 'fr', 'german': 'de', 'spanish': 'es', 'portuguese': 'pt', 'italian': 'it',
    'dutch': 'nl', 'russian': 'ru', 'ukrainian': 'uk', 'polish': 'pl', 'finnish': 'fi', 'swedish': 'sv',
    'norwegian': 'no', 'danish': 'da', 'estonian': 'et', 'latvian': 'lv', 'lithuanian': 'lt', 'arabic': 'ar',
    'persian': 'fa', 'hebrew': 'he', 'turkish': 'tr', 'chinese': 'zh', 'japanese': 'ja', 'korean': 'ko',
    'hindi': 'hi', 'urdu': 'ur', 'indonesian': 'id', 'vietnamese': 'vi', 'thai': 'th', 'greek': 'el',
}
_COUNTRY_ISO = {
    'unitedstates': 'US', 'us': 'US', 'unitedkingdom': 'GB', 'uk': 'GB', 'finland': 'FI', 'sweden': 'SE',
    'norway': 'NO', 'denmark': 'DK', 'iceland': 'IS', 'estonia': 'EE', 'latvia': 'LV', 'lithuania': 'LT',
    'poland': 'PL', 'germany': 'DE', 'france': 'FR', 'netherlands': 'NL', 'belgium': 'BE', 'spain': 'ES',
    'italy': 'IT', 'ukraine': 'UA', 'russia': 'RU', 'belarus': 'BY', 'turkey': 'TR', 'israel': 'IL',
    'egypt': 'EG', 'saudiarabia': 'SA', 'yemen': 'YE', 'iran': 'IR', 'iraq': 'IQ',
    'unitedarabemirates': 'AE', 'syria': 'SY', 'lebanon': 'LB', 'jordan': 'JO', 'qatar': 'QA',
    'india': 'IN', 'pakistan': 'PK', 'china': 'CN', 'japan': 'JP', 'southkorea': 'KR', 'taiwan': 'TW',
    'australia': 'AU', 'canada': 'CA', 'djibouti': 'DJ', 'somalia': 'SO', 'eritrea': 'ER', 'sudan': 'SD',
    'ethiopia': 'ET', 'kenya': 'KE',
}


def to_newscatcher_params(params: dict) -> tuple[dict | None, list[str]]:
    """Translate GDELT filters for fallback; report unsupported restrictions."""
    if not any(k.strip() for k in params.get('keywords', [])):
        return None, []
    dropped = ['themes'] if params.get('themes') else []
    langs, countries = [], []
    for language in params.get('languages', []):
        code = _LANG_ISO.get(language.strip().lower()) or (language.strip().lower() if len(language.strip()) == 2 else None)
        langs.append(code) if code else dropped.append(f'language {language}')
    for country in params.get('source_countries', []):
        key = country.strip().replace(' ', '').lower()
        code = _COUNTRY_ISO.get(key) or (key.upper() if len(key) == 2 else None)
        countries.append(code) if code else dropped.append(f'country {country}')
    return {'keywords': params['keywords'], 'exclude_keywords': params.get('exclude_keywords', []),
            'languages': list(dict.fromkeys(langs)), 'source_countries': list(dict.fromkeys(countries)),
            'max_records': min(int(params.get('max_records', 250)), 250)}, dropped


def next_poll_at(profile: SourceProfile):
    if not profile.enabled:
        return None
    state = profile.ingest_state
    if state and state.retry_at:
        return state.retry_at
    if state and state.run_requested:
        return None
    anchor = state.last_success_at if state else profile.last_run_at
    return anchor + timedelta(minutes=profile.interval_minutes) if anchor else None


def is_due(p: SourceProfile, now: datetime) -> bool:
    due = next_poll_at(p)
    return bool(p.enabled and (due is None or now >= due))


def get_ingest_state(profile, now):
    if profile.ingest_state is None:
        profile.ingest_state = IngestState(
            last_success_at=profile.last_run_at,
            initial_since=now - timedelta(hours=int((profile.params or {}).get('lookback_hours', 24))),
            failures=0, run_requested=False)
    return profile.ingest_state


def request_poll(profile, now):
    # Manual requests change scheduling, never the successful-poll watermark.
    get_ingest_state(profile, now).run_requested = True


def _fetch(db, profile, params, since, now):
    source = SOURCES.get(profile.source)
    if source is None:
        raise SourceError('Unknown source')
    try:
        if profile.source == 'newscatcher' and params.get('multilingual_enabled', False):
            from ..sources.keyword_translation import load_approved
            return source.fetch(params, since, now, translation=load_approved(db, params)), ''
        return source.fetch(params, since, now), ''
    except GdeltRateLimited:
        fb_params, dropped = to_newscatcher_params(params)
        st = get_settings()
        if not (st.gdelt_fallback_to_newscatcher and st.newscatcher_api_key and fb_params):
            raise
        global _fallback_blocked_until
        if now < _fallback_blocked_until:
            raise SourceError('Fallback cooldown', retry_at=_fallback_blocked_until)
        try:
            result = SOURCES['newscatcher'].fetch(fb_params, since, now)
        except Exception:
            _fallback_blocked_until = now + timedelta(minutes=10)
            raise
        return result, ' via NewsCatcher fallback' + (f" (ignored: {', '.join(dropped)})" if dropped else '')


def _store_articles(s, profile, raws, run, now):
    excludes = [x.casefold() for x in (profile.params or {}).get('exclude_keywords', []) if x.strip()]
    candidates = {}
    for raw in raws:
        if not isinstance(raw.url, str) or not isinstance(raw.title, str) or not raw.title.strip():
            run.invalid_articles += 1
            continue
        if any(x in raw.title.casefold() for x in excludes):
            run.excluded_articles += 1
            continue
        try:
            location = urlsplit(raw.url.strip())
            if location.scheme.lower() not in {'http', 'https'} or not location.hostname or location.username or location.password:
                raise ValueError('Invalid article URL')
            url = normalize_url(raw.url)
        except ValueError:
            run.invalid_articles += 1
            continue
        if url in candidates:
            run.duplicate_urls += 1
            parts = candidates[url].extra.setdefault('_query_parts', [])
            parts.extend(p for p in raw.extra.get('_query_parts', []) if p not in parts)
        else:
            candidates[url] = raw
    if not candidates:
        return
    existing = {a.url: a for a in s.scalars(select(Article).where(Article.url.in_(list(candidates))))}
    matches = recent_title_matches(s, [r.title for r in candidates.values()], now)
    for url, raw in candidates.items():
        digest = title_hash(raw.title)
        article = existing.get(url)
        if article:
            run.duplicate_urls += 1
        elif digest and digest in matches:
            article = matches[digest]
            run.duplicate_titles += 1
        new = article is None
        if new:
            article = Article(url=url, title=raw.title[:2000], title_hash=legacy_title_hash(raw.title),
                              description=raw.description, body=raw.body, source_domain=raw.source_domain,
                              source_country=raw.source_country, language=raw.language, image_url=raw.image_url,
                              published_at=min(raw.published_at, now), ingested_at=now, profile_id=profile.id)
            s.add(article)
            s.flush()
            s.add(ArticleFingerprint(article_id=article.id, version=VERSION, digest=digest))
            existing[url] = article
            if digest:
                matches[digest] = article
            run.new_articles += 1
        if not s.get(ArticleProfile, (article.id, profile.id)):
            s.add(ArticleProfile(article_id=article.id, profile_id=profile.id))
        link = s.get(IngestRunArticle, (run.id, article.id))
        parts = raw.extra.get('_query_parts', [])
        if link:
            link.query_parts = sorted(set(link.query_parts or []) | set(parts))
        else:
            s.add(IngestRunArticle(run_id=run.id, article_id=article.id, is_new=new, query_parts=parts))


def run_profile(s: Session, profile: SourceProfile) -> int:
    started = time.monotonic()
    now = datetime.now(timezone.utc)
    params = profile.params or {}
    state = get_ingest_state(profile, now)
    since = state.last_success_at - timedelta(minutes=15) if state.last_success_at else state.initial_since
    state.last_attempt_at = now
    state.run_requested = False
    run = IngestRun(profile_id=profile.id, source=profile.source, started_at=now,
                    window_since=since, window_until=now,
                    config_hash=hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest(),
                    new_articles=0, duplicate_urls=0, duplicate_titles=0,
                    excluded_articles=0, invalid_articles=0)
    s.add(run)
    s.flush()
    failure, via = None, ''
    try:
        raws, via = _fetch(s, profile, params, since, now)
    except Exception as exc:
        failure = exc
        partial = getattr(exc, 'partial', None)
        raws = partial if partial is not None else FetchResult()
    metrics = list(getattr(raws, 'request_metrics', []))
    run.source = getattr(raws, 'provider', None) or ('newscatcher' if via else profile.source)
    run.request_metrics = metrics
    run.planned_requests = getattr(raws, 'planned_requests', None)
    run.returned_articles = sum(m['returned'] for m in metrics) if metrics else len(raws)
    run.duplicate_urls = getattr(raws, 'duplicate_urls', 0)
    run.invalid_articles = getattr(raws, 'invalid_articles', 0)
    costs = [m.get('estimated_credits') for m in metrics]
    run.estimated_credits = sum(costs) if costs and all(c is not None for c in costs) else None
    _store_articles(s, profile, raws, run, now)
    finished = datetime.now(timezone.utc)
    if failure:
        state.failures = (state.failures or 0) + 1
        delay = min(3600, 60 * 2 ** min(state.failures - 1, 6))
        retry = getattr(failure, 'retry_at', None)
        state.retry_at = max(finished + timedelta(seconds=delay), retry) if retry else finished + timedelta(seconds=delay)
        run.status = 'partial' if raws or any(m['status'] == 'success' for m in metrics) else 'error'
        default_code = failure.code if isinstance(failure, QueryBudgetError) else type(failure).__name__
        run.error_code = next((m['error_code'] for m in reversed(metrics) if m.get('error_code')), default_code)[:80]
        if isinstance(failure, QueryBudgetError) and not metrics:
            run.planned_requests = 0  # No executable article-query plan was accepted.
            run.estimated_credits = 0
        profile.last_status = f'{run.status}: {run.error_code}; {run.new_articles} new; retry {state.retry_at:%Y-%m-%d %H:%M:%S} UTC'
    else:
        state.last_success_at = now
        state.retry_at = None
        state.failures = 0
        profile.last_run_at = now
        run.status = 'success'
        capped = sum(bool(m.get('cap_hit')) for m in metrics)
        warning = f'; warning: {capped} response(s) at result cap — coverage may be incomplete' if capped else ''
        profile.last_status = f'ok{via}: {run.returned_articles} fetched, {run.new_articles} new{warning}'
    run.finished_at = finished
    run.duration_ms = max(0, round((time.monotonic() - started) * 1000))
    log.info('profile %s: %s', profile.id, profile.last_status)
    return run.new_articles
