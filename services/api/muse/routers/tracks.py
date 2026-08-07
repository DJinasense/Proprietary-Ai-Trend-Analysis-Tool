"""Track upload and analysis job endpoints."""

from __future__ import annotations

import hashlib
import logging
import os
import pathlib
import re
import uuid
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from muse.config import settings
from muse.db import SessionLocal, get_session
from muse.pipeline import run_analysis
from muse.schemas import JobStatus, TrackSummary, UploadResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tracks", tags=["tracks"])

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".aiff", ".aif"}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB
CHUNK = 1024 * 1024


def _safe_stem(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80] or "upload"


async def _run_job_in_background(
    job_id: str, track_row_id: int, media_path: str, title: str, genre: str | None
) -> None:
    """Background entrypoint. Owns its own session — the request-scoped one is
    closed by the time this runs."""
    async with SessionLocal() as session:
        try:
            await run_analysis(
                session,
                job_id=job_id,
                track_row_id=track_row_id,
                media_path=media_path,
                title=title,
                genre=genre,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Analysis job %s failed", job_id)
            # A DB-level failure leaves the transaction aborted, and Postgres
            # rejects every subsequent statement on it — including this one.
            # Without the rollback the job never reaches a terminal state and
            # clients poll it forever.
            await session.rollback()
            # Postgres text cannot hold a NUL byte, and driver errors quote the
            # offending SQL back at us, so the error string is not necessarily
            # clean.
            err = str(exc).replace("\x00", "\\x00")[:1000]
            try:
                await session.execute(
                    text(
                        """
                        UPDATE analysis_jobs
                        SET status = 'failed', error = :err, updated_at = now()
                        WHERE job_id = :job_id
                        """
                    ),
                    {"job_id": job_id, "err": err},
                )
                await session.commit()
            except Exception:  # noqa: BLE001
                # Nothing further we can do; log it rather than raising into
                # the background-task machinery where it would be swallowed.
                logger.exception("Could not record failure for job %s", job_id)


@router.post("", response_model=UploadResponse, status_code=202)
async def upload_track(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(...),
    genre: str | None = Form(None),
    artist: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
) -> UploadResponse:
    """Upload an audio file and queue the full analysis pipeline."""

    ext = pathlib.Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported format {ext or '(none)'}. "
                f"Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            ),
        )

    if not title.strip():
        raise HTTPException(status_code=400, detail="Title is required.")

    track_id = f"trk_{uuid.uuid4().hex[:16]}"
    media_root = pathlib.Path(settings.media_root)
    media_root.mkdir(parents=True, exist_ok=True)
    dest = media_root / f"{track_id}_{_safe_stem(pathlib.Path(file.filename).stem)}{ext}"

    # Stream to disk with a running size check — reading the whole upload into
    # memory first would let a large file exhaust the container.
    written = 0
    hasher = hashlib.sha256()
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(CHUNK):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds {MAX_UPLOAD_BYTES // (1024*1024)}MB limit.",
                    )
                hasher.update(chunk)
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}") from exc

    if written == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    content_hash = hasher.hexdigest()

    # Re-analysing a file already in the corpus would mint a second embedding at
    # (near) zero distance from the first. Those synthetic neighbours raise
    # neighbourhood density and confidence for the whole region, so the corpus
    # reads as saturated purely because someone uploaded twice. Return the
    # existing analysis instead.
    existing = (
        await session.execute(
            text(
                """
                SELECT t.track_id,
                       (SELECT j.job_id
                          FROM analysis_jobs j
                         WHERE j.track_id = t.id
                      ORDER BY j.created_at DESC
                         LIMIT 1) AS job_id
                  FROM tracks t
                 WHERE t.content_hash = :content_hash
                """
            ),
            {"content_hash": content_hash},
        )
    ).first()

    if existing is not None and existing.job_id:
        dest.unlink(missing_ok=True)
        logger.info(
            "Duplicate upload rejected: %s already present as %s",
            file.filename,
            existing.track_id,
        )
        return UploadResponse(
            job_id=existing.job_id,
            track_id=existing.track_id,
            status="duplicate",
            message=(
                "This audio is already in the corpus — returning the existing "
                "analysis. Re-analysing it would inflate saturation readings."
            ),
            duplicate=True,
        )

    # Artist is optional; create-or-fetch by normalised key.
    artist_row_id = None
    if artist and artist.strip():
        artist_key = re.sub(r"\s+", "-", artist.strip().lower())
        artist_row_id = (
            await session.execute(
                text(
                    """
                    INSERT INTO artists (artist_key, display_name)
                    VALUES (:key, :name)
                    ON CONFLICT (artist_key) DO UPDATE SET display_name = EXCLUDED.display_name
                    RETURNING id
                    """
                ),
                {"key": artist_key, "name": artist.strip()},
            )
        ).scalar_one()

    # The check above races: two identical uploads in flight together both see
    # an empty corpus. The partial unique index is the actual guarantee, so
    # losing the race has to be survivable rather than a 500.
    inserted = (
        await session.execute(
            text(
                """
                INSERT INTO tracks
                    (track_id, title, artist_id, genre, media_path, content_hash)
                VALUES
                    (:track_id, :title, :artist_id, :genre, :media_path, :content_hash)
                ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                    DO NOTHING
                RETURNING id
                """
            ),
            {
                "track_id": track_id,
                "title": title.strip(),
                "artist_id": artist_row_id,
                "genre": (genre or "").strip() or None,
                "media_path": str(dest),
                "content_hash": content_hash,
            },
        )
    ).scalar_one_or_none()

    if inserted is None:
        # The concurrent upload committed first. Adopt its track rather than
        # writing a second copy of identical audio.
        await session.rollback()
        dest.unlink(missing_ok=True)
        winner = (
            await session.execute(
                text(
                    """
                    SELECT t.track_id,
                           (SELECT j.job_id
                              FROM analysis_jobs j
                             WHERE j.track_id = t.id
                          ORDER BY j.created_at DESC
                             LIMIT 1) AS job_id
                      FROM tracks t
                     WHERE t.content_hash = :content_hash
                    """
                ),
                {"content_hash": content_hash},
            )
        ).first()
        if winner is None or not winner.job_id:
            raise HTTPException(
                status_code=409,
                detail="This audio is already being analysed. Retry shortly.",
            )
        return UploadResponse(
            job_id=winner.job_id,
            track_id=winner.track_id,
            status="duplicate",
            message="This audio is already in the corpus — returning the existing analysis.",
            duplicate=True,
        )

    track_row_id = inserted

    job_id = f"job_{uuid.uuid4().hex[:16]}"
    await session.execute(
        text(
            """
            INSERT INTO analysis_jobs (job_id, track_id, status, stage)
            VALUES (:job_id, :track_id, 'queued', 'queued')
            """
        ),
        {"job_id": job_id, "track_id": track_row_id},
    )
    await session.commit()

    background.add_task(
        _run_job_in_background,
        job_id,
        track_row_id,
        str(dest),
        title.strip(),
        (genre or "").strip() or None,
    )

    return UploadResponse(
        job_id=job_id,
        track_id=track_id,
        status="queued",
        message="Analysis queued. Poll /api/tracks/jobs/{job_id} for progress.",
    )


@router.get("/jobs/{job_id}", response_model=JobStatus)
async def job_status(
    job_id: str, session: AsyncSession = Depends(get_session)
) -> JobStatus:
    row = (
        await session.execute(
            text(
                """
                SELECT j.job_id, t.track_id, j.status, j.stage, j.error,
                       j.created_at, j.updated_at
                FROM analysis_jobs j
                LEFT JOIN tracks t ON t.id = j.track_id
                WHERE j.job_id = :job_id
                """
            ),
            {"job_id": job_id},
        )
    ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Job not found.")

    return JobStatus(**dict(row))


@router.get("", response_model=list[TrackSummary])
async def list_tracks(
    limit: int = 50, session: AsyncSession = Depends(get_session)
) -> list[TrackSummary]:
    """Analysed tracks, newest first, with their latest fatigue reading."""
    rows = (
        await session.execute(
            text(
                """
                SELECT
                    t.track_id, t.title, t.genre, t.duration_sec, t.created_at,
                    f.fatigue_index, f.confidence AS fatigue_confidence,
                    n.headline
                FROM tracks t
                LEFT JOIN LATERAL (
                    SELECT fatigue_index, confidence
                    FROM fatigue_snapshots
                    WHERE track_id = t.id
                    ORDER BY computed_at DESC
                    LIMIT 1
                ) f ON TRUE
                LEFT JOIN LATERAL (
                    SELECT headline
                    FROM narrative_insights
                    WHERE track_id = t.id
                    ORDER BY generated_at DESC
                    LIMIT 1
                ) n ON TRUE
                ORDER BY t.created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": min(limit, 200)},
        )
    ).mappings().all()

    return [TrackSummary(**dict(r)) for r in rows]
