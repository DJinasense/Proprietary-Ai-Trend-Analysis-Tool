"""MUSE API — Music Utility & Structural Intelligence Engine."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from muse.config import settings
from muse.connectors import connector_status
from muse.db import engine, run_migrations
from muse.routers import insights, tracks, trends
from muse.schemas import HealthResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
)
logger = logging.getLogger("muse")

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Migrations run here rather than in a separate step so a fresh
    # `docker compose up` produces a working system with no manual command.
    try:
        await run_migrations()
    except Exception:  # noqa: BLE001
        # Log and continue: the health endpoint will report the database as
        # unreachable, which is more useful than a container that won't boot
        # and shows nothing.
        logger.exception("Migrations failed at startup")

    active = [c["name"] for c in connector_status() if c["enabled"]]
    logger.info(
        "MUSE %s ready | embeddings=%s | narrative=%s | connectors=%s",
        VERSION,
        settings.embedding_backend,
        "llm" if settings.anthropic_api_key else "deterministic",
        ", ".join(active) or "none",
    )
    yield
    await engine.dispose()


app = FastAPI(
    title="MUSE API",
    version=VERSION,
    description=(
        "Narrative-first music trend intelligence. Every reading is traceable "
        "to a source URL, and measured acoustic values are kept distinct from "
        "heuristic proxies."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tracks.router)
app.include_router(insights.router)
app.include_router(trends.router)


@app.get("/api/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    """Liveness plus a straight answer about which capabilities are actually on.

    Connectors degrade rather than fail when their credentials are absent, so
    the only honest way to know what is running is to ask.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        database = "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Health check database probe failed: %s", exc)
        database = "unreachable"

    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        version=VERSION,
        database=database,
        embedding_backend=settings.embedding_backend,
        narrative_mode="llm" if settings.anthropic_api_key else "deterministic",
        connectors=connector_status(),
    )


@app.get("/", tags=["system"])
async def root() -> dict[str, str]:
    return {"service": "muse-api", "version": VERSION, "docs": "/docs"}
