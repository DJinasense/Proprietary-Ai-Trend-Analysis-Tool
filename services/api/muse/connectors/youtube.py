"""YouTube connector.

YouTube Data API v3 — the most-popular chart for the Music category (id 10),
plus search passes over recently-uploaded music. Official, free within the
default 10,000 units/day quota.

**Quota is the binding constraint here, and it is tight.** `videos.list` costs
1 unit; `search.list` costs 100. At the 900s ingest interval there are 96 cycles
a day, so a single search on every cycle is 9,600 units — 96% of the daily cap
on its own, before the AI scene adds a second search pass. Running both every
cycle would exceed the quota outright and the connector would spend the back
half of each day returning `quotaExceeded`.

So the searches run on their own, slower clock
(`MUSE_YOUTUBE_SEARCH_MIN_INTERVAL_SECONDS`, default 3600s) while the chart pass
keeps polling every cycle at 1 unit a time. That is the right trade: the chart
is where the movement actually shows up, and a search for week-old uploads
ordered by view count does not change meaningfully in fifteen minutes. Budget
at the default: 96 chart polls + 24 runs of each search pass with their
hydration ≈ 4,950 units/day.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from muse.config import settings
from muse.connectors import scenes
from muse.connectors.base import Connector, RawSignal
from muse.connectors.scenes import scene_for
from muse.connectors.util import text_keywords

logger = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/youtube/v3"
MUSIC_CATEGORY_ID = "10"


class YouTubeConnector(Connector):
    name = "youtube"
    platform = "youtube"

    def __init__(self) -> None:
        # None means "never searched", so the first cycle after start always
        # runs one rather than waiting out a full interval.
        self._last_search: float | None = None

    @property
    def enabled(self) -> bool:
        return bool(settings.youtube_api_key)

    def _search_due(self) -> bool:
        if self._last_search is None:
            return True
        elapsed = time.monotonic() - self._last_search
        return elapsed >= settings.youtube_search_min_interval_seconds

    async def fetch(self) -> list[RawSignal]:
        if not self.enabled:
            return []

        signals: list[RawSignal] = []
        async with httpx.AsyncClient() as client:
            if settings.human_scene_enabled:
                signals.extend(await self._fetch_chart(client))

            if self._search_due():
                # Stamp before the calls, not after: a search that fails still
                # spent its quota, and retrying it every 15 minutes because it
                # errored is exactly how the daily cap gets burned.
                self._last_search = time.monotonic()
                if settings.human_scene_enabled:
                    signals.extend(await self._fetch_recent(client))
                if settings.ai_scene_enabled:
                    signals.extend(await self._fetch_ai(client))

        by_scene: dict[str, int] = {}
        for s in signals:
            by_scene[s.scene] = by_scene.get(s.scene, 0) + 1
        logger.info(
            "YouTube connector produced %d signals (%s)",
            len(signals),
            ", ".join(f"{k}={v}" for k, v in sorted(by_scene.items())) or "none",
        )
        return signals

    async def _fetch_chart(self, client: httpx.AsyncClient) -> list[RawSignal]:
        """Most-popular music videos. 1 quota unit."""
        try:
            resp = await client.get(
                f"{API_BASE}/videos",
                params={
                    "part": "snippet,statistics",
                    "chart": "mostPopular",
                    "videoCategoryId": MUSIC_CATEGORY_ID,
                    "regionCode": "US",
                    "maxResults": 50,
                    "key": settings.youtube_api_key,
                },
                timeout=25.0,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("YouTube chart fetch failed: %s", _describe_error(exc))
            return []

        return self._to_signals(items, scenes.HUMAN)

    async def _fetch_recent(self, client: httpx.AsyncClient) -> list[RawSignal]:
        """Recently-uploaded music, ordered by view count. 100 quota units."""
        return await self._search_pass(
            client,
            label="recent",
            scene=scenes.HUMAN,
            extra_params={"videoCategoryId": MUSIC_CATEGORY_ID},
        )

    async def _fetch_ai(self, client: httpx.AsyncClient) -> list[RawSignal]:
        """Recently-uploaded AI music. 100 quota units.

        Deliberately *not* restricted to the Music category. AI tracks are
        uploaded under Entertainment, People & Blogs and Science & Technology at
        least as often as under Music, and the category filter would drop most
        of the scene. The query terms are specific enough to carry it alone.
        """
        return await self._search_pass(
            client,
            label="ai",
            scene=scenes.AI,
            extra_params={"q": scenes.AI_YOUTUBE_QUERY},
        )

    async def _search_pass(
        self,
        client: httpx.AsyncClient,
        *,
        label: str,
        scene: str,
        extra_params: dict[str, str],
    ) -> list[RawSignal]:
        published_after = (
            datetime.now(timezone.utc) - timedelta(days=7)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            resp = await client.get(
                f"{API_BASE}/search",
                params={
                    "part": "snippet",
                    "type": "video",
                    "order": "viewCount",
                    "publishedAfter": published_after,
                    "maxResults": 25,
                    "key": settings.youtube_api_key,
                    **extra_params,
                },
                timeout=25.0,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "YouTube %s search failed: %s", label, _describe_error(exc)
            )
            return []

        # search.list omits statistics, so hydrate view counts in one batched
        # videos.list call rather than N separate ones.
        video_ids = [
            i["id"]["videoId"]
            for i in items
            if i.get("id", {}).get("videoId")
        ]
        if not video_ids:
            return []

        try:
            stats_resp = await client.get(
                f"{API_BASE}/videos",
                params={
                    "part": "snippet,statistics",
                    "id": ",".join(video_ids),
                    "key": settings.youtube_api_key,
                },
                timeout=25.0,
            )
            stats_resp.raise_for_status()
            hydrated = stats_resp.json().get("items", [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("YouTube stats hydration failed: %s", _describe_error(exc))
            return []

        return self._to_signals(hydrated, scene)

    def _to_signals(self, items: list[dict], scene: str) -> list[RawSignal]:
        out: list[RawSignal] = []
        for item in items:
            sig = self._to_signal(item, scene)
            if sig:
                out.append(sig)
        return out

    def _to_signal(self, item: dict, scene: str) -> RawSignal | None:
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        video_id = item.get("id")
        title = (snippet.get("title") or "").strip()

        if not video_id or not title:
            return None

        views = int(stats.get("viewCount", 0) or 0)
        likes = int(stats.get("likeCount", 0) or 0)
        comments = int(stats.get("commentCount", 0) or 0)

        published = snippet.get("publishedAt")
        try:
            observed = (
                datetime.fromisoformat(published.replace("Z", "+00:00"))
                if published
                else datetime.now(timezone.utc)
            )
        except ValueError:
            observed = datetime.now(timezone.utc)

        channel = snippet.get("channelTitle") or ""
        tags = " ".join(snippet.get("tags") or [])

        # The chart pass has no AI query behind it, so a "Made with Suno" video
        # that charts arrives here labelled human. Titles, channel names and
        # tags are where uploaders say so, and that self-labelling is the only
        # provenance YouTube exposes.
        scene = scene_for(title, channel, tags, default=scene)

        return RawSignal(
            platform=self.platform,
            target_entity=title[:120],
            entity_type="video",
            # Views dominate by orders of magnitude; likes and comments are
            # weighted up so active engagement isn't lost in the rounding.
            engagement_count=views + (likes * 10) + (comments * 25),
            context_anchor_url=f"https://www.youtube.com/watch?v={video_id}",
            associated_keywords=text_keywords(title, channel, tags),
            scene=scene,
            observed_at=observed,
            raw={
                "video_id": video_id,
                "channel": snippet.get("channelTitle"),
                "scene": scene,
                "views": views,
                "likes": likes,
                "comments": comments,
            },
        )


def _describe_error(exc: Exception) -> str:
    """Status code and Google's reason string only — never the URL.

    The API key travels as a `key=` query parameter, so httpx's exception text
    (which embeds the full request URL) would write the live credential into
    the logs on every failure. Reason codes are what actually diagnose these:
    `API_KEY_INVALID` means a wrong or malformed key, `keyInvalid` a key
    restricted away from this API, `quotaExceeded` the 10,000 unit/day cap.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        reason = ""
        try:
            err = exc.response.json().get("error", {})
            details = err.get("errors") or []
            reason = (details[0].get("reason") if details else "") or err.get("status", "")
        except Exception:  # noqa: BLE001
            pass
        code = exc.response.status_code
        return f"HTTP {code}{f' ({reason})' if reason else ''}"
    return f"{type(exc).__name__}: {exc}"
