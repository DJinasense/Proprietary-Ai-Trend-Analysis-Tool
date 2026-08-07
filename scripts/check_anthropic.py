"""Preflight for the narrative layer's Anthropic credentials.

`/api/health` reports narrative_mode from whether the key string is non-empty,
which tells you nothing about whether the key works. This makes one real
~10-token call and prints the actual outcome, so a billing, auth, or model-name
problem surfaces in a second rather than as a silent fallback to the
deterministic path buried in the container logs.

Run inside the api container:

    docker compose exec api python /app/../scripts/check_anthropic.py

or, from the repo root with the API's env loaded:

    python scripts/check_anthropic.py
"""

from __future__ import annotations

import asyncio
import sys

from muse.config import settings


async def main() -> int:
    key = settings.anthropic_api_key
    if not key:
        print("FAIL  MUSE_ANTHROPIC_API_KEY is empty.")
        print("      The narrative layer will use the deterministic path.")
        return 1

    # Enough to confirm the shape without putting the secret on stdout.
    print(f"key    : {key[:11]}…{key[-4:]}  ({len(key)} chars)")
    print(f"model  : {settings.narrative_model}")

    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=key)
        resp = await client.messages.create(
            model=settings.narrative_model,
            max_tokens=16,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        )
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAIL  {type(exc).__name__}: {exc}")
        print("\n      401 / authentication_error -> key is wrong or revoked.")
        print("      400 / credit balance        -> org has no API credits.")
        print("      404 / model_not_found       -> MUSE_NARRATIVE_MODEL is wrong.")
        print("      429 / rate_limit_error      -> valid key, throttled; retry.")
        return 1

    text_out = "".join(b.text for b in resp.content if b.type == "text").strip()
    usage = resp.usage
    print(f"\nOK    reply={text_out!r}")
    print(f"      tokens in={usage.input_tokens} out={usage.output_tokens}")
    print("      The narrative layer will use Claude.")
    return 0


sys.exit(asyncio.run(main()))
