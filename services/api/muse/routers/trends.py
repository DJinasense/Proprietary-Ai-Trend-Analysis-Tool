"""Live social signals and corpus health."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from muse.config import settings
from muse.db import get_session
from muse.schemas import CorpusStats, SignalOut

router = APIRouter(prefix="/api/trends", tags=["trends"])


# The scene a caller asks for. Omitting it returns both, which is the honest
# default for a board that tracks two worlds — a UI that wants them separated
# should say so rather than getting one silently.
SceneParam = Query(
    None,
    pattern="^(human|ai)$",
    description="Filter to one scene: 'human' or 'ai'. Omit for both.",
)


@router.get("/signals", response_model=list[SignalOut])
async def recent_signals(
    limit: int = Query(50, le=200),
    platform: str | None = None,
    scene: str | None = SceneParam,
    session: AsyncSession = Depends(get_session),
) -> list[SignalOut]:
    """Most recent social signals, optionally filtered by platform and scene."""
    rows = (
        await session.execute(
            text(
                """
                SELECT platform, connector, target_entity, entity_type,
                       velocity_spike_pct, engagement_count,
                       context_anchor_url, scene, observed_at
                FROM social_signals
                -- The CASTs are load-bearing. `$n IS NULL` gives asyncpg
                -- nothing to infer a type from, and it raises
                -- AmbiguousParameterError before Postgres ever reaches the
                -- `col = $n` half that would have settled it. Without the cast
                -- this endpoint 500s on every call, filter or no filter.
                WHERE (CAST(:platform AS text) IS NULL OR platform = :platform)
                  AND (CAST(:scene AS text) IS NULL OR scene = :scene)
                ORDER BY observed_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit, "platform": platform, "scene": scene},
        )
    ).mappings().all()
    return [SignalOut(**dict(r)) for r in rows]


@router.get("/spikes", response_model=list[SignalOut])
async def top_spikes(
    hours: int = Query(48, le=720),
    limit: int = Query(25, le=100),
    scene: str | None = SceneParam,
    session: AsyncSession = Depends(get_session),
) -> list[SignalOut]:
    """Highest-velocity movers in the window — the live trend board.

    Velocity is computed per scene, so `?scene=ai` is a ranking *within* the AI
    scene rather than AI entries pulled out of a shared leaderboard. The two
    scenes carry very different engagement magnitudes; comparing their raw
    positions against each other would not mean anything.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT platform, connector, target_entity, entity_type,
                       velocity_spike_pct, engagement_count,
                       context_anchor_url, scene, observed_at
                FROM social_signals
                -- make_interval() rather than casting a string parameter to
                -- interval: asyncpg binds such a parameter as a native
                -- interval and rejects a Python str outright. Note also that
                -- text() scans comments for bind parameters, so a colon-
                -- prefixed name must not appear even in this comment.
                WHERE observed_at >= now() - make_interval(hours => :hours)
                  AND velocity_spike_pct > 0
                  -- CAST here is load-bearing: `$n IS NULL` gives asyncpg
                  -- nothing to infer a type from, and it raises
                  -- AmbiguousParameterError before Postgres ever sees the
                  -- `scene = $n` half that would have settled it.
                  AND (CAST(:scene AS text) IS NULL OR scene = :scene)
                ORDER BY velocity_spike_pct DESC
                LIMIT :limit
                """
            ),
            {"hours": int(hours), "limit": limit, "scene": scene},
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

    scenes = (
        await session.execute(
            text(
                """
                SELECT scene,
                       COUNT(*) AS signals,
                       COUNT(*) FILTER (
                           WHERE observed_at >= now() - INTERVAL '24 hours'
                       ) AS signals_24h,
                       MAX(observed_at) AS latest
                FROM social_signals
                GROUP BY scene
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
        scenes=[
            {
                "scene": s["scene"],
                "signals": int(s["signals"]),
                "signals_last_24h": int(s["signals_24h"]),
                "latest": s["latest"].isoformat() if s["latest"] else None,
            }
            for s in scenes
        ],
        fatigue_ready=ready,
        fatigue_ready_message=message,
    )
