-- ── Upload de-duplication ────────────────────────────────────────────────────
-- The Fatigue Index answers "how crowded is this sound" by counting embedding
-- neighbours. Re-uploading the same file therefore does not just waste disk —
-- it manufactures neighbours, inflating density and confidence for every track
-- in that region. A corpus of one track uploaded twelve times reads as a
-- saturated lane. Content-addressing the audio closes that off at the source.
--
-- Backfill note: rows predating this migration keep content_hash NULL. The
-- unique index is partial so those NULLs coexist; de-duplication applies to
-- everything ingested from here on.

ALTER TABLE tracks ADD COLUMN IF NOT EXISTS content_hash TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_tracks_content_hash
    ON tracks (content_hash)
    WHERE content_hash IS NOT NULL;

COMMENT ON COLUMN tracks.content_hash IS
    'SHA-256 of the uploaded bytes. NULL for rows ingested before 002.';
