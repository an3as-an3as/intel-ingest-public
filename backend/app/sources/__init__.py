from .base import NewsSource, RawArticle, SourceError
from .gdelt import GdeltSource
from .newscatcher import NewsCatcherSource

SOURCES: dict[str, NewsSource] = {
    "gdelt": GdeltSource(),
    "newscatcher": NewsCatcherSource(),
}

__all__ = ["SOURCES", "NewsSource", "RawArticle", "SourceError"]
