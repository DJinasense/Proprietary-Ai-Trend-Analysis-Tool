"""SQLAlchemy ORM models mirroring migrations/001_init.sql."""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from muse.config import settings


class Base(DeclarativeBase):
    pass


class Artist(Base):
    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    artist_key: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    track_id: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    artist_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("artists.id", ondelete="SET NULL"), nullable=True
    )
    genre: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    released_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    features: Mapped["AudioFeature | None"] = relationship(
        back_populates="track", uselist=False, cascade="all, delete-orphan"
    )
    embedding: Mapped["TrackEmbedding | None"] = relationship(
        back_populates="track", uselist=False, cascade="all, delete-orphan"
    )


class AudioFeature(Base):
    __tablename__ = "audio_features"

    track_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    bpm: Mapped[float | None] = mapped_column(Float)
    beat_strength: Mapped[float | None] = mapped_column(Float)
    musical_key: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str | None] = mapped_column(Text)
    key_confidence: Mapped[float | None] = mapped_column(Float)
    energy: Mapped[float | None] = mapped_column(Float)
    valence: Mapped[float | None] = mapped_column(Float)
    danceability: Mapped[float | None] = mapped_column(Float)
    acousticness: Mapped[float | None] = mapped_column(Float)
    spectral_centroid: Mapped[float | None] = mapped_column(Float)
    spectral_bandwidth: Mapped[float | None] = mapped_column(Float)
    spectral_rolloff: Mapped[float | None] = mapped_column(Float)
    spectral_flatness: Mapped[float | None] = mapped_column(Float)
    zero_crossing_rate: Mapped[float | None] = mapped_column(Float)
    rms_mean: Mapped[float | None] = mapped_column(Float)
    dynamic_range: Mapped[float | None] = mapped_column(Float)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    track: Mapped[Track] = relationship(back_populates="features")


class TrackEmbedding(Base):
    __tablename__ = "track_embeddings"

    track_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.embedding_storage_dim)
    )
    backend: Mapped[str] = mapped_column(Text)
    native_dim: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    track: Mapped[Track] = relationship(back_populates="embedding")


class SocialSignal(Base):
    __tablename__ = "social_signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    signal_id: Mapped[str] = mapped_column(Text, unique=True)
    platform: Mapped[str] = mapped_column(Text)
    connector: Mapped[str] = mapped_column(Text)
    target_entity: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(Text)
    velocity_spike_pct: Mapped[float] = mapped_column(Float)
    engagement_count: Mapped[int] = mapped_column(BigInteger, default=0)
    associated_keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    context_anchor_url: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)


class FatigueSnapshot(Base):
    __tablename__ = "fatigue_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    track_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tracks.id", ondelete="CASCADE")
    )
    fatigue_index: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    neighbor_count: Mapped[int] = mapped_column(Integer)
    density_recent: Mapped[float] = mapped_column(Float)
    density_slope: Mapped[float] = mapped_column(Float)
    engagement_slope: Mapped[float] = mapped_column(Float)
    components: Mapped[dict] = mapped_column(JSONB, default=dict)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class NarrativeInsight(Base):
    __tablename__ = "narrative_insights"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    track_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tracks.id", ondelete="CASCADE")
    )
    headline: Mapped[str] = mapped_column(Text)
    narrative: Mapped[str] = mapped_column(Text)
    actionable_insight: Mapped[str] = mapped_column(Text)
    primary_drivers: Mapped[list] = mapped_column(JSONB, default=list)
    fatigue_index: Mapped[float | None] = mapped_column(Float)
    fatigue_confidence: Mapped[float | None] = mapped_column(Float)
    generation_mode: Mapped[str] = mapped_column(Text, default="deterministic")
    model: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[str] = mapped_column(Text, unique=True)
    track_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, default="queued")
    stage: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ConnectorState(Base):
    __tablename__ = "connector_state"

    connector: Mapped[str] = mapped_column(Text, primary_key=True)
    cursor: Mapped[str | None] = mapped_column(Text)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    state: Mapped[dict] = mapped_column(JSONB, default=dict)
