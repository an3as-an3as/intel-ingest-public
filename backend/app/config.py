from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://intel:intel@db:5432/intel"
    app_environment: Literal['production', 'development', 'test'] = 'production'

    # Model providers. Keys/URLs are server configuration, never browser input.
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str = 'https://api.openai.com/v1'
    deepseek_api_key: str | None = None
    deepseek_base_url: str = 'https://api.deepseek.com'
    gemini_api_key: str | None = None
    gemini_base_url: str = 'https://generativelanguage.googleapis.com/v1beta'
    ollama_base_url: str | None = None  # Explicit host/native/Docker/remote endpoint.
    ollama_api_key: str | None = None  # Optional authenticated reverse proxy.
    llm_request_timeout_seconds: int = Field(180, ge=1, le=600)
    alternative_model_max_tokens: int = Field(8192, ge=1, le=128000)
    classify_provider: Literal['anthropic', 'openai', 'deepseek', 'gemini', 'ollama'] = 'anthropic'
    summary_provider: Literal['anthropic', 'openai', 'deepseek', 'gemini', 'ollama'] = 'anthropic'
    classify_model: str = "claude-opus-5-5"
    classify_effort: str = "low"
    summary_model: str = "claude-opus-5-5"
    summary_effort: str = "high"
    classify_concurrency: int = 4
    classify_batch_size: int = 40  # articles enriched per worker tick
    pir_match_threshold: float = 0.5

    # Article text extraction (GDELT only returns headlines/metadata)
    fetch_article_text: bool = True
    article_text_max_chars: int = 6000

    # Sources
    newscatcher_api_key: str | None = None
    newscatcher_api: str = "news"  # "news" (platform.newscatcherapi.com keys) or "v3" (Enterprise)
    newscatcher_effort: str = "low"  # low=1 credit/search, medium=5, high=10
    # When GDELT rate-limits us, run GDELT profiles' keywords through NewsCatcher instead
    gdelt_fallback_to_newscatcher: bool = True

    # Experimental keyword translation; opt-in deployment configuration, never per poll.
    keyword_translation_allow_live: bool = False
    keyword_translation_model: str = 'claude-haiku-5-5'

    # Worker
    worker_tick_seconds: int = 60

    # Optional shared password for the web UI / API (HTTP Basic, any username)
    app_password: str | None = None

    map_tile_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    map_tile_attribution: str = "&copy; OpenStreetMap contributors"


@lru_cache
def get_settings() -> Settings:
    return Settings()
