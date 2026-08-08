"""Ingestion worker.

Polls every enabled connector on a fixed interval and persists what it finds.
Deliberately a plain asyncio loop rather than Celery or Kafka: at v1 volumes
this is a scheduled fan-out over a handful of HTTP APIs, and a broker would be
infrastructure to operate without a problem to solve. The `Connector`
interface is the seam — swapping this loop for a queue later touches only
this file.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timezone

from sqlalchemy import text

from muse.config import settings
from muse.connectors import enabled_connectors, persist_signals
from muse.connectors.scenes import enabled_scenes
from muse.db import SessionLocal, run_migrations

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# httpx logs the full request URL at INFO. Several APIs here take their
# credential as a query parameter (YouTube's `key=`, and Google Trends'
# session tokens), so leaving this at INFO writes live secrets into the
# container logs on every single poll.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("muse.worker")

_shutdown = asyncio.Event()


async def _record_state(
    connector_name: str, *, error: str | None = None
) -> None:
    async with SessionLocal() as session:
        await session.execute(
            text(
                """
                INSERT INTO connector_state (connector, last_run_at, last_error)
                VALUES (:name, now(), :error)
                ON CONFLICT (connector) DO UPDATE SET
                    last_run_at = now(),
                    last_error = :error
                """
            ),
            {"name": connector_name, "error": error},
        )
        await session.commit()


async def run_cycle() -> dict[str, int]:
    """One full pass over every enabled connector."""
    results: dict[str, int] = {}
    connectors = enabled_connectors()
    scenes = enabled_scenes()

    if not scenes:
        logger.warning(
            "Both scenes are disabled — nothing to collect. Set "
            "MUSE_HUMAN_SCENE_ENABLED or MUSE_AI_SCENE_ENABLED back to true."
        )
        return results

    if not connectors:
        logger.warning(
            "No connectors enabled. Add credentials to .env — Bluesky and "
            "Google Trends need none and should be running by default."
        )
        return results

    for connector in connectors:
        try:
            signals = await connector.fetch()

            kept = [s for s in signals if s.scene in scenes]
            if len(kept) != len(signals):
                logger.info(
                    "%s: dropped %d signals from disabled scenes",
                    connector.name, len(signals) - len(kept),
                )
            signals = kept

            async with SessionLocal() as session:
                written = await persist_signals(session, connector, signals)
            results[connector.name] = written
            await _record_state(connector.name)
            logger.info("%s: %d signals persisted", connector.name, written)
        except Exception as exc:  # noqa: BLE001 — one bad source must not
            # take down the whole ingestion cycle.
            logger.exception("Connector %s failed", connector.name)
            results[connector.name] = 0
            await _record_state(connector.name, error=str(exc)[:500])

    return results


async def main() -> None:
    logger.info("MUSE ingestion worker starting")

    # The API also runs migrations; whichever process wins is fine, since
    # every statement is idempotent.
    try:
        await run_migrations()
    except Exception:
        logger.exception("Migration run failed in worker — continuing")

    active = [c.name for c in enabled_connectors()]
    logger.info("Enabled connectors: %s", ", ".join(active) or "(none)")

    while not _shutdown.is_set():
        started = datetime.now(timezone.utc)
        try:
            results = await run_cycle()
            total = sum(results.values())
            logger.info(
                "Cycle complete in %.1fs — %d signals across %d connectors",
                (datetime.now(timezone.utc) - started).total_seconds(),
                total,
                len(results),
            )
        except Exception:
            logger.exception("Ingestion cycle raised")

        try:
            await asyncio.wait_for(
                _shutdown.wait(), timeout=settings.ingest_interval_seconds
            )
        except asyncio.TimeoutError:
            pass

    logger.info("Worker shut down cleanly")


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown.set)
        except NotImplementedError:
            # Windows without ProactorEventLoop support; the container runs
            # Linux so this only affects local bare-metal runs.
            pass


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers(loop)
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
