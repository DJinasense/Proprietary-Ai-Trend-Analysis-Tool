"""Connector contract.

Every social source implements this one interface. That is the whole point of
the abstraction: the v1 sources (Reddit, YouTube, Bluesky, Google Trends) are
free and open, and when a licensed TikTok/Instagram aggregator is added later
— Soundcharts, Songstats, Chartmetric — it becomes one more file implementing
`Connector.fetch()`. Nothing downstream of this module changes.

`context_anchor_url` is mandatory on every signal. A connector that cannot
say where a datapoint came from cannot emit it.
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class RawSignal:
    """One observation from a social source, before velocity is computed."""

    platform: str
    target_entity: str
    entity_type: str
    engagement_count: int
    context_anchor_url: str
    associated_keywords: list[str]
    observed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    raw: dict[str, Any] = field(default_factory=dict)

    def signal_id(self, connector: str) -> str:
        """Stable id so re-polling the same entity in the same hour upserts
        rather than duplicating."""
        bucket = self.observed_at.strftime("%Y%m%d%H")
        key = f"{connector}:{self.platform}:{self.target_entity}:{bucket}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()


class Connector(ABC):
    """Base class for all social sources."""

    name: str = "unnamed"
    platform: str = "unknown"

    @property
    @abstractmethod
    def enabled(self) -> bool:
        """False when the required credentials are absent. Disabled
        connectors are skipped silently rather than raising — a missing
        YouTube key should not stop Reddit from running."""

    @abstractmethod
    async def fetch(self) -> list[RawSignal]:
        """Pull current observations. Must not raise; return [] on failure."""

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "platform": self.platform,
            "enabled": self.enabled,
        }


BASELINE_SQL = text(
    """
    SELECT
        percentile_cont(0.5) WITHIN GROUP (ORDER BY engagement_count) AS median,
        COUNT(*) AS n
    FROM social_signals
    WHERE platform = :platform
      AND lower(target_entity) = lower(:entity)
      AND observed_at >= now() - INTERVAL '21 days'
      AND observed_at < now() - INTERVAL '1 hour'
    """
)


async def compute_velocity(
    session: AsyncSession,
    *,
    platform: str,
    entity: str,
    engagement: int,
) -> float:
    """Percentage change against this entity's own trailing median.

    Median rather than mean because social engagement is heavy-tailed — one
    viral day would otherwise poison the baseline for weeks and suppress every
    subsequent spike.

    Returns 0.0 when there is no history. A first sighting is not a spike, and
    reporting it as +100% would flood the narrative layer with phantom drivers
    every time a new entity appears.
    """
    row = (
        await session.execute(
            BASELINE_SQL, {"platform": platform, "entity": entity}
        )
    ).mappings().first()

    if not row or not row["n"] or row["n"] < 2:
        return 0.0

    median = float(row["median"] or 0.0)
    if median <= 0:
        return 0.0

    return round(((engagement - median) / median) * 100.0, 2)


UPSERT_SQL = text(
    """
    INSERT INTO social_signals (
        signal_id, platform, connector, target_entity, entity_type,
        velocity_spike_pct, engagement_count, associated_keywords,
        context_anchor_url, observed_at, raw
    )
    VALUES (
        :signal_id, :platform, :connector, :target_entity, :entity_type,
        :velocity_spike_pct, :engagement_count, CAST(:associated_keywords AS text[]),
        :context_anchor_url, :observed_at, CAST(:raw AS jsonb)
    )
    ON CONFLICT (signal_id) DO UPDATE SET
        velocity_spike_pct = EXCLUDED.velocity_spike_pct,
        engagement_count   = EXCLUDED.engagement_count,
        associated_keywords = EXCLUDED.associated_keywords,
        raw                = EXCLUDED.raw
    """
)


async def persist_signals(
    session: AsyncSession,
    connector: Connector,
    signals: list[RawSignal],
) -> int:
    """Compute velocity for each signal and upsert. Returns rows written."""
    import json

    written = 0
    for sig in signals:
        if not sig.context_anchor_url:
            logger.warning(
                "%s emitted a signal with no anchor URL (%s) — dropped",
                connector.name, sig.target_entity,
            )
            continue

        velocity = await compute_velocity(
            session,
            platform=sig.platform,
            entity=sig.target_entity,
            engagement=sig.engagement_count,
        )

        await session.execute(
            UPSERT_SQL,
            {
                "signal_id": sig.signal_id(connector.name),
                "platform": sig.platform,
                "connector": connector.name,
                "target_entity": sig.target_entity,
                "entity_type": sig.entity_type,
                "velocity_spike_pct": velocity,
                "engagement_count": sig.engagement_count,
                "associated_keywords": [k.lower() for k in sig.associated_keywords],
                "context_anchor_url": sig.context_anchor_url,
                "observed_at": sig.observed_at,
                "raw": json.dumps(sig.raw, default=str),
            },
        )
        written += 1

    await session.commit()
    return written
