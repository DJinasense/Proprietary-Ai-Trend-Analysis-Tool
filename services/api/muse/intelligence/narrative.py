"""Narrative Synthesis Layer — Tier 3, the core innovation.

Turns three structured inputs (acoustic profile, correlated social drivers,
fatigue result) into the sentence the source document said every existing tool
fails to produce: *why* the line is moving, and what to do about it.

Two generation modes, and the UI always shows which one produced the text:

* ``llm``           — Claude synthesises from the structured evidence.
* ``deterministic`` — a rules-based template, used when no API key is set or
                      the API call fails. Always available, never blocks.

The single most important constraint on the LLM path is that it may only
reference drivers present in the evidence block. A narrative engine that
hallucinates "a beauty influencer on TikTok" when no such signal was observed
would reproduce, in a more convincing register, exactly the credibility
problem MUSE is meant to solve. The prompt forbids it, the evidence is passed
as structured JSON rather than prose, and the deterministic path is the
fallback rather than an unconstrained retry.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from muse.config import settings
from muse.intelligence.correlation import Driver
from muse.intelligence.fatigue import FatigueResult

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are the Narrative Synthesis Layer of MUSE, a music market-intelligence \
engine. You translate structured analysis into plain language for working \
musicians — from label A&Rs to bedroom producers.

You will receive a JSON evidence block containing:
  - acoustic: measured and proxied features of one track
  - fatigue: a market-saturation reading with a confidence score
  - drivers: social signals correlated with this track, each with a source URL
  - corpus: how much comparison data the reading is based on

ABSOLUTE RULES

1. Never invent a cause. If `drivers` is empty, say plainly that no external \
driver was detected and that the reading is acoustic-only. Do not speculate \
about TikTok, influencers, playlists, or anything else not in the evidence.

2. Respect confidence. When `fatigue.confidence` is below 0.25, you must lead \
with the fact that the corpus is too small for a reliable saturation reading. \
Do not present a low-confidence number as a finding.

3. Distinguish measured from proxied. bpm, key, spectral values, dynamic range \
and loudness are measured. energy, valence, danceability and acousticness are \
documented heuristics. Never describe a proxy as if it were a measurement.

4. No hedging filler, no hype, no jargon-for-its-own-sake. A producer should \
be able to act on the last sentence without a glossary.

OUTPUT — return valid JSON only, no markdown fence:
{
  "headline": "one line, under 90 characters, the single most important thing",
  "narrative": "2-4 sentences explaining what is happening and why, citing \
platforms by name where drivers exist",
  "actionable_insight": "1-2 sentences of concrete, specific advice. Name the \
musical or release decision to make. Never generic encouragement."
}"""


@dataclass
class Narrative:
    headline: str
    narrative: str
    actionable_insight: str
    generation_mode: str
    model: str | None = None


def build_evidence(
    *,
    title: str,
    genre: str | None,
    acoustic: dict[str, Any],
    fatigue: FatigueResult,
    drivers: list[Driver],
) -> dict[str, Any]:
    """Assemble the structured evidence block handed to the model."""
    return {
        "track": {"title": title, "genre": genre},
        "acoustic": {
            "measured": {
                "bpm": acoustic.get("bpm"),
                "key": acoustic.get("musical_key"),
                "mode": acoustic.get("mode"),
                "key_confidence": acoustic.get("key_confidence"),
                "duration_sec": acoustic.get("duration_sec"),
                "spectral_centroid_hz": acoustic.get("spectral_centroid"),
                "dynamic_range_db": acoustic.get("dynamic_range"),
            },
            "proxied": {
                "energy": acoustic.get("energy"),
                "valence": acoustic.get("valence"),
                "danceability": acoustic.get("danceability"),
                "acousticness": acoustic.get("acousticness"),
            },
        },
        "fatigue": {
            "index": fatigue.fatigue_index,
            "confidence": fatigue.confidence,
            "verdict": fatigue.verdict,
            "density_recent": fatigue.density_recent,
            "supply_trend": fatigue.density_slope,
            "engagement_trend": fatigue.engagement_slope,
            "explanation": fatigue.explanation,
        },
        "corpus": {
            "comparable_tracks": fatigue.neighbor_count,
            "with_engagement_data": fatigue.components.get(
                "neighbors_with_engagement", 0
            ),
        },
        "drivers": [
            {
                "platform": d.platform,
                "entity": d.entity,
                "entity_type": d.entity_type,
                "velocity_surge_pct": d.velocity_surge,
                "engagement": d.engagement,
                "observed_at": d.observed_at.isoformat(),
                "source_url": d.context_anchor_url,
            }
            for d in drivers
        ],
    }


def deterministic_narrative(
    *,
    title: str,
    genre: str | None,
    fatigue: FatigueResult,
    drivers: list[Driver],
) -> Narrative:
    """Rules-based synthesis. No API key required, never fails."""

    # ── Low confidence dominates everything else ──────────────────────────
    if fatigue.verdict == "insufficient_data" or fatigue.confidence < 0.25:
        headline = "Acoustic profile captured — market context still building"
        narrative = (
            f"\"{title}\" has been fully analysed acoustically, but the corpus "
            f"currently holds {fatigue.neighbor_count} comparable "
            f"track{'s' if fatigue.neighbor_count != 1 else ''}, which is not "
            "enough to judge market saturation. "
        )
        if drivers:
            top = drivers[0]
            narrative += (
                f"One external signal was detected: activity around "
                f"{top.entity} on {top.platform}."
            )
        else:
            narrative += "No external social drivers were detected in the window."
        return Narrative(
            headline=headline,
            narrative=narrative,
            actionable_insight=(
                "Treat the saturation figure as provisional. Analyse more "
                "reference tracks in this style, or connect a social source, "
                "to make the reading meaningful."
            ),
            generation_mode="deterministic",
        )

    pct = f"{fatigue.fatigue_index * 100:.1f}%"

    # ── Driver-led narrative ──────────────────────────────────────────────
    if drivers:
        top = drivers[0]
        platforms = sorted({d.platform for d in drivers})
        platform_str = (
            platforms[0]
            if len(platforms) == 1
            else ", ".join(platforms[:-1]) + f" and {platforms[-1]}"
        )
        narrative = (
            f"Movement on \"{title}\" correlates with activity on "
            f"{platform_str} — the strongest signal is {top.entity}, up "
            f"{top.velocity_surge:.0f}% in the observation window. "
            f"Market saturation for this sonic profile reads {pct} "
            f"({fatigue.verdict}). {fatigue.explanation}"
        )
    else:
        narrative = (
            f"No external social drivers were detected for \"{title}\" in the "
            f"window, so this reading is acoustic-only. Market saturation for "
            f"this sonic profile reads {pct}. {fatigue.explanation}"
        )

    # ── Action ────────────────────────────────────────────────────────────
    if fatigue.verdict == "saturated":
        headline = f"Saturated sonic space — {pct} fatigue"
        action = (
            "The neighbourhood is crowded and engagement per release is not "
            "keeping pace. Differentiate structurally rather than sonically: "
            "change the arrangement at the second chorus, or shift the "
            "release into a less contested week."
        )
    elif fatigue.verdict == "warming":
        headline = f"Window narrowing — {pct} fatigue and rising"
        action = (
            "Supply in this space is climbing. If this record is close to "
            "finished, prioritise shipping it over further polish — the "
            "advantage here is timing, not refinement."
        )
    else:
        headline = f"Open lane — {pct} fatigue"
        action = (
            "Saturation is low for this profile. Lean into what makes the "
            "track distinctive and release while the space is uncontested."
        )

    if drivers:
        action += (
            f" Engage the {drivers[0].platform} activity directly while it is "
            "still live."
        )

    return Narrative(
        headline=headline,
        narrative=narrative,
        actionable_insight=action,
        generation_mode="deterministic",
    )


async def llm_narrative(evidence: dict[str, Any]) -> Narrative | None:
    """Claude-backed synthesis. Returns None on any failure so the caller
    falls back to the deterministic path rather than surfacing an error."""

    if not settings.anthropic_api_key:
        return None

    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.narrative_model,
            max_tokens=900,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Evidence block:\n\n"
                        + json.dumps(evidence, indent=2, default=str)
                        + "\n\nSynthesise the narrative. JSON only."
                    ),
                }
            ],
        )

        text_out = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()

        # Tolerate a fenced response even though the prompt forbids it.
        if text_out.startswith("```"):
            text_out = text_out.split("```")[1]
            if text_out.startswith("json"):
                text_out = text_out[4:]
            text_out = text_out.strip()

        payload = json.loads(text_out)

        required = {"headline", "narrative", "actionable_insight"}
        if not required.issubset(payload):
            logger.warning(
                "LLM response missing keys %s — falling back",
                required - set(payload),
            )
            return None

        return Narrative(
            headline=str(payload["headline"]).strip(),
            narrative=str(payload["narrative"]).strip(),
            actionable_insight=str(payload["actionable_insight"]).strip(),
            generation_mode="llm",
            model=settings.narrative_model,
        )

    except Exception as exc:  # noqa: BLE001 — narrative must never break analysis
        logger.warning("LLM narrative failed (%s) — using deterministic path", exc)
        return None


async def synthesize(
    *,
    title: str,
    genre: str | None,
    acoustic: dict[str, Any],
    fatigue: FatigueResult,
    drivers: list[Driver],
) -> tuple[Narrative, dict[str, Any]]:
    """Produce the narrative, preferring Claude and degrading gracefully."""

    evidence = build_evidence(
        title=title, genre=genre, acoustic=acoustic, fatigue=fatigue, drivers=drivers
    )

    narrative = await llm_narrative(evidence)
    if narrative is None:
        narrative = deterministic_narrative(
            title=title, genre=genre, fatigue=fatigue, drivers=drivers
        )

    return narrative, evidence
