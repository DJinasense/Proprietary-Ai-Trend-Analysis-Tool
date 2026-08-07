"""Contextual Cross-Reference Engine — Tier 2 of the spec.

Answers "what happened around this track" by matching stored social spikes
against a track's identifying terms inside a temporal window, then ranking
them by how much they plausibly explain movement.

Every driver returned carries its `context_anchor_url`. That is deliberate:
the Exploding Topics complaint in the source document was that users cannot
tell where a trend claim came from. Here, every claim the narrative layer
makes is traceable to a link the user can open.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from muse.config import settings

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 30
DRIVER_HALF_LIFE_DAYS = 7.0

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "to", "for", "with",
    "my", "your", "is", "it", "at", "by", "feat", "ft", "remix", "version",
    "official", "audio", "video", "prod",
}

# Words long enough to survive tokenisation but too common to be evidence of
# anything. These are deliberately *not* added to STOPWORDS: a track called
# "Borrowed Time" should still match a signal keyed on "time", it just must not
# be able to claim causation on that match alone.
GENERIC_TERMS = {
    "about", "after", "again", "all", "also", "back", "been", "before",
    "being", "best", "better", "book", "both", "call", "came", "come",
    "could", "does", "done", "down", "even", "ever", "every", "first",
    "from", "full", "give", "goes", "going", "good", "have", "here",
    "into", "just", "keep", "know", "last", "left", "less", "life",
    "like", "line", "list", "long", "look", "made", "make", "many",
    "more", "most", "much", "must", "need", "never", "next", "news",
    "only", "open", "other", "over", "part", "past", "people", "place",
    "post", "real", "right", "said", "same", "says", "show", "since",
    "some", "still", "such", "take", "than", "that", "them", "then",
    "there", "these", "they", "thing", "think", "this", "those", "time",
    "today", "under", "used", "very", "want", "week", "well", "went",
    "were", "what", "when", "where", "which", "while", "will", "with",
    "work", "would", "year", "your",
}

# Connectors whose queries are already scoped to music. A single-term match
# from one of these is meaningfully more likely to be about music than the
# same match from a general-purpose news/search feed.
#
# The chart sources are the strongest members of this set: every row they emit
# is a song by construction, so a term shared with a track is a term shared
# with another song rather than with the internet at large.
MUSIC_DOMAIN_CONNECTORS = {
    "reddit", "youtube", "bluesky", "deezer", "apple_music", "lastfm",
}


@dataclass
class Driver:
    platform: str
    connector: str
    originating_event: str
    entity: str
    entity_type: str | None
    velocity_surge: float
    engagement: int
    context_anchor_url: str
    observed_at: datetime
    relevance: float
    # What actually tied this signal to the track, and on which terms. Carried
    # through to the API so a user can see the basis of the claim, not just
    # the claim.
    match_basis: str = "unspecified"
    matched_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["observed_at"] = self.observed_at.isoformat()
        return d


def track_terms(title: str, genre: str | None) -> list[str]:
    """Identifying terms for a track, used for keyword-array overlap.

    Includes the full lowercased title and genre plus individual meaningful
    tokens, so "Livin' on Borrowed Time" also matches a signal keyed on
    "borrowed".
    """
    terms: set[str] = set()
    t = (title or "").strip().lower()
    if t:
        terms.add(t)
        for token in re.split(r"[^a-z0-9']+", t):
            token = token.strip("'")
            if len(token) >= 4 and token not in STOPWORDS:
                terms.add(token)
    if genre:
        g = genre.strip().lower()
        terms.add(g)
        # "Synthwave-Industrial" should also match "synthwave" and "industrial"
        for part in re.split(r"[^a-z0-9]+", g):
            if len(part) >= 4 and part not in STOPWORDS:
                terms.add(part)
    return sorted(terms)


SIGNAL_SQL = text(
    """
    SELECT
        s.platform,
        s.connector,
        s.target_entity,
        s.entity_type,
        s.velocity_spike_pct,
        s.engagement_count,
        s.context_anchor_url,
        s.observed_at,
        s.associated_keywords,
        EXTRACT(EPOCH FROM (now() - s.observed_at)) / 86400.0 AS age_days
    FROM social_signals s
    WHERE s.associated_keywords && CAST(:terms AS text[])
      -- make_interval() with an integer rather than CAST('30 days' AS interval):
      -- asyncpg binds the parameter as a native interval and rejects a string
      -- outright, so the cast form fails at execution time.
      AND s.observed_at >= now() - make_interval(days => :lookback_days)
    ORDER BY s.observed_at DESC
    LIMIT 200
    """
)


# How often each of our terms appears across the whole window, not just in the
# matching rows. A term carried by a large share of all signals is boilerplate
# — it says something about the connectors' vocabulary, not about this track.
TERM_FREQ_SQL = text(
    """
    WITH win AS (
        SELECT associated_keywords
        FROM social_signals
        WHERE observed_at >= now() - make_interval(days => :lookback_days)
    )
    SELECT
        lower(kw) AS term,
        count(*)::int AS df,
        (SELECT count(*) FROM win)::int AS total
    FROM win, unnest(associated_keywords) AS kw
    WHERE lower(kw) = ANY(CAST(:terms AS text[]))
    GROUP BY 1
    """
)


def _word_count(s: str) -> int:
    return len([t for t in re.split(r"[^a-z0-9']+", s or "") if t.strip("'")])


def _weigh_match(
    matched: set[str],
    *,
    title_full: str,
    title_token_count: int,
    genre_full: str | None,
    connector: str,
    generic: set[str],
) -> tuple[float, str] | None:
    """Decide whether an overlap is evidence at all, and how strong.

    Returns ``(specificity, basis)`` or ``None`` to reject the signal.

    This is the bar. Before it existed, any single non-stopword token scored
    0.7 — which is how a money-laundering news story keyed on "probe" was
    reported as the driver behind a track called "Dedupe Probe". One four-letter
    collision, rendered as a confident causal sentence. Coincidence at that rate
    is not evidence, and a tool whose whole premise is traceable claims cannot
    make claims like that.
    """
    if not matched:
        return None

    # Multi-word title/genre strings are phrases, not tokens — they are judged
    # by the branches below. A *single*-word title or genre is left in the token
    # pool, because for those the word genuinely is the whole evidence.
    phrases = {x for x in (title_full, genre_full or "") if _word_count(x) >= 2}
    tokens = matched - phrases
    distinctive = {t for t in tokens if t not in generic}
    scoped = connector in MUSIC_DOMAIN_CONNECTORS

    # A multi-word title appearing verbatim is not a coincidence.
    if title_full and title_full in matched and title_token_count >= 2:
        return 1.0, "exact title"

    # Several independent distinctive terms landing on one signal is not
    # either — the probability of coincidence falls off fast.
    if len(distinctive) >= settings.correlation_min_distinct_terms:
        extra = len(distinctive) - settings.correlation_min_distinct_terms
        return min(0.55 + 0.1 * extra, 0.9), f"{len(distinctive)} distinct terms"

    # Everything below is a single-term match, and a single term is only
    # admissible from a source that was already asking about music. The same
    # single term from a general search/news feed is exactly the failure mode
    # above: a track with the genre "test" matched Google Trends' "jobs (GB)"
    # on the word "test", which is a coincidence wearing a causal sentence.
    if not scoped:
        return None

    if distinctive:
        return 0.5, f"music-scoped source, term '{sorted(distinctive)[0]}'"

    # A multi-word genre phrase, on a music source. Weak but honest: it says
    # "this lane is active", never "this event moved your track", and is scored
    # so it can never outrank a real match.
    if genre_full and genre_full in matched and genre_full not in generic:
        return 0.35, f"genre match ('{genre_full}')"

    return None


async def find_drivers(
    session: AsyncSession,
    *,
    title: str,
    genre: str | None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    limit: int = 6,
) -> list[Driver]:
    """Return the social spikes most likely to explain this track's movement.

    Returns ``[]`` when nothing clears the evidence bar. That empty list is a
    result, not a failure — the narrative layer says "no external driver was
    detected", which is the correct answer far more often than any single
    keyword collision would suggest.
    """

    terms = track_terms(title, genre)
    if not terms:
        return []

    params = {"terms": terms, "lookback_days": int(lookback_days)}
    rows = (await session.execute(SIGNAL_SQL, params)).mappings().all()
    if not rows:
        return []

    freq_rows = (await session.execute(TERM_FREQ_SQL, params)).mappings().all()

    # Corpus-derived genericness, on top of the static list. A term carried by
    # more than `correlation_max_df_ratio` of all signals in the window is this
    # corpus's own boilerplate, whatever the dictionary thinks of it.
    generic = set(GENERIC_TERMS)
    total = int(freq_rows[0]["total"]) if freq_rows else 0
    if total >= 20:  # below this, document frequency is noise
        for fr in freq_rows:
            if int(fr["df"]) / total > settings.correlation_max_df_ratio:
                generic.add(fr["term"])

    title_full = (title or "").strip().lower()
    title_token_count = _word_count(title_full)
    genre_full = genre.strip().lower() if genre else None

    term_set = set(terms)
    drivers: list[Driver] = []
    rejected = 0

    for r in rows:
        matched = term_set.intersection(
            {k.lower() for k in (r["associated_keywords"] or [])}
        )
        weighed = _weigh_match(
            matched,
            title_full=title_full,
            title_token_count=title_token_count,
            genre_full=genre_full,
            connector=r["connector"],
            generic=generic,
        )
        if weighed is None:
            rejected += 1
            continue
        specificity, basis = weighed

        age_days = float(r["age_days"] or 0.0)
        recency = math.exp(-math.log(2.0) * age_days / DRIVER_HALF_LIFE_DAYS)

        velocity = float(r["velocity_spike_pct"] or 0.0)
        # Compress velocity — a 3000% spike is not 10x more explanatory than
        # a 300% one, and without compression a single outlier dominates.
        velocity_term = math.log1p(max(velocity, 0.0)) / math.log1p(1000.0)

        relevance = recency * specificity * (0.35 + 0.65 * min(velocity_term, 1.5))
        if relevance < settings.correlation_min_relevance:
            rejected += 1
            continue

        drivers.append(
            Driver(
                platform=r["platform"],
                connector=r["connector"],
                originating_event=f"Activity spike around {r['target_entity']}",
                entity=r["target_entity"],
                entity_type=r["entity_type"],
                velocity_surge=round(velocity, 2),
                engagement=int(r["engagement_count"] or 0),
                context_anchor_url=r["context_anchor_url"],
                observed_at=r["observed_at"],
                relevance=round(relevance, 4),
                match_basis=basis,
                matched_terms=sorted(matched),
            )
        )

    drivers.sort(key=lambda d: d.relevance, reverse=True)

    # De-duplicate by (platform, entity) — connectors polling on a schedule
    # will legitimately observe the same entity repeatedly, and six rows about
    # one subreddit is not six drivers.
    seen: set[tuple[str, str]] = set()
    unique: list[Driver] = []
    for d in drivers:
        key = (d.platform, d.entity.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(d)
        if len(unique) >= limit:
            break

    logger.info(
        "Correlation for %r: %d signals matched, %d rejected below the "
        "evidence bar -> %d distinct drivers",
        title, len(rows), rejected, len(unique),
    )
    return unique
