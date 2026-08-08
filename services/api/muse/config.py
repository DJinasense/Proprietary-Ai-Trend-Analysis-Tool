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

    # Chart sources. Deezer and Apple Music need no credential at all — their
    # endpoints are public — so they default on and are toggled by flag rather
    # than by the presence of a key.
    deezer_enabled: bool = True

    apple_music_enabled: bool = True
    # ISO country codes for Apple's per-storefront charts. More countries means
    # more requests and a broader, less US-centric picture; the trade is one
    # extra HTTP call per country per feed per poll.
    apple_music_countries: str = "us,gb"

    lastfm_api_key: str = ""
    # Last.fm's geo charts key on full country *names*, not ISO codes.
    lastfm_countries: str = "united states,united kingdom"

    ingest_interval_seconds: int = 900

    # ── Scenes ────────────────────────────────────────────────────────────
    # AI-generated music and human-made music are tracked as separate scenes,
    # not as one filter over the other. Both default on: turning one off narrows
    # what MUSE collects, it does not redirect that effort to the other scene.
    human_scene_enabled: bool = True
    ai_scene_enabled: bool = True

    # YouTube charges 100 quota units for a search.list call against 1 for
    # videos.list, on a 10,000/day cap. At the 900s ingest interval, searching
    # every cycle would cost 9,600 units/day for the search passes alone —
    # before the AI scene adds a second one. This throttles searches to their
    # own interval so the charts keep polling at full rate and the searches
    # sample less often. At 3600s that is 24 runs/day/pass — two passes, chart
    # polls and hydration together come to roughly 4,950 of the 10,000 units.
    youtube_search_min_interval_seconds: int = 3600

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
