from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Always returns timezone-aware UTC datetimes (SQLite drops tzinfo; Postgres keeps it)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc) if value is not None else None

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class AppSetting(Base):
    """Shared runtime preferences; API credentials remain in the environment."""

    __tablename__ = 'app_settings'
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


class WorkerState(Base):
    """Operational heartbeat, independent of the worker's long-running transactions."""

    __tablename__ = "worker_states"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    heartbeat_at: Mapped[datetime] = mapped_column(UTCDateTime())
    phase: Mapped[str] = mapped_column(String(40), default="starting")
    phase_started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    last_tick_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error: Mapped[str | None] = mapped_column(Text)
    summary_id: Mapped[int | None] = mapped_column(Integer)


class KeywordTranslationCache(Base):
    """Translation suggestions are cached, but never auto-approved for a stream."""

    __tablename__ = 'keyword_translation_cache'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    candidates: Mapped[list] = mapped_column(JSON)
    origin: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class KeywordTranslationReview(Base):
    """Immutable approved query expansion; drafts never affect collection."""

    __tablename__ = 'keyword_translation_reviews'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    basis_hash: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    model_calls: Mapped[int] = mapped_column(Integer, default=0)


class SourceProfile(Base):
    """An ingest profile = the initial, source-level filter (query, geography, themes, language)."""

    __tablename__ = "source_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(40))  # "gdelt" | "newscatcher"
    # keywords: list[str]; exclude_keywords: list[str]; themes: list[str];
    # source_countries: list[str]; languages: list[str]; max_records: int
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_status: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    dashboard_links: Mapped[list["ProfileDashboard"]] = relationship(cascade="all, delete-orphan")
    ingest_state: Mapped["IngestState | None"] = relationship(cascade="all, delete-orphan", uselist=False)


class IngestState(Base):
    """Additive scheduling state: attempts must not overwrite successful coverage."""

    __tablename__ = 'ingest_states'
    profile_id: Mapped[int] = mapped_column(ForeignKey('source_profiles.id', ondelete='CASCADE'), primary_key=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    initial_since: Mapped[datetime | None] = mapped_column(UTCDateTime())
    retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failures: Mapped[int] = mapped_column(Integer, default=0)
    run_requested: Mapped[bool] = mapped_column(Boolean, default=False)


class IngestRun(Base):
    """Poll ledger; request hashes/metrics only, never credentials or provider bodies."""

    __tablename__ = 'ingest_runs'
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey('source_profiles.id', ondelete='SET NULL'), index=True)
    source: Mapped[str] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    window_since: Mapped[datetime] = mapped_column(UTCDateTime())
    window_until: Mapped[datetime] = mapped_column(UTCDateTime())
    config_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default='running')
    returned_articles: Mapped[int] = mapped_column(Integer, default=0)
    new_articles: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_urls: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_titles: Mapped[int] = mapped_column(Integer, default=0)
    excluded_articles: Mapped[int] = mapped_column(Integer, default=0)
    invalid_articles: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    request_metrics: Mapped[list] = mapped_column(JSON, default=list)
    planned_requests: Mapped[int | None] = mapped_column(Integer)
    estimated_credits: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(80))


class ProfileDashboard(Base):
    """Explicit stream-to-dashboard links; no links preserves legacy all-stream scope."""

    __tablename__ = "profile_dashboards"
    profile_id: Mapped[int] = mapped_column(ForeignKey("source_profiles.id", ondelete="CASCADE"), primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("pir_sets.id", ondelete="CASCADE"), primary_key=True)


class ArticleProfile(Base):
    """A deduplicated article can belong to multiple ingestion streams."""

    __tablename__ = "article_profiles"
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("source_profiles.id", ondelete="CASCADE"), primary_key=True)


class PirSet(Base):
    """A group of related PIRs; each set gets its own dashboard."""

    __tablename__ = "pir_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    pirs: Mapped[list["Pir"]] = relationship(
        back_populates="pir_set", cascade="all, delete-orphan", order_by="Pir.code"
    )


class Pir(Base):
    __tablename__ = "pirs"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("pir_sets.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40), unique=True)  # e.g. "BAL-1"
    title: Mapped[str] = mapped_column(String(300))
    question: Mapped[str] = mapped_column(Text)  # the intelligence requirement itself
    indicators: Mapped[str] = mapped_column(Text, default="")  # what counts as relevant
    priority: Mapped[int] = mapped_column(Integer, default=2)  # 1 high .. 3 low
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    pir_set: Mapped[PirSet] = relationship(back_populates="pirs")


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    title_hash: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    source_domain: Mapped[str | None] = mapped_column(String(300))
    source_country: Mapped[str | None] = mapped_column(String(100))
    language: Mapped[str | None] = mapped_column(String(40))
    image_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_profiles.id", ondelete="SET NULL"), index=True
    )

    # pending -> enriched | irrelevant | failed
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text)

    # Enrichment (zero-shot classification)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str | None] = mapped_column(String(40), index=True)
    region: Mapped[str | None] = mapped_column(String(40), index=True)
    countries: Mapped[list | None] = mapped_column(JSON)
    location_name: Mapped[str | None] = mapped_column(String(300))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    geo_precision: Mapped[str | None] = mapped_column(String(20))
    enriched_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    model: Mapped[str | None] = mapped_column(String(80))

    matches: Mapped[list["ArticlePir"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )


class IngestRunArticle(Base):
    """Attribution for later quality evaluation; overlapping polls do not reclassify."""

    __tablename__ = 'ingest_run_articles'
    run_id: Mapped[int] = mapped_column(ForeignKey('ingest_runs.id', ondelete='CASCADE'), primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey('articles.id', ondelete='CASCADE'), primary_key=True)
    is_new: Mapped[bool] = mapped_column(Boolean, default=False)
    query_parts: Mapped[list] = mapped_column(JSON, default=list)


class ArticleFingerprint(Base):
    """Unicode title index, separate from the unchanged legacy article hash column."""

    __tablename__ = 'article_fingerprints'
    article_id: Mapped[int] = mapped_column(ForeignKey('articles.id', ondelete='CASCADE'), primary_key=True)
    version: Mapped[str] = mapped_column(String(30), default='unicode-v1')
    digest: Mapped[str | None] = mapped_column(String(64), index=True)


class ArticlePir(Base):
    __tablename__ = "article_pirs"
    __table_args__ = (Index("ix_article_pirs_pir", "pir_id"),)

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    pir_id: Mapped[int] = mapped_column(ForeignKey("pirs.id", ondelete="CASCADE"), primary_key=True)
    score: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text, default="")

    article: Mapped[Article] = relationship(back_populates="matches")
    pir: Mapped[Pir] = relationship()


class Summary(Base):
    __tablename__ = "summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("pir_sets.id", ondelete="CASCADE"), index=True)
    period_label: Mapped[str] = mapped_column(String(40))
    period_start: Mapped[datetime] = mapped_column(UTCDateTime())
    period_end: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending (durable queue)|done|failed
    content: Mapped[str | None] = mapped_column(Text)
    article_count: Mapped[int] = mapped_column(Integer, default=0)
    references: Mapped[dict | None] = mapped_column(JSON)  # "A123" -> {title, url, date}
    model: Mapped[str | None] = mapped_column(String(80))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
