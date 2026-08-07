"""Connector registry.

Adding a licensed TikTok/Instagram source later means writing one module that
subclasses `Connector` and appending it to `ALL_CONNECTORS`. No other file
changes.
"""

from __future__ import annotations

from muse.connectors.applemusic import AppleMusicConnector
from muse.connectors.base import Connector, RawSignal, persist_signals
from muse.connectors.bluesky import BlueskyConnector
from muse.connectors.deezer import DeezerConnector
from muse.connectors.gtrends import GoogleTrendsConnector
from muse.connectors.lastfm import LastFmConnector
from muse.connectors.reddit import RedditConnector
from muse.connectors.youtube import YouTubeConnector

ALL_CONNECTORS: list[Connector] = [
    RedditConnector(),
    YouTubeConnector(),
    BlueskyConnector(),
    GoogleTrendsConnector(),
    DeezerConnector(),
    AppleMusicConnector(),
    LastFmConnector(),
]


def enabled_connectors() -> list[Connector]:
    return [c for c in ALL_CONNECTORS if c.enabled]


def connector_status() -> list[dict]:
    return [c.describe() for c in ALL_CONNECTORS]


__all__ = [
    "Connector",
    "RawSignal",
    "persist_signals",
    "ALL_CONNECTORS",
    "enabled_connectors",
    "connector_status",
]
