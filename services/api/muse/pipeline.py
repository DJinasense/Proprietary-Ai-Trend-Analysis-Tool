"""End-to-end analysis pipeline: audio file in, narrative insight out.

Ties together the four tiers from the spec:
  Tier 1  ingest + acoustic analysis   (muse.audio)
  Tier 2  contextual cross-reference   (muse.intelligence.correlation)
  Tier 3  fatigue + narrative          (muse.intelligence.fatigue/narrative)
  Tier 4  delivered by the API layer   (muse.routers)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from muse.audio import analyze_audio, embed_track
from muse.intelligence.correlation import find_drivers
from muse.intelligence.fatigue import compute_fatigue
from muse.intelligence.narrative import synthesize

logger = logging.getLogger(__name__)


async def _set_job(
    session: AsyncSession,
    job_id: str,
    *,
    status: str | None = None,
    stage: str | None = None,
    error: str | None = None,
) -> None:
    await session.execute(
        text(
            """
            UPDATE analysis_jobs
            SET status = COALESCE(:status, status),
                stage  = COALESCE(:stage, stage),
                error  = COALESCE(:error, error),
                updated_at = now()
            WHERE job_id = :job_id
            """
        ),
        {"job_id": job_id, "status": status, "stage": stage, "error": error},
    )
    await session.commit()


async def run_analysis(
    session: AsyncSession,
    *,
    job_id: str,
    track_row_id: int,
    media_path: str,
    title: str,
    genre: str | None,
) -> dict:
    """Run the full pipeline for one track. Raises on unrecoverable failure."""

    # ── Tier 1: acoustic analysis ─────────────────────────────────────────
    await _set_job(session, job_id, status="running", stage="acoustic_analysis")

    # librosa is CPU-bound and synchronous; off-thread so it doesn't stall the
    # event loop and block every other request for the duration.
    profile = await asyncio.to_thread(analyze_audio, media_path)
    vector, backend, native_dim = await asyncio.to_thread(
        embed_track, profile, media_path
    )

    await session.execute(
        text(
            """
            INSERT INTO audio_features (
                track_id, bpm, beat_strength, musical_key, mode, key_confidence,
                energy, valence, danceability, acousticness,
                spectral_centroid, spectral_bandwidth, spectral_rolloff,
                spectral_flatness, zero_crossing_rate, rms_mean, dynamic_range,
                raw, analyzed_at
            ) VALUES (
                :track_id, :bpm, :beat_strength, :musical_key, :mode, :key_confidence,
                :energy, :valence, :danceability, :acousticness,
                :spectral_centroid, :spectral_bandwidth, :spectral_rolloff,
                :spectral_flatness, :zero_crossing_rate, :rms_mean, :dynamic_range,
                CAST(:raw AS jsonb), now()
            )
            ON CONFLICT (track_id) DO UPDATE SET
                bpm = EXCLUDED.bpm, beat_strength = EXCLUDED.beat_strength,
                musical_key = EXCLUDED.musical_key, mode = EXCLUDED.mode,
                key_confidence = EXCLUDED.key_confidence,
                energy = EXCLUDED.energy, valence = EXCLUDED.valence,
                danceability = EXCLUDED.danceability,
                acousticness = EXCLUDED.acousticness,
                spectral_centroid = EXCLUDED.spectral_centroid,
                spectral_bandwidth = EXCLUDED.spectral_bandwidth,
                spectral_rolloff = EXCLUDED.spectral_rolloff,
                spectral_flatness = EXCLUDED.spectral_flatness,
                zero_crossing_rate = EXCLUDED.zero_crossing_rate,
                rms_mean = EXCLUDED.rms_mean,
                dynamic_range = EXCLUDED.dynamic_range,
                raw = EXCLUDED.raw, analyzed_at = now()
            """
        ),
        {
            "track_id": track_row_id,
            "bpm": profile.bpm,
            "beat_strength": profile.beat_strength,
            "musical_key": profile.musical_key,
            "mode": profile.mode,
            "key_confidence": profile.key_confidence,
            "energy": profile.energy,
            "valence": profile.valence,
            "danceability": profile.danceability,
            "acousticness": profile.acousticness,
            "spectral_centroid": profile.spectral_centroid,
            "spectral_bandwidth": profile.spectral_bandwidth,
            "spectral_rolloff": profile.spectral_rolloff,
            "spectral_flatness": profile.spectral_flatness,
            "zero_crossing_rate": profile.zero_crossing_rate,
            "rms_mean": profile.rms_mean,
            "dynamic_range": profile.dynamic_range,
            "raw": json.dumps(profile.to_dict()),
        },
    )

    vec_literal = "[" + ",".join(f"{v:.6f}" for v in vector) + "]"
    await session.execute(
        text(
            """
            INSERT INTO track_embeddings (track_id, embedding, backend, native_dim)
            VALUES (:track_id, CAST(:vec AS vector), :backend, :native_dim)
            ON CONFLICT (track_id) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                backend = EXCLUDED.backend,
                native_dim = EXCLUDED.native_dim,
                created_at = now()
            """
        ),
        {
            "track_id": track_row_id,
            "vec": vec_literal,
            "backend": backend,
            "native_dim": native_dim,
        },
    )

    await session.execute(
        text("UPDATE tracks SET duration_sec = :d WHERE id = :id"),
        {"d": profile.duration_sec, "id": track_row_id},
    )
    await session.commit()

    # ── Tier 2: contextual cross-reference ────────────────────────────────
    await _set_job(session, job_id, stage="correlation")
    drivers = await find_drivers(session, title=title, genre=genre)

    # ── Tier 3a: fatigue ──────────────────────────────────────────────────
    await _set_job(session, job_id, stage="fatigue")
    fatigue = await compute_fatigue(
        session, track_id=track_row_id, embedding=vector, backend=backend
    )

    await session.execute(
        text(
            """
            INSERT INTO fatigue_snapshots (
                track_id, fatigue_index, confidence, neighbor_count,
                density_recent, density_slope, engagement_slope, components
            ) VALUES (
                :track_id, :fatigue_index, :confidence, :neighbor_count,
                :density_recent, :density_slope, :engagement_slope,
                CAST(:components AS jsonb)
            )
            """
        ),
        {
            "track_id": track_row_id,
            "fatigue_index": fatigue.fatigue_index,
            "confidence": fatigue.confidence,
            "neighbor_count": fatigue.neighbor_count,
            "density_recent": fatigue.density_recent,
            "density_slope": fatigue.density_slope,
            "engagement_slope": fatigue.engagement_slope,
            "components": json.dumps(fatigue.components, default=str),
        },
    )
    await session.commit()

    # ── Tier 3b: narrative synthesis ──────────────────────────────────────
    await _set_job(session, job_id, stage="narrative")
    narrative, evidence = await synthesize(
        title=title,
        genre=genre,
        acoustic=profile.scalar_summary(),
        fatigue=fatigue,
        drivers=drivers,
    )

    await session.execute(
        text(
            """
            INSERT INTO narrative_insights (
                track_id, headline, narrative, actionable_insight,
                primary_drivers, fatigue_index, fatigue_confidence,
                generation_mode, model
            ) VALUES (
                :track_id, :headline, :narrative, :actionable_insight,
                CAST(:drivers AS jsonb), :fatigue_index, :fatigue_confidence,
                :generation_mode, :model
            )
            """
        ),
        {
            "track_id": track_row_id,
            "headline": narrative.headline,
            "narrative": narrative.narrative,
            "actionable_insight": narrative.actionable_insight,
            "drivers": json.dumps([d.to_dict() for d in drivers], default=str),
            "fatigue_index": fatigue.fatigue_index,
            "fatigue_confidence": fatigue.confidence,
            "generation_mode": narrative.generation_mode,
            "model": narrative.model,
        },
    )
    await session.commit()

    await _set_job(session, job_id, status="complete", stage="done")

    return {
        "track_id": track_row_id,
        "acoustic": profile.scalar_summary(),
        "fatigue": fatigue.to_dict(),
        "drivers": [d.to_dict() for d in drivers],
        "narrative": {
            "headline": narrative.headline,
            "narrative": narrative.narrative,
            "actionable_insight": narrative.actionable_insight,
            "generation_mode": narrative.generation_mode,
            "model": narrative.model,
        },
        "embedding_backend": backend,
    }
