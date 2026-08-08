"""Apple Music connector, via the public marketing RSS feeds.

No key and no account — the feeds are published for marketing use and served
as plain JSON.

Endpoint (verified live; note the host):

    GET https://rss.marketingtools.apple.com/api/v2/{country}/music/{feed}/{n}/songs.json
    -> {"feed": {"results": [{"name", "artistName", "url", "genres": [...]}]}}

The older `rss.applemarketingtools.com` host still resolves but now answers
301, and a client that does not follow redirects gets an empty body with no
error — which is exactly how this looked when first wired up. `follow_redirects`
is set below so a future host move degrades into a working request rather than
a silently empty connector.

`genres` is the reason this source earns its place alongside Deezer: Apple
tags every entry with its genre, which lands in `associated_keywords` and gives
the correlation engine a real music-domain term to match a track's genre
against.
"""

from __future__ import annotations

import logging

import httpx

from muse.config import settings
from muse.connectors.base import Connector, RawSignal
from muse.connectors.charts import chart_signal, describe_http_error, keep_best

logger = logging.getLogger(__name__)

API_BASE = "https://rss.marketingtools.apple.com/api/v2"
CHART_LIMIT = 50

# "most-played" is the only songs feed this API still serves — `top-songs`,
# `new-music-daily`, `hot-tracks` and `city-charts` all answer 404 as of
# 2026-08 (probed, not assumed). Kept as a tuple so restoring one is a one-line
# change if Apple brings it back.
FEEDS = ("most-played",)


class AppleMusicConnector(Connector):
    name = "apple_music"
    platform = "apple_music"

    @property
    def enabled(self) -> bool:
        # Human scene only — see the note in deezer.py; Apple's feeds expose no
        # provenance either.
        return settings.apple_music_enabled and settings.human_scene_enabled

    async def fetch(self) -> list[RawSignal]:
        if not self.enabled:
            return []

        countries = [
            c.strip().lower()
            for c in settings.apple_music_countries.split(",")
            if c.strip()
        ]

        signals: list[RawSignal] = []
        async with httpx.AsyncClient(follow_redirects=True) as client:
            for country in countries:
                for feed in FEEDS:
                    signals.extend(await self._fetch_feed(client, country, feed))

        # The same track sits in both feeds and in every country's chart. Keep
        # its strongest showing so breadth reads as strength, not as a coin toss
        # between the last two writes.
        signals = keep_best(signals)

        logger.info("Apple Music connector produced %d signals", len(signals))
        return signals

    async def _fetch_feed(
        self, client: httpx.AsyncClient, country: str, feed: str
    ) -> list[RawSignal]:
        try:
            resp = await client.get(
                f"{API_BASE}/{country}/music/{feed}/{CHART_LIMIT}/songs.json",
                timeout=25.0,
            )
            resp.raise_for_status()
            results = (resp.json().get("feed") or {}).get("results") or []
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Apple Music %s/%s fetch failed: %s",
                country, feed, describe_http_error(exc),
            )
            return []

        chart_size = len(results)

        out: list[RawSignal] = []
        for position, item in enumerate(results, start=1):
            genres = [
                g.get("name", "")
                for g in (item.get("genres") or [])
                # "Music" is on literally every entry and carries no information.
                if g.get("name") and g.get("name") != "Music"
            ]

            sig = chart_signal(
                platform=self.platform,
                title=item.get("name") or "",
                artist=item.get("artistName") or "",
                url=item.get("url") or "",
                position=position,
                chart_size=chart_size,
                extra_keywords=genres,
                raw={
                    "country": country,
                    "feed": feed,
                    "genres": genres,
                    "release_date": item.get("releaseDate"),
                    "apple_id": item.get("id"),
                },
            )
            if sig:
                out.append(sig)

        return out
