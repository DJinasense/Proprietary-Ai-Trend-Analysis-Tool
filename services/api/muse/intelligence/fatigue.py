"""The Fatigue Index.

── What the spec PDF did ─────────────────────────────────────────────────────
    mock_query_vec = np.random.uniform(-1, 1, 512).tolist()
    results = vector_index.query(vector=mock_query_vec, ...)
    mean_density = float(np.mean([m['score'] for m in results['matches']]))

That queries the index with a *random* vector and averages the cosine scores
of whatever comes back. In 512 dimensions, a random vector is near-orthogonal
to essentially everything, so those scores hover around zero regardless of
the track being analysed. The output is uncorrelated with the input. It is a
random number rendered as a percentage.

── What fatigue actually is ──────────────────────────────────────────────────
Market fatigue is a supply-and-response phenomenon, and it needs both halves:

    supply  ↑   — more and more tracks occupying this sonic neighbourhood
    response ↓  — yet each one earning less engagement than its predecessors

Either alone is a false positive. Rising supply with rising engagement is a
*boom*, not fatigue — that's a trend you want to ride. Falling engagement with
flat supply is just a quiet corner of the market. Fatigue is specifically the
scissors: crowd going up, payoff coming down.

So the index is built from three measured components:

  density_recent    Recency-weighted crowding of the neighbourhood right now.
                    Neighbours decay with a configurable half-life, so a genre
                    that was saturated two years ago and has since cleared out
                    does not read as saturated today.

  density_slope     Is that crowding accelerating? Recent window vs. prior
                    window. Catches a neighbourhood filling up fast even
                    before it is objectively crowded.

  engagement_slope  Is engagement per track in this neighbourhood rising or
                    falling? This is the half that makes it fatigue rather
                    than popularity. It enters the score negatively.

── Honesty about small corpora ───────────────────────────────────────────────
Every result carries a `confidence` derived from how many neighbours were
actually found and how many of them had engagement data. On a fresh install
with nine tracks, confidence is near zero and the API says so in plain words.
The number is never presented as authoritative when the evidence isn't there —
which is the whole complaint about opaque metrics that MUSE exists to answer.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from muse.config import settings

logger = logging.getLogger(__name__)

# Trailing windows for slope estimation.
RECENT_WINDOW_DAYS = 45
PRIOR_WINDOW_DAYS = 135  # i.e. the 90 days preceding the recent window

# Logistic weights. Tuned so that a moderately crowded neighbourhood with flat
# engagement lands near 0.5, and the scissors condition (crowding up,
# engagement down) pushes decisively past the 0.78 warning threshold.
W_DENSITY = 2.60
W_DENSITY_SLOPE = 1.15
W_ENGAGEMENT_SLOPE = 1.45
BIAS = -1.35

WARN_THRESHOLD = 0.78


@dataclass
class Neighbor:
    track_id: int
    title: str
    genre: str | None
    similarity: float
    age_days: float
    engagement: int


@dataclass
class FatigueResult:
    fatigue_index: float
    confidence: float
    neighbor_count: int
    density_recent: float
    density_slope: float
    engagement_slope: float
    components: dict[str, Any]
    verdict: str
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


NEIGHBOR_SQL = text(
    """
    WITH target AS (
        SELECT CAST(:vec AS vector) AS v
    )
    SELECT
        t.id                                        AS track_id,
        t.title                                     AS title,
        t.genre                                     AS genre,
        1 - (e.embedding <=> target.v)              AS similarity,
        EXTRACT(EPOCH FROM (now() - t.released_at)) / 86400.0 AS age_days,
        COALESCE(eng.total, 0)                      AS engagement
    FROM track_embeddings e
    JOIN tracks t ON t.id = e.track_id
    CROSS JOIN target
    LEFT JOIN LATERAL (
        -- Engagement attributable to this neighbour: any social signal whose
        -- keyword array overlaps the track's title or genre. GIN-indexed
        -- array overlap, not the full collection scan the spec's Mongo
        -- `$in` query would have performed.
        SELECT SUM(s.engagement_count) AS total
        FROM social_signals s
        -- array_remove drops the genre element when it is NULL. Do not
        -- reintroduce a COALESCE sentinel here: this is not a raw Python
        -- string, so a hex escape for a NUL byte becomes a real NUL in the
        -- SQL text, and the wire protocol truncates the message there.
        WHERE s.associated_keywords && array_remove(
                  ARRAY[lower(t.title), lower(t.genre)]::text[], NULL
              )
    ) eng ON TRUE
    WHERE e.backend = :backend
      AND e.track_id <> :self_id
      AND (1 - (e.embedding <=> target.v)) >= :radius
    ORDER BY e.embedding <=> target.v
    LIMIT :max_neighbors
    """
)


def _recency_weight(age_days: float, half_life: float) -> float:
    """Exponential decay. A neighbour one half-life old counts half as much."""
    if age_days <= 0:
        return 1.0
    return math.exp(-math.log(2.0) * age_days / max(half_life, 1e-6))


def _proximity(similarity: float, radius: float) -> float:
    """Rescale similarity from [radius, 1] onto [0, 1].

    A track sitting exactly on the inclusion boundary contributes nothing to
    crowding; a near-clone contributes fully. Without this, widening the
    radius would inflate density purely by admitting distant tracks.
    """
    if radius >= 1.0:
        return 1.0
    return max(0.0, min(1.0, (similarity - radius) / (1.0 - radius)))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _slope(recent: float, prior: float) -> float:
    """Relative change between windows, clipped to [-1, 1].

    Guarded so an empty prior window doesn't produce a division blow-up or a
    fake +100% reading: no prior evidence means no measurable slope.
    """
    if prior <= 1e-9:
        return 0.0 if recent <= 1e-9 else 0.5
    return max(-1.0, min(1.0, (recent - prior) / prior))


async def compute_fatigue(
    session: AsyncSession,
    *,
    track_id: int,
    embedding: list[float],
    backend: str,
) -> FatigueResult:
    """Compute the Fatigue Index for one track against the live corpus."""

    radius = settings.fatigue_neighbor_radius
    half_life = settings.fatigue_half_life_days
    min_neighbors = settings.fatigue_min_neighbors

    vec_literal = "[" + ",".join(f"{v:.6f}" for v in embedding) + "]"

    rows = (
        await session.execute(
            NEIGHBOR_SQL,
            {
                "vec": vec_literal,
                "backend": backend,
                "self_id": track_id,
                "radius": radius,
                "max_neighbors": settings.fatigue_max_neighbors,
            },
        )
    ).mappings().all()

    neighbors = [
        Neighbor(
            track_id=r["track_id"],
            title=r["title"],
            genre=r["genre"],
            similarity=float(r["similarity"]),
            age_days=float(r["age_days"]),
            engagement=int(r["engagement"] or 0),
        )
        for r in rows
    ]

    n = len(neighbors)

    # ── Insufficient corpus ───────────────────────────────────────────────
    # Return honestly rather than inventing a number. This is the branch that
    # fires on a fresh install, and it must never look like a real reading.
    if n == 0:
        return FatigueResult(
            fatigue_index=0.0,
            confidence=0.0,
            neighbor_count=0,
            density_recent=0.0,
            density_slope=0.0,
            engagement_slope=0.0,
            components={"reason": "no_neighbors"},
            verdict="insufficient_data",
            explanation=(
                "No comparable tracks in the corpus yet, so market saturation "
                "cannot be measured. This is a corpus-size limitation, not a "
                "finding that the sound is fresh."
            ),
        )

    # ── density_recent ────────────────────────────────────────────────────
    weighted_mass = sum(
        _proximity(nb.similarity, radius) * _recency_weight(nb.age_days, half_life)
        for nb in neighbors
    )
    # Saturating transform: crowding has diminishing marginal meaning. The
    # scale constant is min_neighbors, so "a full quorum of close, recent
    # neighbours" reads as roughly 63% dense.
    density_recent = 1.0 - math.exp(-weighted_mass / max(min_neighbors, 1))

    # ── density_slope ─────────────────────────────────────────────────────
    recent_mass = sum(
        _proximity(nb.similarity, radius)
        for nb in neighbors
        if nb.age_days <= RECENT_WINDOW_DAYS
    )
    prior_mass = sum(
        _proximity(nb.similarity, radius)
        for nb in neighbors
        if RECENT_WINDOW_DAYS < nb.age_days <= PRIOR_WINDOW_DAYS
    )
    density_slope = _slope(recent_mass, prior_mass)

    # ── engagement_slope ──────────────────────────────────────────────────
    # Mean engagement *per track* in each window. Per-track is the point: total
    # engagement naturally rises as more tracks enter, which would mask exactly
    # the decline we're looking for.
    recent_group = [nb for nb in neighbors if nb.age_days <= RECENT_WINDOW_DAYS]
    prior_group = [
        nb for nb in neighbors if RECENT_WINDOW_DAYS < nb.age_days <= PRIOR_WINDOW_DAYS
    ]
    recent_eng = (
        sum(nb.engagement for nb in recent_group) / len(recent_group)
        if recent_group
        else 0.0
    )
    prior_eng = (
        sum(nb.engagement for nb in prior_group) / len(prior_group)
        if prior_group
        else 0.0
    )
    engagement_slope = _slope(recent_eng, prior_eng)

    # ── Combine ───────────────────────────────────────────────────────────
    score = (
        W_DENSITY * density_recent
        + W_DENSITY_SLOPE * density_slope
        - W_ENGAGEMENT_SLOPE * engagement_slope
        + BIAS
    )
    fatigue_index = _sigmoid(score)

    # ── Confidence ────────────────────────────────────────────────────────
    corpus_coverage = 1.0 - math.exp(-n / max(min_neighbors, 1))
    with_engagement = sum(1 for nb in neighbors if nb.engagement > 0)
    engagement_coverage = with_engagement / n if n else 0.0
    # Engagement data is what separates fatigue from popularity, so its absence
    # is heavily penalised — without it we're only measuring crowding.
    confidence = 0.60 * corpus_coverage + 0.40 * engagement_coverage

    # ── Verdict ───────────────────────────────────────────────────────────
    if confidence < 0.25:
        verdict = "low_confidence"
        explanation = (
            f"Only {n} comparable track{'s' if n != 1 else ''} in the corpus"
            + (
                f", and {with_engagement} with engagement data. "
                if with_engagement
                else " and none with engagement data. "
            )
            + "Treat this reading as directional only — it will sharpen as the "
            "corpus grows."
        )
    elif fatigue_index >= WARN_THRESHOLD:
        verdict = "saturated"
        explanation = (
            f"This sonic neighbourhood is crowded ({density_recent:.0%} density) "
            f"and engagement per release is "
            f"{'falling' if engagement_slope < 0 else 'flat'}. "
            "Expect shorter organic tails than the raw trend line suggests."
        )
    elif fatigue_index >= 0.5:
        verdict = "warming"
        explanation = (
            f"Moderate crowding ({density_recent:.0%}) with supply "
            f"{'accelerating' if density_slope > 0.15 else 'stable'}. "
            "Still workable, but the window is narrowing."
        )
    else:
        verdict = "open"
        explanation = (
            f"Low saturation ({density_recent:.0%} density). "
            "Room to move in this sonic space."
        )

    components = {
        # Persisted alongside the numbers so a stored snapshot stays
        # self-describing — the reading can be read back months later without
        # re-deriving what the score meant at the time.
        "verdict": verdict,
        "explanation": explanation,
        "radius": radius,
        "half_life_days": half_life,
        "weighted_mass": round(weighted_mass, 4),
        "recent_mass": round(recent_mass, 4),
        "prior_mass": round(prior_mass, 4),
        "recent_engagement_per_track": round(recent_eng, 2),
        "prior_engagement_per_track": round(prior_eng, 2),
        "corpus_coverage": round(corpus_coverage, 4),
        "engagement_coverage": round(engagement_coverage, 4),
        "neighbors_with_engagement": with_engagement,
        "weights": {
            "density": W_DENSITY,
            "density_slope": W_DENSITY_SLOPE,
            "engagement_slope": -W_ENGAGEMENT_SLOPE,
            "bias": BIAS,
        },
        "nearest": [
            {
                "track_id": nb.track_id,
                "title": nb.title,
                "genre": nb.genre,
                "similarity": round(nb.similarity, 4),
                "age_days": round(nb.age_days, 1),
                "engagement": nb.engagement,
            }
            for nb in neighbors[:8]
        ],
    }

    logger.info(
        "Fatigue for track %s: %.3f (conf %.2f, n=%d, density=%.3f, "
        "d_slope=%.3f, e_slope=%.3f)",
        track_id, fatigue_index, confidence, n,
        density_recent, density_slope, engagement_slope,
    )

    return FatigueResult(
        fatigue_index=round(fatigue_index, 4),
        confidence=round(confidence, 4),
        neighbor_count=n,
        density_recent=round(density_recent, 4),
        density_slope=round(density_slope, 4),
        engagement_slope=round(engagement_slope, 4),
        components=components,
        verdict=verdict,
        explanation=explanation,
    )
