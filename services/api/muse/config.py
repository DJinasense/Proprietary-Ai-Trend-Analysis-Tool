"""Runtime configuration.

Pydantic v2 moved ``BaseSettings`` into the separate ``pydantic-settings``
package; the spec PDF's sample imported it from ``pydantic`` directly, which
raises ImportError on any current install.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MUSE_",
        env_file=".env",
        extra="ignore",
    )

    # ── Core ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://muse:muse@localhost:5433/muse"
    media_root: str = "/data/media"
    cors_origins: str = "http://localhost:3000"

    # ── Narrative synthesis ───────────────────────────────────────────────
    anthropic_api_key: str = ""
    narrative_model: str = "claude-sonnet-5"

    # ── Audio ─────────────────────────────────────────────────────────────
    embedding_backend: str = "stats"  # "stats" | "clap"
    # Storage width for the pgvector column. Backends with a smaller native
    # dimension zero-pad; padding does not alter cosine similarity.
    embedding_storage_dim: int = 512
    analysis_sample_rate: int = 22050
    # Cap analysis at the first N seconds. Most tracks establish their sonic
    # identity well inside this, and it bounds worst-case CPU per upload.
    analysis_max_seconds: float = 180.0

    # ── Fatigue Index ─────────────────────────────────────────────────────
    fatigue_neighbor_radius: float = 0.82
    fatigue_half_life_days: float = 90.0
    fatigue_min_neighbors: int = 12
    fatigue_max_neighbors: int = 400

    # ── Correlation evidence bar ──────────────────────────────────────────
    # How much overlap a social signal needs before MUSE will call it a driver.
    # Below these thresholds the engine reports no driver rather than dressing
    # a keyword collision up as causation.
    correlation_min_distinct_terms: int = 2
    # A term appearing in more than this share of all signals in the window is
    # treated as corpus boilerplate and cannot carry a match on its own.
    correlation_max_df_ratio: float = 0.15
    correlation_min_relevance: float = 0.05

    # ── Connectors ────────────────────────────────────────────────────────
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "muse-trend-analysis/0.1"

    youtube_api_key: str = ""

    bluesky_identifier: str = ""
    bluesky_app_password: str = ""

    google_trends_enabled: bool = True

    ingest_interval_seconds: int = 900

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
