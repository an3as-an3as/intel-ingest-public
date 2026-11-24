"""Counts, time series and trend direction per PIR."""

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..models import Article, ArticlePir, Pir
from .scope import dashboard_scope

WINDOWS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30), "90d": timedelta(days=90)}


def parse_window(w: str) -> timedelta:
    if w not in WINDOWS:
        raise ValueError(f"window must be one of {list(WINDOWS)}")
    return WINDOWS[w]


def trend_label(cur: int, prev: int) -> dict:
    """Compare this window with the one before it.

    Small counts are noisy, so a direction is only claimed when the change is both
    >= 25% and >= 3 articles.
    """
    if cur + prev < 4:
        return {"direction": "insufficient", "change_pct": None}
    pct = (cur - prev) / prev * 100 if prev else None
    diff = cur - prev
    if diff >= 3 and (prev == 0 or diff / prev >= 0.25):
        d = "rising"
    elif -diff >= 3 and -diff / prev >= 0.25:
        d = "falling"
    else:
        d = "steady"
    return {"direction": d, "change_pct": round(pct, 1) if pct is not None else None}


def set_article_conditions(set_id: int, since: datetime, until: datetime):
    """One row per article, even if it answers several active requirements in a set."""
    return (Article.status == 'enriched', Article.published_at >= since, Article.published_at < until,
            dashboard_scope(set_id),
            Article.matches.any(ArticlePir.pir.has(and_(Pir.set_id == set_id, Pir.active.is_(True)))))


def set_activity(s: Session, set_id: int, window: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    span = parse_window(window)
    start = now - span
    dates = s.scalars(select(Article.published_at).where(*set_article_conditions(set_id, now - 2 * span, now))).all()
    hourly = span <= timedelta(hours=48)
    bucket = timedelta(hours=1) if hourly else timedelta(days=1)
    n = int(span / bucket)
    counts = [0] * n
    current = previous = 0
    for date in dates:
        if date >= start:
            current += 1
            counts[min(n - 1, int((date - start) / bucket))] += 1
        else:
            previous += 1
    return {'count': current, 'previous_count': previous, **trend_label(current, previous),
            'series': {'bucket': 'hour' if hourly else 'day', 'start': [(start + i * bucket).isoformat() for i in range(n)],
                       'counts': counts}}


def pir_stats(s: Session, pirs: list[Pir], window: str, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    span = parse_window(window)
    hourly = span <= timedelta(hours=48)
    bucket = timedelta(hours=1) if hourly else timedelta(days=1)
    start, prev_start = now - span, now - 2 * span
    ids = [p.id for p in pirs]
    if not ids:
        return []

    rows = s.execute(
        select(ArticlePir.pir_id, Article.published_at)
        .join(Article, Article.id == ArticlePir.article_id)
        .where(ArticlePir.pir_id.in_(ids), Article.published_at >= prev_start, Article.status == "enriched",
               dashboard_scope(pirs[0].set_id))
    ).all()

    n_buckets = int(span / bucket)
    first = (now - n_buckets * bucket)
    cur, prev = Counter(), Counter()
    series = {pid: [0] * n_buckets for pid in ids}
    for pid, ts in rows:
        if ts >= start:
            cur[pid] += 1
            i = int((ts - first) / bucket)
            if 0 <= i < n_buckets:
                series[pid][i] += 1
        else:
            prev[pid] += 1

    labels = [(first + i * bucket).isoformat() for i in range(n_buckets)]
    out = []
    for p in pirs:
        out.append(
            {
                "pir_id": p.id,
                "code": p.code,
                "title": p.title,
                "priority": p.priority,
                "count": cur[p.id],
                "previous_count": prev[p.id],
                **trend_label(cur[p.id], prev[p.id]),
                "series": {"bucket": "hour" if hourly else "day", "start": labels, "counts": series[p.id]},
            }
        )
    return out
