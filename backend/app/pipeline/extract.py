"""Fetch and extract readable article text (GDELT gives only headlines)."""

import logging

import requests
import trafilatura

log = logging.getLogger(__name__)
_UA = "Mozilla/5.0 (compatible; intel-ingest/0.1; +https://github.com/)"


def fetch_text(url: str, max_chars: int) -> tuple[str | None, str | None]:
    """Return (body_text, description). Either may be None on failure."""
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": _UA})
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return None, None
        html = r.text
    except requests.RequestException as e:
        log.debug("fetch failed %s: %s", url, e)
        return None, None
    body = trafilatura.extract(html, include_comments=False, include_tables=False)
    meta = trafilatura.extract_metadata(html)
    desc = getattr(meta, "description", None) if meta else None
    if body and len(body) > max_chars:
        body = body[:max_chars]
    return body, desc
