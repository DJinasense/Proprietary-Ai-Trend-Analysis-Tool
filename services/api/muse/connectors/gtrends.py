"""Google Trends connector.

Reads the public daily-trends RSS feed. This is a public endpoint but *not* a
documented, supported API — Google has changed its shape before and will
again. It is therefore treated as strictly best-effort: parse failures are
logged and swallowed, and nothing downstream depends on it being present.

Set MUSE_GOOGLE_TRENDS_ENABLED=false to switch it off entirely.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote_plus

import httpx

from muse.config import settings
from muse.connectors.base import Connector, RawSignal
from muse.connectors.scenes import scene_for
from muse.connectors.util import text_keywords

logger = logging.getLogger(__name__)

RSS_URL = "https://trends.google.com/trending/rss"
NS = {"ht": "https://trends.google.com/trending/rss"}

REGIONS = ["US", "GB"]


def _parse_traffic(value: str | None) -> int:
    """'200K+' -> 200000, '1M+' -> 1000000."""
    if not value:
        return 0
    v = value.strip().replace("+", "").replace(",", "").upper()
    multiplier = 1
    if v.endswith("K"):
        multiplier, v = 1_000, v[:-1]
    elif v.endswith("M"):
        multiplier, v = 1_000_000, v[:-1]
    try:
        return int(float(v) * multiplier)
    except ValueError:
        return 0


class GoogleTrendsConnector(Connector):
    name = "google_trends"
    platform = "google_trends"

    @property
    def enabled(self) -> bool:
        return settings.google_trends_enabled

    async def fetch(self) -> list[RawSignal]:
        if not self.enabled:
            return []

        signals: list[RawSignal] = []
        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (compatible; MUSE/0.1)"}
        ) as client:
            for geo in REGIONS:
                try:
                    resp = await client.get(
                        RSS_URL, params={"geo": geo}, timeout=25.0
                    )
                    resp.raise_for_status()
                    root = ET.fromstring(resp.text)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Google Trends fetch failed for %s: %s", geo, exc)
                    continue

                for item in root.iter("item"):
                    sig = self._to_signal(item, geo)
                    if sig:
                        signals.append(sig)

        logger.info("Google Trends connector produced %d signals", len(signals))
        return signals

    def _to_signal(self, item: ET.Element, geo: str) -> RawSignal | None:
        title_el = item.find("title")
        title = (title_el.text or "").strip() if title_el is not None else ""
        if not title:
            return None

        traffic_el = item.find("ht:approx_traffic", NS)
        traffic = _parse_traffic(traffic_el.text if traffic_el is not None else None)

        # Prefer a linked news item as the anchor; fall back to the Trends
        # explore page for the term. Never emit without an anchor.
        news_url = None
        news_titles: list[str] = []
        for news in item.findall("ht:news_item", NS):
            url_el = news.find("ht:news_item_url", NS)
            t_el = news.find("ht:news_item_title", NS)
            if url_el is not None and url_el.text and not news_url:
                news_url = url_el.text.strip()
            if t_el is not None and t_el.text:
                news_titles.append(t_el.text.strip())

        anchor = news_url or (
            "https://trends.google.com/trends/explore"
            f"?q={quote_plus(title)}&geo={geo}"
        )

        # This feed is general trending, not a music query — there is nothing to
        # point at the AI scene. But when "Suno" or an AI-music story breaks
        # nationally it lands here, and the term plus its news headlines say so.
        scene = scene_for(title, *news_titles)

        return RawSignal(
            platform=self.platform,
            target_entity=f"{title} ({geo})",
            entity_type="search_term",
            engagement_count=traffic,
            context_anchor_url=anchor,
            associated_keywords=text_keywords(title, *news_titles),
            scene=scene,
            observed_at=datetime.now(timezone.utc),
            raw={
                "geo": geo,
                "scene": scene,
                "approx_traffic": traffic,
                "news": news_titles[:3],
            },
        )
