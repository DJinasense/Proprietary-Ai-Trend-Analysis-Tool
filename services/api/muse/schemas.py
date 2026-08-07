"""API response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    embedding_backend: str
    narrative_mode: str = Field(
        description="'llm' when an Anthropic key is configured, else 'deterministic'"
    )
    connectors: list[dict[str, Any]]


class UploadResponse(BaseModel):
    job_id: str
    track_id: str
    status: str
    message: str
    duplicate: bool = Field(
        default=False,
        description=(
            "True when the uploaded bytes already existed in the corpus. The "
            "returned job_id belongs to the original analysis; no new track was "
            "created."
        ),
    )


class JobStatus(BaseModel):
    job_id: str
    track_id: str | None
    status: str
    stage: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class AcousticSummary(BaseModel):
    # Measured directly from the waveform.
    bpm: float | None
    musical_key: str | None
    mode: str | None
    key_confidence: float | None
    duration_sec: float | None
    spectral_centroid: float | None
    spectral_bandwidth: float | None
    spectral_rolloff: float | None
    spectral_flatness: float | None
    zero_crossing_rate: float | None
    rms_mean: float | None
    dynamic_range: float | None
    beat_strength: float | None
    # Heuristic proxies — see muse.audio.features module docstring.
    energy: float | None
    valence: float | None
    danceability: float | None
    acousticness: float | None


class DriverOut(BaseModel):
    platform: str
    entity: str
    entity_type: str | None
    originating_event: str
    velocity_surge: float
    engagement: int
    context_anchor_url: str
    observed_at: str
    relevance: float
    # Why this signal was accepted as a driver. Defaulted so analyses stored
    # before the evidence bar existed still deserialise.
    match_basis: str = "unspecified"
    matched_terms: list[str] = []


class FatigueOut(BaseModel):
    fatigue_index: float
    confidence: float
    verdict: str
    explanation: str
    neighbor_count: int
    density_recent: float
    density_slope: float
    engagement_slope: float
    components: dict[str, Any]


class NarrativeOut(BaseModel):
    headline: str
    narrative: str
    actionable_insight: str
    generation_mode: str
    model: str | None
    generated_at: datetime | None = None


class InsightResponse(BaseModel):
    track_id: str
    title: str
    genre: str | None
    acoustic: AcousticSummary | None
    fatigue: FatigueOut | None
    drivers: list[DriverOut]
    narrative: NarrativeOut | None
    embedding_backend: str | None = None


class TrackSummary(BaseModel):
    track_id: str
    title: str
    genre: str | None
    duration_sec: float | None
    created_at: datetime
    fatigue_index: float | None
    fatigue_confidence: float | None
    headline: str | None


class SignalOut(BaseModel):
    platform: str
    connector: str
    target_entity: str
    entity_type: str | None
    velocity_spike_pct: float
    engagement_count: int
    context_anchor_url: str
    observed_at: datetime


class CorpusStats(BaseModel):
    tracks: int
    tracks_with_embeddings: int
    social_signals: int
    signals_last_24h: int
    platforms: list[dict[str, Any]]
    fatigue_ready: bool
    fatigue_ready_message: str
