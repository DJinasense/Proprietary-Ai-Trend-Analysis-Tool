"""Reddit connector.

Uses the official OAuth API with a client-credentials (application-only)
grant, which is what Reddit's terms provide for read-only script access.
Free, documented, and stable — no scraping.

Music-relevant subreddits are polled for rising posts; each post becomes a
signal whose engagement is score + comment count.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from muse.config import settings
from muse.connectors.base import Connector, RawSignal
from muse.connectors.util import text_keywords

logger = logging.getLogger(__name__)

SUBREDDITS = [
    "Music", "listentothis", "WeAreTheMusicMakers", "hiphopheads",
    "electronicmusic", "indieheads", "popheads", "trap", "futurebeats",
    "synthwave", "edm", "LetsTalkMusic",
]

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"


class RedditConnector(Connector):
    name = "reddit"
    platform = "reddit"

    def __init__(self) -> None:
        self._token: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(settings.reddit_client_id and settings.reddit_client_secret)

    async def _authenticate(self, client: httpx.AsyncClient) -> str | None:
        if self._token:
            return self._token
        try:
            resp = await client.post(
                TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(settings.reddit_client_id, settings.reddit_client_secret),
                headers={"User-Agent": settings.reddit_user_agent},
                timeout=20.0,
            )
            resp.raise_for_status()
            self._token = resp.json().get("access_token")
            return self._token
        except Exception as exc:  # noqa: BLE001
            logger.warning("Reddit auth failed: %s", exc)
            return None

    async def fetch(self) -> list[RawSignal]:
        if not self.enabled:
            return []

        signals: list[RawSignal] = []
        async with httpx.AsyncClient() as client:
            token = await self._authenticate(client)
            if not token:
                return []

            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": settings.reddit_user_agent,
            }

            for sub in SUBREDDITS:
                try:
                    resp = await client.get(
                        f"{API_BASE}/r/{sub}/rising",
                        headers=headers,
                        params={"limit": 25},
                        timeout=20.0,
                    )
                    if resp.status_code == 401:
                        # Token expired mid-run; drop it so the next cycle
                        # re-authenticates rather than failing silently forever.
                        self._token = None
                        logger.warning("Reddit token rejected — will re-auth")
                        break
                    resp.raise_for_status()
                    children = resp.json().get("data", {}).get("children", [])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Reddit fetch failed for r/%s: %s", sub, exc)
                    continue

                for child in children:
                    d = child.get("data", {})
                    title = (d.get("title") or "").strip()
                    if not title:
                        continue

                    permalink = d.get("permalink") or ""
                    signals.append(
                        RawSignal(
                            platform=self.platform,
                            target_entity=f"r/{sub}: {title[:80]}",
                            entity_type="post",
                            engagement_count=int(d.get("score", 0))
                            + int(d.get("num_comments", 0)),
                            context_anchor_url=f"https://reddit.com{permalink}",
                            associated_keywords=text_keywords(
                                title, d.get("link_flair_text") or "", sub
                            ),
                            observed_at=datetime.fromtimestamp(
                                d.get("created_utc", 0) or 0, tz=timezone.utc
                            )
                            if d.get("created_utc")
                            else datetime.now(timezone.utc),
                            raw={
                                "subreddit": sub,
                                "score": d.get("score"),
                                "num_comments": d.get("num_comments"),
                                "upvote_ratio": d.get("upvote_ratio"),
                            },
                        )
                    )

        logger.info("Reddit connector produced %d signals", len(signals))
        return signals
