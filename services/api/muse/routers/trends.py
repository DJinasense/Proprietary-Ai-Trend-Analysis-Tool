"""Live social signals and corpus health."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from muse.config import settings
from muse.db import get_session
from muse.schemas import CorpusStats, SignalOut

router = APIRouter(prefix="/api/trends", tags=["trends"])


@router.get("/signals", response_model=list[SignalOut])
async def recent_signals(
    limit: int = Query(50, le=200),
    platform: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[SignalOut]:
    """Most recent social signals, optionally filtered by platform."""
    rows = (
        await session.execute(
            text(
                """
                SELECT platform, connector, target_entity, entity_type,
                       velocity_spike_pct, engagement_count,
                       context_anchor_url, observed_at
                FROM social_signals
                WHERE (:platform IS NULL OR platform = :platform)
                ORDER BY observed_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit, "platform": platform},
        )
    ).mappings().all()
    return [SignalOut(**dict(r)) for r in rows]


@router.get("/spikes", response_model=list[SignalOut])
async def top_spikes(
    hours: int = Query(48, le=720),
    limit: int = Query(25, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[SignalOut]:
    """Highest-velocity movers in the window — the live trend board."""
    rows = (
        await session.execute(
            text(
                """
                SELECT platform, connector, target_entity, entity_type,
                       velocity_spike_pct, engagement_count,
                       context_anchor_url, observed_at
                FROM social_signals
                -- make_interval() rather than casting a string parameter to
                -- interval: asyncpg binds such a parameter as a native
                -- interval and rejects a Python str outright. Note also that
                -- text() scans comments for bind parameters, so a colon-
                -- prefixed name must not appear even in this comment.
                WHERE observed_at >= now() - make_interval(hours => :hours)
                  AND velocity_spike_pct > 0
                ORDER BY velocity_spike_pct DESC
                LIMIT :limit
                """
            ),
            {"hours": int(hours), "limit": limit},
        )
    ).mappings().all()
    return [SignalOut(**dict(r)) for r in rows]


@router.get("/corpus", response_model=CorpusStats)
async def corpus_stats(session: AsyncSession = Depends(get_session)) -> CorpusStats:
    """Corpus health.

    Surfaced in the UI because the Fatigue Index is only as good as the
    comparison set behind it. Users should be able to see exactly how much
    evidence their readings rest on rather than having to infer it from a
    confidence number.
    """
    counts = (
        await session.execute(
            text(
                """
                SELECT
                    (SELECT COUNT(*) FROM tracks)            AS tracks,
                    (SELECT COUNT(*) FROM track_embeddings)  AS embedded,
                    (SELECT COUNT(*) FROM social_signals)    AS signals,
                    (SELECT COUNT(*) FROM social_signals
                     WHERE observed_at >= now() - INTERVAL '24 hours') AS signals_24h
                """
            )
        )
    ).mappings().one()

    platforms = (
        await session.execute(
            text(
                """
                SELECT platform,
                       COUNT(*) AS signals,
                       MAX(observed_at) AS latest
                FROM social_signals
                GROUP BY platform
                ORDER BY signals DESC
                """
            )
        )
    ).mappings().all()

    embedded = int(counts["embedded"])
    threshold = settings.fatigue_min_neighbors
    ready = embedded >= threshold

    if ready:
        message = (
            f"{embedded} tracks embedded — saturation readings are supported."
        )
    else:
        message = (
            f"{embedded} of {threshold} tracks needed for reliable saturation "
            "readings. Analyses will run, but the Fatigue Index will report "
            "low confidence until the corpus grows."
        )

    return CorpusStats(
        tracks=int(counts["tracks"]),
        tracks_with_embeddings=embedded,
        social_signals=int(counts["signals"]),
        signals_last_24h=int(counts["signals_24h"]),
        platforms=[
            {
                "platform": p["platform"],
                "signals": int(p["signals"]),
                "latest": p["latest"].isoformat() if p["latest"] else None,
            }
            for p in platforms
        ],
        fatigue_ready=ready,
        fatigue_ready_message=message,
    )
