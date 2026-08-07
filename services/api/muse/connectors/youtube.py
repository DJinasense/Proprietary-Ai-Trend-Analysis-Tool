"""YouTube connector.

YouTube Data API v3 — the most-popular chart for the Music category (id 10),
plus a search pass over recently-uploaded music. Official, free within the
default 10,000 units/day quota.

Quota note: `videos.list` costs 1 unit, `search.list` costs 100. The search
pass is therefore run once per cycle with a tight result cap, and the chart
pass carries most of the load.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from muse.config import settings
from muse.connectors.base import Connector, RawSignal
from muse.connectors.util import text_keywords

logger = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/youtube/v3"
MUSIC_CATEGORY_ID = "10"


class YouTubeConnector(Connector):
    name = "youtube"
    platform = "youtube"

    @property
    def enabled(self) -> bool:
        return bool(settings.youtube_api_key)

    async def fetch(self) -> list[RawSignal]:
        if not self.enabled:
            return []

        signals: list[RawSignal] = []
        async with httpx.AsyncClient() as client:
            signals.extend(await self._fetch_chart(client))
            signals.extend(await self._fetch_recent(client))

        logger.info("YouTube connector produced %d signals", len(signals))
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
            logger.warning("YouTube chart fetch failed: %s", exc)
            return []

        return [self._to_signal(item) for item in items if self._to_signal(item)]

    async def _fetch_recent(self, client: httpx.AsyncClient) -> list[RawSignal]:
        """Recently-uploaded music, ordered by view count. 100 quota units."""
        published_after = (
            datetime.now(timezone.utc) - timedelta(days=7)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            resp = await client.get(
                f"{API_BASE}/search",
                params={
                    "part": "snippet",
                    "type": "video",
                    "videoCategoryId": MUSIC_CATEGORY_ID,
                    "order": "viewCount",
                    "publishedAfter": published_after,
                    "maxResults": 25,
                    "key": settings.youtube_api_key,
                },
                timeout=25.0,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("YouTube search fetch failed: %s", exc)
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
            logger.warning("YouTube stats hydration failed: %s", exc)
            return []

        out = []
        for item in hydrated:
            sig = self._to_signal(item)
            if sig:
                out.append(sig)
        return out

    def _to_signal(self, item: dict) -> RawSignal | None:
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

        return RawSignal(
            platform=self.platform,
            target_entity=title[:120],
            entity_type="video",
            # Views dominate by orders of magnitude; likes and comments are
            # weighted up so active engagement isn't lost in the rounding.
            engagement_count=views + (likes * 10) + (comments * 25),
            context_anchor_url=f"https://www.youtube.com/watch?v={video_id}",
            associated_keywords=text_keywords(
                title,
                snippet.get("channelTitle") or "",
                " ".join(snippet.get("tags") or []),
            ),
            observed_at=observed,
            raw={
                "video_id": video_id,
                "channel": snippet.get("channelTitle"),
                "views": views,
                "likes": likes,
                "comments": comments,
            },
        )
