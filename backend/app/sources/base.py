from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawArticle:
    url: str
    title: str
    published_at: datetime
    description: str | None = None
    body: str | None = None
    source_domain: str | None = None
    source_country: str | None = None
    language: str | None = None
    image_url: str | None = None
    extra: dict = field(default_factory=dict)


class FetchResult(list):
    """List-compatible result carrying per-call telemetry without shared adapter state."""

    def __init__(self, articles=(), *, provider=None, planned_requests=None):
        super().__init__(articles)
        self.provider = provider
        self.planned_requests = planned_requests
        self.request_metrics = []
        self.duplicate_urls = 0
        self.invalid_articles = 0


class SourceError(RuntimeError):
    def __init__(self, message, *, partial=None, retry_at=None):
        super().__init__(message)
        self.partial = partial
        self.retry_at = retry_at if retry_at is not None else getattr(self, 'retry_at', None)


class QueryBudgetError(ValueError):
    """A local pre-transport refusal with a safe diagnostic code."""

    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class NewsSource:
    """Adapter interface. `params` is the ingest profile's params dict."""

    name: str = "base"

    def fetch(self, params: dict, since: datetime, until: datetime) -> list[RawArticle]:
        raise NotImplementedError
