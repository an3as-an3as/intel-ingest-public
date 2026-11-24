"""GDELT DOC 2.0 API adapter (free, no key, global coverage, ~15-min latency).

Docs: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
Returns article metadata only (title, url, domain, language, source country) - the
pipeline fetches body text separately.
"""

import re
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

from .base import NewsSource, RawArticle, SourceError

API = "https://api.gdeltproject.org/api/v2/doc/doc"
_MIN_INTERVAL = 10.0  # GDELT asks for at most one request every 5 seconds; stay well under
_lock = threading.Lock()
_last_call = 0.0

# Shared cooldown after a 429. Retrying while throttled extends GDELT's block, so all
# GDELT profiles pause together and the pause grows on repeated 429s (5 -> 10 -> 20 -> 60 min).
_COOLDOWNS = [300, 600, 1200, 3600]
_strikes = 0
_blocked_until = 0.0  # time.time()


class GdeltRateLimited(SourceError):
    def __init__(self, retry_at: datetime):
        self.retry_at = retry_at
        super().__init__(f"GDELT is rate-limiting this IP; pausing GDELT until {retry_at:%H:%M} UTC")


def _retry_at() -> datetime:
    return datetime.fromtimestamp(_blocked_until, tz=timezone.utc)


def _term(t: str) -> str:
    t = t.strip()
    return f'"{t}"' if " " in t and not t.startswith('"') else t


def _group(terms: list[str]) -> str | None:
    terms = [t for t in terms if t]
    if not terms:
        return None
    return terms[0] if len(terms) == 1 else "(" + " OR ".join(terms) + ")"


def build_query(params: dict) -> str:
    """(keywords) AND/OR (themes), AND geography, AND language, minus exclusions.

    params.combine = "and" (default) requires both a keyword and a theme hit when both are
    given; "or" accepts either.
    """
    kw = [_term(k) for k in params.get("keywords", []) if k.strip()]
    th = [f"theme:{t.strip().upper()}" for t in params.get("themes", []) if t.strip()]
    if params.get("combine", "and") == "or":
        topical = [_group(kw + th)]
    else:
        topical = [_group(kw), _group(th)]
    parts = [
        *topical,
        _group([f"sourcecountry:{c.strip().replace(' ', '').lower()}" for c in params.get("source_countries", []) if c.strip()]),
        _group([f"sourcelang:{l.strip().lower()}" for l in params.get("languages", []) if l.strip()]),
    ]
    parts += [f"-{_term(x)}" for x in params.get("exclude_keywords", []) if x.strip()]
    q = " ".join(p for p in parts if p)
    if not q:
        raise SourceError("GDELT profile needs at least one keyword, theme, country or language")
    return q


_SPACED_PUNCT = re.compile(r"\s+([,.:;!?%)])")


def clean_title(t: str) -> str:
    """GDELT tokenises titles ("Attack in Aden , officials say") - undo the extra spaces."""
    t = _SPACED_PUNCT.sub(r"\1", t or "")
    t = re.sub(r"\(\s+", "(", t)
    t = re.sub(r"\s+'\s*s\b", "'s", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _parse_seendate(s: str) -> datetime:
    return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


class GdeltSource(NewsSource):
    name = "gdelt"

    def fetch(self, params: dict, since: datetime, until: datetime) -> list[RawArticle]:
        global _last_call, _strikes, _blocked_until
        if time.time() < _blocked_until:
            raise GdeltRateLimited(_retry_at())  # no network call while cooling down
        # DOC API only searches the last ~3 months.
        since = max(since, until - timedelta(days=89))
        query = build_query(params)
        req = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": min(int(params.get("max_records", 250)), 250),
            "sort": "datedesc",
            "startdatetime": since.strftime("%Y%m%d%H%M%S"),
            "enddatetime": until.strftime("%Y%m%d%H%M%S"),
        }
        with _lock:
            wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
            if wait > 0:
                time.sleep(wait)
            try:
                r = requests.get(API, params=req, timeout=60, headers={"User-Agent": "intel-ingest/0.1"})
            finally:
                _last_call = time.monotonic()
        if r.status_code == 429:
            _blocked_until = time.time() + _COOLDOWNS[min(_strikes, len(_COOLDOWNS) - 1)]
            _strikes += 1
            raise GdeltRateLimited(_retry_at())
        _strikes = 0
        if r.status_code != 200:
            raise SourceError(f"GDELT HTTP {r.status_code}: {r.text[:300]}")
        text = r.text.strip()
        if not text:
            return []
        try:
            data = r.json()
        except ValueError:
            # GDELT reports query problems as plain text
            raise SourceError(f"GDELT: {text[:300]} (query: {query})")

        out = []
        for a in data.get("articles", []) or []:
            try:
                published = _parse_seendate(a["seendate"])
            except (KeyError, ValueError):
                published = until
            out.append(
                RawArticle(
                    url=a["url"],
                    title=clean_title(a.get("title") or ""),
                    published_at=published,
                    source_domain=a.get("domain"),
                    source_country=a.get("sourcecountry"),
                    language=a.get("language"),
                    image_url=a.get("socialimage") or None,
                )
            )
        return out
