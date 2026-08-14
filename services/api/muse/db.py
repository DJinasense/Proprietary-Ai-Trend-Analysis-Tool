"""Async engine, session factory, and startup schema bootstrap."""

from __future__ import annotations

import logging
import pathlib
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from muse.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    # Supabase's transaction-mode pooler hands out a different backend
    # connection per transaction, so asyncpg's server-side prepared
    # statements (named and cached per logical connection) collide with
    # whatever the previous transaction on that backend already prepared —
    # DuplicatePreparedStatementError. Disabling the cache falls back to
    # unnamed statements, which transaction pooling actually supports.
    connect_args={"statement_cache_size": 0},
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with SessionLocal() as session:
        yield session


async def run_migrations() -> None:
    """Apply migration files in filename order.

    The compose file also mounts these into the Postgres image's
    docker-entrypoint-initdb.d, but that only fires on a fresh volume. Running
    them here as well makes the API self-healing against an existing volume.
    Every statement is written to be idempotent (IF NOT EXISTS throughout).
    """
    if not MIGRATIONS_DIR.exists():
        logger.warning("No migrations directory at %s", MIGRATIONS_DIR)
        return

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    async with engine.begin() as conn:
        # SQLAlchemy's asyncpg dialect routes every statement through a prepared
        # statement, and Postgres rejects multi-command prepared statements
        # ("cannot insert multiple commands into a prepared statement"). Dropping
        # to the underlying asyncpg connection gets the simple query protocol,
        # which is the one that accepts a whole script per call.
        raw = await conn.get_raw_connection()
        asyncpg_conn = raw.driver_connection
        for path in files:
            sql = path.read_text(encoding="utf-8")
            logger.info("Applying migration %s", path.name)
            await asyncpg_conn.execute(sql)
    logger.info("Migrations applied: %s", ", ".join(p.name for p in files))
