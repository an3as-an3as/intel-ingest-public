"""Conservative Unicode fingerprints; legacy hashes remain unchanged for rollback."""
import hashlib
import html
import re
import unicodedata
from datetime import timedelta

from sqlalchemy import select

from ..models import Article, ArticleFingerprint

VERSION = 'unicode-v1'
_GENERIC_TITLES = {'breaking news', 'latest news', 'live updates', 'news update'}


def legacy_title_hash(title: str) -> str:
    normalized = re.sub(r'[^a-z0-9 ]', '', title.lower())
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return hashlib.sha256(normalized.encode()).hexdigest()


def title_hash(title: str) -> str | None:
    text = unicodedata.normalize('NFKC', html.unescape(title)).casefold()
    normalized = ''.join(c if unicodedata.category(c)[0] in 'LMN' else ' ' for c in text)
    normalized = ' '.join(normalized.split())
    # Do not equate different URLs just because titles are punctuation, numbers,
    # very short labels, or common generic headlines. URL dedupe still applies.
    if sum(c.isalpha() for c in normalized) < 8 or normalized in _GENERIC_TITLES:
        return None
    return hashlib.sha256(normalized.encode()).hexdigest()


def recent_title_matches(session, titles, now):
    """Lazily index recent legacy rows; never trust their ASCII hashes alone.

    This adds rows in a new table, without rewriting/deleting articles, old hashes,
    classification results or stream memberships. Missing historical articles
    cannot be recovered by changing the hash algorithm.
    """
    wanted = {digest for title in titles if (digest := title_hash(title))}
    if not wanted:
        return {}
    cutoff = now - timedelta(hours=72)
    old_rows = session.scalars(
        select(Article).outerjoin(ArticleFingerprint, ArticleFingerprint.article_id == Article.id)
        .where(ArticleFingerprint.article_id.is_(None), Article.ingested_at >= cutoff).order_by(Article.id)
    ).all()
    for article in old_rows:
        session.add(ArticleFingerprint(article_id=article.id, version=VERSION, digest=title_hash(article.title)))
    session.flush()
    rows = session.execute(
        select(ArticleFingerprint.digest, Article).join(Article, ArticleFingerprint.article_id == Article.id)
        .where(ArticleFingerprint.version == VERSION, ArticleFingerprint.digest.in_(wanted),
               Article.ingested_at >= cutoff).order_by(Article.id)
    ).all()
    return {digest: article for digest, article in rows}
