"""Shared helpers for connectors."""

from __future__ import annotations

import re

# Terms that appear in nearly every music post and would match every track,
# turning correlation into noise.
NOISE = {
    "the", "and", "for", "with", "that", "this", "you", "your", "from", "have",
    "was", "are", "new", "song", "music", "track", "album", "video",
    "official", "audio", "live", "feat", "featuring", "remix", "version",
    "lyrics", "cover", "full", "best", "listen", "out", "now", "just",
    "like", "get", "all", "how", "what", "when", "why", "who", "its",
    "has", "had", "not", "but", "can", "will", "one", "two", "about",
}


def text_keywords(*texts: str, limit: int = 24) -> list[str]:
    """Extract lowercase keyword tokens from free text.

    Deliberately conservative: 4+ characters, no stopwords, no pure digits.
    Over-broad keywords are worse than too few here — they create spurious
    matches in the correlation engine, which then surface as fabricated-looking
    causes in the narrative.
    """
    seen: dict[str, None] = {}
    for t in texts:
        if not t:
            continue
        for token in re.split(r"[^\w']+", t.lower()):
            token = token.strip("'_")
            if len(token) < 4 or token in NOISE or token.isdigit():
                continue
            seen.setdefault(token, None)
            if len(seen) >= limit:
                return list(seen)
    return list(seen)


def hashtags(text: str) -> list[str]:
    """Pull hashtags out of a post body, normalised without the '#'."""
    return [h.lower() for h in re.findall(r"#(\w{3,40})", text or "")]
