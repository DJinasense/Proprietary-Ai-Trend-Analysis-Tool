"""Shared machinery for ordinal chart sources (Deezer, Apple Music).

A chart is a different kind of source from a social feed, and the difference
matters to the rest of the pipeline.

A Bluesky post carries its own engagement number — likes, reposts, replies —
so `compute_velocity` can compare today's figure against that entity's trailing
median and get a meaningful "this is spiking" reading. A chart gives no such
number. It gives an *ordinal position*: this track is #7 today. Position 7 is
not an engagement count, and feeding it in raw would invert the whole signal —
the biggest hits would look like the smallest numbers.

So we translate position into a score that rises with prominence:

    score = (chart_size - position + 1) * CHART_SCORE_SCALE

Two consequences worth being explicit about, because they define what a
chart-derived driver actually means:

* A track parked at #1 for six weeks has a velocity of ~0. That is correct.
  It is popular, not *trending* — and MUSE's question is what is moving, not
  what is big. The Fatigue Index is where sustained saturation shows up.
* A track climbing #38 -> #6 produces a large positive velocity. That is the
  signal we actually want, and it emerges from the existing median-baseline
  machinery with no special-casing.

The first poll of any track yields velocity 0.0 (`compute_velocity` returns 0
without history), so a newly-charting track is not reported as an infinite
spike. It becomes reportable on the second sighting, once there is a baseline
to move against.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from muse.connectors.base import RawSignal
from muse.connectors.util import text_keywords

logger = logging.getLogger(__name__)

# Positions are small integers; multiplying keeps the derived engagement figures
# in the same order of magnitude as real like/play counts, so a chart entity and
# a Bluesky post do not sit on wildly different numeric scales when the
# correlation engine compresses velocity.
CHART_SCORE_SCALE = 100


def chart_score(position: int, chart_size: int) -> int:
    """Prominence score from an ordinal position. Higher is more prominent."""
    return max(chart_size - position + 1, 1) * CHART_SCORE_SCALE


def chart_entity(artist: str, title: str) -> str:
    """The canonical entity string for a charted track.

    "Artist — Title" rather than the title alone: chart titles collide
    constantly across artists ("Alright", "Stay", "Hold On"), and
    `compute_velocity` keys its baseline on the entity string. Collapsing two
    different songs into one entity would blend their histories and produce a
    velocity reading that describes neither.

    Every chart connector goes through here so that the same song observed on
    Deezer, Apple Music and Last.fm lands on one entity name. Baselines are
    per-platform, so this does not merge their engagement scales — it just
    means the correlation engine sees one track rather than three.
    """
    artist = (artist or "").strip()
    title = (title or "").strip()
    return f"{artist} — {title}" if artist else title


def keep_best(signals: list[RawSignal]) -> list[RawSignal]:
    """Collapse repeats of one entity within a poll, keeping the strongest.

    A track routinely appears on several charts at once — #1 global and #30 pop
    on Deezer, or in both the US and UK Apple feeds. Those share a `signal_id`
    (connector + platform + entity + hour), so without this the last one written
    silently wins and an entity's score depends on dict iteration order.

    The rule here is that an entity's standing for the hour is its *best*
    showing across the charts it appears on. Chart breadth then reads as
    strength rather than as noise, and the trailing median compares like with
    like poll after poll.
    """
    best: dict[str, RawSignal] = {}
    for sig in signals:
        key = sig.target_entity.lower()
        current = best.get(key)
        if current is None or sig.engagement_count > current.engagement_count:
            best[key] = sig
    return list(best.values())


def chart_signal(
    *,
    platform: str,
    title: str,
    artist: str,
    url: str,
    position: int,
    chart_size: int,
    extra_keywords: list[str] | None = None,
    raw: dict[str, Any] | None = None,
) -> RawSignal | None:
    """Build one chart entry into a RawSignal, or None if unusable."""
    title = (title or "").strip()
    artist = (artist or "").strip()
    if not title or not url:
        return None

    entity = chart_entity(artist, title)

    keywords = text_keywords(title, artist)
    for kw in extra_keywords or []:
        kw = (kw or "").strip().lower()
        if kw and kw not in keywords:
            keywords.append(kw)

    return RawSignal(
        platform=platform,
        target_entity=entity,
        entity_type="track",
        engagement_count=chart_score(position, chart_size),
        context_anchor_url=url,
        associated_keywords=keywords,
        raw={"position": position, "chart_size": chart_size, **(raw or {})},
    )


def describe_http_error(exc: Exception) -> str:
    """Status code only — never the URL.

    Same reasoning as the YouTube connector: some chart APIs take credentials
    as query parameters, and httpx's exception text embeds the full URL. A
    connector that leaks its own key into the logs on failure is worse than one
    that fails opaquely.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return f"{type(exc).__name__}: {exc}"
