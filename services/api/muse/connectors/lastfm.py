"""Last.fm connector.

Last.fm is the odd one out among the chart sources, and in a useful way: it
reports *listener counts*, not just ordinal positions. `chart.getTopTracks` and
`geo.getTopTracks` both return `listeners` and `playcount`, so this connector
does not need `chart_score()` — it has real engagement numbers to hand to
`compute_velocity`.

One property of those numbers is worth stating plainly, because it changes how
a Last.fm velocity should be read. Last.fm's `listeners` is *cumulative* — the
number of distinct accounts that have ever scrobbled the track. It can rise and
it can plateau, but it essentially never falls. So a Last.fm velocity is a
growth rate, not a spike-and-decay curve: a catalogue track sits near 0% while a
breaking track climbs fast. That is genuinely the signal we want here, but it
means a negative Last.fm velocity is not a thing, and the narrative layer should
not be read as saying a track "declined" on this platform.

Auth: a plain API key, passed as a query parameter. That is exactly the failure
mode that put the YouTube key into the container logs, so every error path here
goes through `describe_http_error`, which reports the status code and nothing
that could carry the URL.

    GET https://ws.audioscrobbler.com/2.0/
        ?method=chart.gettoptracks&api_key=…&format=json&limit=N
    -> {"tracks": {"track": [{"name", "artist": {"name"}, "url",
                              "listeners", "playcount"}]}}
"""

from __future__ import annotations

import logging

import httpx

from muse.config import settings
from muse.connectors.base import Connector, RawSignal
from muse.connectors.charts import chart_entity, describe_http_error, keep_best
from muse.connectors.util import text_keywords

logger = logging.getLogger(__name__)

API_BASE = "https://ws.audioscrobbler.com/2.0/"
CHART_LIMIT = 50


class LastFmConnector(Connector):
    name = "lastfm"
    platform = "lastfm"

    @property
    def enabled(self) -> bool:
        # Human scene only — see the note in deezer.py.
        return bool(settings.lastfm_api_key.strip()) and settings.human_scene_enabled

    async def fetch(self) -> list[RawSignal]:
        if not self.enabled:
            return []

        countries = [
            c.strip()
            for c in settings.lastfm_countries.split(",")
            if c.strip()
        ]

        signals: list[RawSignal] = []
        async with httpx.AsyncClient() as client:
            signals.extend(
                await self._fetch(client, "chart.gettoptracks", {}, scope="global")
            )
            for country in countries:
                signals.extend(
                    await self._fetch(
                        client,
                        "geo.gettoptracks",
                        {"country": country},
                        scope=country,
                    )
                )

        # The global chart and every geo chart overlap heavily. `listeners` is a
        # worldwide figure, so the global reading is the same number wherever it
        # is seen — keeping the best is what makes the per-entity baseline
        # stable rather than dependent on which chart was polled last.
        signals = keep_best(signals)

        logger.info("Last.fm connector produced %d signals", len(signals))
        return signals

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        method: str,
        params: dict[str, str],
        *,
        scope: str,
    ) -> list[RawSignal]:
        try:
            resp = await client.get(
                API_BASE,
                params={
                    "method": method,
                    "api_key": settings.lastfm_api_key.strip(),
                    "format": "json",
                    "limit": CHART_LIMIT,
                    **params,
                },
                timeout=25.0,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            # A bad key comes back as a bare 403, which on its own reads like a
            # network or blocking problem. Say what it actually is — this is the
            # first thing anyone wiring up the connector will hit.
            hint = ""
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 403:
                hint = " — MUSE_LASTFM_API_KEY is rejected"
            logger.warning(
                "Last.fm %s (%s) fetch failed: %s%s",
                method, scope, describe_http_error(exc), hint,
            )
            return []

        # Last.fm reports its own errors in the body, sometimes alongside a 200.
        # Code 10 is an invalid key and 26 a suspended one — both mean the
        # connector is dead until the key is fixed, so say which.
        if isinstance(payload, dict) and payload.get("error"):
            logger.warning(
                "Last.fm %s (%s) returned API error code %s — check MUSE_LASTFM_API_KEY",
                method, scope, payload.get("error"),
            )
            return []

        items = ((payload or {}).get("tracks") or {}).get("track") or []

        out: list[RawSignal] = []
        for item in items:
            title = (item.get("name") or "").strip()
            artist = ((item.get("artist") or {}).get("name") or "").strip()
            url = item.get("url") or ""
            if not title or not url:
                continue

            # Prefer listeners over playcount: playcount is dominated by a
            # small number of heavy repeat listeners, while listeners counts
            # distinct people and so tracks reach rather than obsession.
            listeners = _as_int(item.get("listeners"))
            playcount = _as_int(item.get("playcount"))
            engagement = listeners or playcount
            if engagement <= 0:
                continue

            keywords = text_keywords(title, artist)
            if scope != "global" and scope.lower() not in keywords:
                keywords.append(scope.lower())

            out.append(
                RawSignal(
                    platform=self.platform,
                    target_entity=chart_entity(artist, title),
                    entity_type="track",
                    engagement_count=engagement,
                    context_anchor_url=url,
                    associated_keywords=keywords,
                    raw={
                        "scope": scope,
                        "method": method,
                        "listeners": listeners,
                        "playcount": playcount,
                        "mbid": item.get("mbid") or None,
                    },
                )
            )

        return out


def _as_int(value: object) -> int:
    """Last.fm returns counts as strings, and occasionally as empty strings."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0
