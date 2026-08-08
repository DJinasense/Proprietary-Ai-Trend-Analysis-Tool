"""Scenes: the AI-music world and the human-music world, tracked separately.

MUSE originally polled one thing — music — with no notion that AI-generated
music is a distinct scene with its own communities, its own release cadence,
and its own vocabulary. Those two worlds trend differently, so blending them
into one corpus makes both readings worse: an AI-music spike gets diluted by
chart pop, and a chart-pop reading gets polluted by Suno release chatter.

So every signal carries a `scene`. `HUMAN` is the default and covers everything
MUSE polled before this existed. `AI` covers the AI-music communities and the
signals that name AI tools directly.

Two ways a signal gets tagged `AI`:

1. **By source.** A post from r/SunoAI, or a Bluesky hit on "suno ai song", was
   sampled from the AI scene by construction. This is the reliable path.
2. **By text.** `looks_ai()` catches AI tracks that surface in a *general* feed
   — a YouTube music chart entry titled "Made with Suno". This path is
   deliberately narrow, because the cost of a false positive is real: calling a
   human artist's track AI-generated is a claim MUSE has no business making on
   the strength of a keyword. So it matches tool names and explicit
   self-labelling only, never vibes.

What this cannot do is detect AI music that does not announce itself. Nothing
in the chart sources exposes provenance — Deezer, Apple Music and Last.fm do
not tag it, and an AI track that charts is indistinguishable from any other. So
the AI scene here means "AI music being *talked about*", not "all AI music".
That distinction should survive into anything the UI says.
"""

from __future__ import annotations

import re

from muse.config import settings

HUMAN = "human"
AI = "ai"
SCENES = (HUMAN, AI)


def enabled_scenes() -> set[str]:
    """The scenes MUSE is currently collecting.

    Connectors that choose what to poll consult this when building their query
    plan and skip the work entirely. Fixed-feed sources — Google Trends serves
    one general trending list, with no query to point anywhere — cannot, so the
    ingest loop filters their output against this as a backstop. Without that,
    switching a scene off would still fill the table with it.
    """
    out: set[str] = set()
    if settings.human_scene_enabled:
        out.add(HUMAN)
    if settings.ai_scene_enabled:
        out.add(AI)
    return out

# ── Bluesky ───────────────────────────────────────────────────────────────────
# Searches are phrases, not tags, so they need to read like something a person
# would actually post. "suno" alone is too thin — it is also a surname and a
# common word in several languages.
AI_BLUESKY_QUERIES = [
    "suno ai",
    "udio music",
    "ai generated song",
    "ai music video",
    "made with suno",
    "ai cover song",
    "generative music",
]

# ── Reddit ────────────────────────────────────────────────────────────────────
AI_SUBREDDITS = [
    "SunoAI", "udiomusic", "AIMusic", "aiMusicVideos", "MusicAI",
]

# ── YouTube ───────────────────────────────────────────────────────────────────
# One search string, because search.list costs 100 quota units a call. See the
# budget note in youtube.py.
AI_YOUTUBE_QUERY = "ai generated music suno udio"

# ── Text detection ────────────────────────────────────────────────────────────
# Tool names and explicit self-labelling only. Every pattern here is something
# someone chose to write about their own track; none of them is an inference
# about how a track sounds.
_AI_PATTERNS = [
    r"\bsuno\s*(?:ai|v\d)\b",
    r"\bmade\s+with\s+suno\b",
    r"\budio\s*(?:ai|music|\.com)\b",
    r"\bai[-\s]?generated\b",
    r"\bai[-\s]?music\b",
    r"\bai[-\s]?(?:cover|song|track|vocals?)\b",
    r"\bgenerative\s+music\b",
    r"\b(?:riffusion|stable\s*audio|musicgen|mureka|boomy)\b",
    r"#aimusic\b",
    r"#sunoai\b",
]

_AI_RE = re.compile("|".join(_AI_PATTERNS), re.IGNORECASE)


def looks_ai(*texts: str) -> bool:
    """True when the text names an AI music tool or labels itself AI-generated.

    Conservative on purpose — see the module docstring. A miss here just means a
    signal stays in the human scene, which is recoverable. A false positive
    labels a real artist's work as machine-made, which is not.
    """
    for t in texts:
        if t and _AI_RE.search(t):
            return True
    return False


def scene_for(*texts: str, default: str = HUMAN) -> str:
    """The scene a signal belongs to, given its free text.

    `default` is what a source declares about itself: a connector polling
    r/SunoAI passes ``default=AI`` because provenance is settled before the text
    is read, and no amount of ordinary-looking text should demote it.
    """
    if default == AI:
        return AI
    return AI if looks_ai(*texts) else default
