"""Deezer connector.

Deezer's public API needs no authentication of any kind — no key, no OAuth, no
account. That is unusual enough to be worth stating plainly: there is nothing
to put in `.env`, nothing to rotate, and nothing that can leak.

Endpoint (verified live against the shape below):

    GET https://api.deezer.com/chart/{genre_id}/tracks?limit=N
    -> {"data": [{"title", "artist": {"name"}, "link", "position", "rank", ...}]}

Genre 0 is the global "all genres" chart. The per-genre charts use Deezer's own
genre ids, which is why they are listed explicitly rather than guessed — an
unknown id returns an empty `data` array rather than an error, so a typo would
show up as a silently dead source.
"""

from __future__ import annotations

import logging

import httpx

from muse.config import settings
from muse.connectors.base import Connector, RawSignal
from muse.connectors.charts import chart_signal, describe_http_error, keep_best

logger = logging.getLogger(__name__)

API_BASE = "https://api.deezer.com"
CHART_LIMIT = 50

# Deezer genre ids. 0 is the global chart; the rest are the lanes most likely
# to matter to a producer using MUSE. Adding one is a one-line change.
GENRES: dict[int, str] = {
    0: "global",
    132: "pop",
    116: "rap-hiphop",
    113: "dance",
    152: "rock",
    106: "electro",
    165: "rnb",
}


class DeezerConnector(Connector):
    name = "deezer"
    platform = "deezer"

    @property
    def enabled(self) -> bool:
        # Chart sources sample the human scene only — nothing in a Deezer chart
        # entry says whether a track was machine-made, so this connector has no
        # AI reading to offer and is skipped outright when the human scene is
        # off, rather than polling and having its output discarded.
        return settings.deezer_enabled and settings.human_scene_enabled

    async def fetch(self) -> list[RawSignal]:
        if not self.enabled:
            return []

        signals: list[RawSignal] = []
        async with httpx.AsyncClient() as client:
            for genre_id, genre_name in GENRES.items():
                signals.extend(await self._fetch_chart(client, genre_id, genre_name))

        # A hit shows up on the global chart and on its genre chart at once.
        # Keep its strongest showing rather than whichever chart was polled last.
        signals = keep_best(signals)

        logger.info("Deezer connector produced %d signals", len(signals))
        return signals

    async def _fetch_chart(
        self, client: httpx.AsyncClient, genre_id: int, genre_name: str
    ) -> list[RawSignal]:
        try:
            resp = await client.get(
                f"{API_BASE}/chart/{genre_id}/tracks",
                params={"limit": CHART_LIMIT},
                timeout=25.0,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Deezer chart %s fetch failed: %s", genre_name, describe_http_error(exc)
            )
            return []

        # Deezer signals errors in-band with HTTP 200 and an "error" object.
        if isinstance(payload, dict) and payload.get("error"):
            code = (payload["error"] or {}).get("code", "?")
            logger.warning("Deezer chart %s returned error code %s", genre_name, code)
            return []

        items = (payload or {}).get("data") or []
        chart_size = len(items)

        out: list[RawSignal] = []
        for idx, item in enumerate(items, start=1):
            # `position` is Deezer's own field; fall back to enumeration order
            # if a payload ever omits it.
            position = int(item.get("position") or idx)

            sig = chart_signal(
                platform=self.platform,
                title=item.get("title_short") or item.get("title") or "",
                artist=(item.get("artist") or {}).get("name", ""),
                url=item.get("link") or "",
                position=position,
                chart_size=chart_size,
                extra_keywords=[genre_name] if genre_name != "global" else [],
                raw={
                    "genre": genre_name,
                    "deezer_rank": item.get("rank"),
                    "track_id": item.get("id"),
                },
            )
            if sig:
                out.append(sig)

        return out
