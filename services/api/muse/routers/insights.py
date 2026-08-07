"""Narrative insight retrieval."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from muse.db import get_session
from muse.schemas import (
    AcousticSummary,
    DriverOut,
    FatigueOut,
    InsightResponse,
    NarrativeOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("/{track_id}", response_model=InsightResponse)
async def get_insight(
    track_id: str, session: AsyncSession = Depends(get_session)
) -> InsightResponse:
    """Full analysis for one track: acoustic profile, fatigue, drivers, narrative."""

    track = (
        await session.execute(
            text(
                """
                SELECT t.id, t.track_id, t.title, t.genre, e.backend
                FROM tracks t
                LEFT JOIN track_embeddings e ON e.track_id = t.id
                WHERE t.track_id = :track_id
                """
            ),
            {"track_id": track_id},
        )
    ).mappings().first()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found.")

    row_id = track["id"]

    features = (
        await session.execute(
            text(
                """
                SELECT bpm, musical_key, mode, key_confidence, beat_strength,
                       energy, valence, danceability, acousticness,
                       spectral_centroid, spectral_bandwidth, spectral_rolloff,
                       spectral_flatness, zero_crossing_rate, rms_mean,
                       dynamic_range,
                       (raw->>'duration_sec')::float AS duration_sec
                FROM audio_features WHERE track_id = :id
                """
            ),
            {"id": row_id},
        )
    ).mappings().first()

    fatigue_row = (
        await session.execute(
            text(
                """
                SELECT fatigue_index, confidence, neighbor_count, density_recent,
                       density_slope, engagement_slope, components
                FROM fatigue_snapshots
                WHERE track_id = :id
                ORDER BY computed_at DESC
                LIMIT 1
                """
            ),
            {"id": row_id},
        )
    ).mappings().first()

    narrative_row = (
        await session.execute(
            text(
                """
                SELECT headline, narrative, actionable_insight, primary_drivers,
                       generation_mode, model, generated_at
                FROM narrative_insights
                WHERE track_id = :id
                ORDER BY generated_at DESC
                LIMIT 1
                """
            ),
            {"id": row_id},
        )
    ).mappings().first()

    # Fatigue verdict and explanation live on the snapshot's component blob so
    # the stored reading stays self-describing after the fact.
    fatigue_out = None
    if fatigue_row:
        components = fatigue_row["components"] or {}
        idx = float(fatigue_row["fatigue_index"])
        conf = float(fatigue_row["confidence"])
        if conf < 0.25:
            verdict = "low_confidence"
        elif idx >= 0.78:
            verdict = "saturated"
        elif idx >= 0.5:
            verdict = "warming"
        else:
            verdict = "open"

        fatigue_out = FatigueOut(
            fatigue_index=idx,
            confidence=conf,
            verdict=verdict,
            explanation=components.get("explanation")
            or _explain(verdict, idx, conf, fatigue_row["neighbor_count"]),
            neighbor_count=int(fatigue_row["neighbor_count"]),
            density_recent=float(fatigue_row["density_recent"]),
            density_slope=float(fatigue_row["density_slope"]),
            engagement_slope=float(fatigue_row["engagement_slope"]),
            components=components,
        )

    drivers: list[DriverOut] = []
    if narrative_row and narrative_row["primary_drivers"]:
        for d in narrative_row["primary_drivers"]:
            try:
                drivers.append(DriverOut(**d))
            except Exception:  # noqa: BLE001 — a malformed stored driver
                # should not take down the whole response.
                logger.warning("Skipping malformed driver payload: %s", d)

    return InsightResponse(
        track_id=track["track_id"],
        title=track["title"],
        genre=track["genre"],
        acoustic=AcousticSummary(**dict(features)) if features else None,
        fatigue=fatigue_out,
        drivers=drivers,
        narrative=NarrativeOut(**dict(narrative_row)) if narrative_row else None,
        embedding_backend=track["backend"],
    )


def _explain(verdict: str, idx: float, conf: float, n: int) -> str:
    if verdict == "low_confidence":
        return (
            f"Based on only {n} comparable track{'s' if n != 1 else ''} — "
            "directional at best until the corpus grows."
        )
    if verdict == "saturated":
        return f"Crowded sonic neighbourhood at {idx:.0%} saturation."
    if verdict == "warming":
        return f"Moderate saturation at {idx:.0%} and the window is narrowing."
    return f"Low saturation at {idx:.0%} — room to move."
