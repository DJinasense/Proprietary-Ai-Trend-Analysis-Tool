"""Bluesky connector.

The strongest free substitute for TikTok in this stack — the network carries a
genuinely active music conversation, and unlike TikTok's Research API (gated to
accredited institutions in the US and EU) anyone with an account can read it.

**Credentials are now required.** This connector originally used the
unauthenticated public AppView at `public.api.bsky.app`, which needed no key at
all. That host now returns `403 Forbidden` for `app.bsky.feed.searchPosts`
specifically — an HTML error page rather than an XRPC error, i.e. rejected at
the edge before it reaches the API. Public *profile* reads on the same host
still return 200, so this is a deliberate narrowing of anonymous search access
rather than an outage.

The supported path is an authenticated session. We log in once with an app
password via `com.atproto.server.createSession`, hold the returned `accessJwt`,
and let the PDS proxy our `app.bsky.*` reads to the AppView. An app password is
free, is revocable independently of the account password, and cannot be used to
change account settings or delete the account.

Set up: Bluesky → Settings → Privacy and security → App passwords → Add.
Then in `.env`:

    MUSE_BLUESKY_IDENTIFIER=you.bsky.social
    MUSE_BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx

Without both, `enabled` is False and the connector reports why, rather than
sitting in the status bar looking live while returning nothing.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from muse.config import settings
from muse.connectors.base import Connector, RawSignal
from muse.connectors.util import hashtags, text_keywords

logger = logging.getLogger(__name__)

# Authenticated reads go to the PDS/entryway, which proxies app.bsky.* queries
# to the AppView on our behalf. A user accessJwt is audience-scoped to the PDS
# that issued it, so sending it to public.api.bsky.app would not authenticate.
SERVICE = "https://bsky.social/xrpc"

# Access tokens are valid for roughly two hours. Refresh well before that
# rather than waiting for a 401 — the 401 path still exists as a backstop.
SESSION_MAX_AGE_SECONDS = 90 * 60

QUERIES = [
    "new music",
    "new single",
    "released today music",
    "producer beat",
    "synthwave",
    "hyperpop",
    "indie release",
    "song of the day",
]


@dataclass
class _Session:
    access_jwt: str
    refresh_jwt: str
    created_at: float

    @property
    def stale(self) -> bool:
        return (time.monotonic() - self.created_at) > SESSION_MAX_AGE_SECONDS


class BlueskyConnector(Connector):
    name = "bluesky"
    platform = "bluesky"

    def __init__(self) -> None:
        self._session: _Session | None = None

    # ── Availability ──────────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return bool(_identifier() and settings.bluesky_app_password.strip())

    def describe(self) -> dict[str, Any]:
        d = super().describe()
        if not self.enabled:
            d["detail"] = (
                "Set MUSE_BLUESKY_IDENTIFIER and MUSE_BLUESKY_APP_PASSWORD — "
                "Bluesky no longer serves post search without a session."
            )
        return d

    # ── Session management ────────────────────────────────────────────────
    async def _create_session(self, client: httpx.AsyncClient) -> _Session | None:
        try:
            resp = await client.post(
                f"{SERVICE}/com.atproto.server.createSession",
                json={
                    "identifier": _identifier(),
                    "password": settings.bluesky_app_password.strip(),
                },
                timeout=25.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            # Do not log the response body — a failed login echoes the
            # identifier back, and the worker log is not a secret store.
            logger.warning("Bluesky login failed: %s", _describe_error(exc))
            return None

        access, refresh = data.get("accessJwt"), data.get("refreshJwt")
        if not access or not refresh:
            logger.warning("Bluesky login returned no tokens")
            return None

        logger.info("Bluesky session established for %s", data.get("handle", "?"))
        return _Session(access_jwt=access, refresh_jwt=refresh, created_at=time.monotonic())

    async def _refresh_session(self, client: httpx.AsyncClient) -> _Session | None:
        if not self._session:
            return None
        try:
            resp = await client.post(
                f"{SERVICE}/com.atproto.server.refreshSession",
                headers={"Authorization": f"Bearer {self._session.refresh_jwt}"},
                timeout=25.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.info("Bluesky refresh failed (%s), re-authenticating", _describe_error(exc))
            return None

        access, refresh = data.get("accessJwt"), data.get("refreshJwt")
        if not access or not refresh:
            return None
        return _Session(access_jwt=access, refresh_jwt=refresh, created_at=time.monotonic())

    async def _ensure_session(
        self, client: httpx.AsyncClient, *, force_new: bool = False
    ) -> _Session | None:
        """Return a usable session, reusing the cached one where possible.

        createSession is rate-limited far more aggressively than reads
        (hundreds per day, not per minute), so a fresh login on every poll
        would eventually lock the connector out on its own.
        """
        if force_new:
            self._session = None
        elif self._session and not self._session.stale:
            return self._session

        if self._session and self._session.stale:
            self._session = await self._refresh_session(client)
            if self._session:
                return self._session

        self._session = await self._create_session(client)
        return self._session

    # ── Fetch ─────────────────────────────────────────────────────────────
    async def fetch(self) -> list[RawSignal]:
        if not self.enabled:
            return []

        signals: list[RawSignal] = []

        async with httpx.AsyncClient() as client:
            session = await self._ensure_session(client)
            if not session:
                logger.warning("Bluesky connector has no session; skipping this cycle")
                return []

            for query in QUERIES:
                posts = await self._search(client, query, session)
                if posts is None:
                    # 401 on a token we believed was good — log in again once
                    # and retry this query. If that also fails, give up on the
                    # cycle rather than hammering the login endpoint.
                    session = await self._ensure_session(client, force_new=True)
                    if not session:
                        break
                    posts = await self._search(client, query, session) or []

                for post in posts:
                    sig = self._to_signal(post, query)
                    if sig:
                        signals.append(sig)

        logger.info("Bluesky connector produced %d signals", len(signals))
        return signals

    async def _search(
        self, client: httpx.AsyncClient, query: str, session: _Session
    ) -> list[dict] | None:
        """Return posts, or None to signal "auth expired, retry with a new session"."""
        try:
            resp = await client.get(
                f"{SERVICE}/app.bsky.feed.searchPosts",
                params={"q": query, "limit": 40, "sort": "top"},
                headers={"Authorization": f"Bearer {session.access_jwt}"},
                timeout=25.0,
            )
            if resp.status_code == 401:
                return None
            resp.raise_for_status()
            return resp.json().get("posts", [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Bluesky search failed for %r: %s", query, _describe_error(exc))
            return []

    def _to_signal(self, post: dict, query: str) -> RawSignal | None:
        record = post.get("record", {})
        text_body = (record.get("text") or "").strip()
        uri = post.get("uri") or ""
        author = post.get("author", {})
        handle = author.get("handle")

        if not text_body or not uri or not handle:
            return None

        likes = int(post.get("likeCount", 0) or 0)
        reposts = int(post.get("repostCount", 0) or 0)
        replies = int(post.get("replyCount", 0) or 0)

        # Skip the long tail of zero-engagement posts — they carry no trend
        # information and would swamp the baseline computation.
        engagement = likes + (reposts * 3) + (replies * 2)
        if engagement < 3:
            return None

        # at://did:plc:xxx/app.bsky.feed.post/RKEY  ->  bsky.app permalink
        rkey = uri.rsplit("/", 1)[-1]
        url = f"https://bsky.app/profile/{handle}/post/{rkey}"

        created = record.get("createdAt")
        try:
            observed = (
                datetime.fromisoformat(created.replace("Z", "+00:00"))
                if created
                else datetime.now(timezone.utc)
            )
        except ValueError:
            observed = datetime.now(timezone.utc)

        keywords = text_keywords(text_body, query)
        keywords.extend(hashtags(text_body))

        return RawSignal(
            platform=self.platform,
            target_entity=f"@{handle}: {text_body[:70]}",
            entity_type="post",
            engagement_count=engagement,
            context_anchor_url=url,
            associated_keywords=list(dict.fromkeys(keywords)),
            observed_at=observed,
            raw={
                "handle": handle,
                "query": query,
                "likes": likes,
                "reposts": reposts,
                "replies": replies,
            },
        )


def _identifier() -> str:
    """The configured handle, normalised for createSession.

    Bluesky displays handles as ``@you.bsky.social`` everywhere in its own UI,
    so that is what people paste into the .env. The AT Protocol identifier
    field wants the bare handle or a DID — the leading ``@`` makes it an
    invalid identifier and the login fails with a 400 that says nothing about
    the cause. Strip it rather than making the user find that out.
    """
    return settings.bluesky_identifier.strip().lstrip("@")


def _describe_error(exc: Exception) -> str:
    """Status code and XRPC error name only — never the response body."""
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            name = exc.response.json().get("error", "")
        except Exception:  # noqa: BLE001
            name = ""
        return f"HTTP {exc.response.status_code}{f' ({name})' if name else ''}"
    return f"{type(exc).__name__}: {exc}"
