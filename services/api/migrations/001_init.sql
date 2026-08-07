-- ═══════════════════════════════════════════════════════════════════════════
-- MUSE — initial schema
--
-- The spec PDF split this across MongoDB (documents) + Pinecone (vectors).
-- Postgres with pgvector does both, which means the Fatigue Index can JOIN
-- embedding neighbours against engagement time-series in a single query —
-- impossible when the vectors live in a separate service.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ── Artists ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS artists (
    id            BIGSERIAL PRIMARY KEY,
    artist_key    TEXT UNIQUE NOT NULL,
    display_name  TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Tracks ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tracks (
    id              BIGSERIAL PRIMARY KEY,
    track_id        TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    artist_id       BIGINT REFERENCES artists(id) ON DELETE SET NULL,
    genre           TEXT,
    -- Where the audio landed on disk. NULL until upload completes.
    media_path      TEXT,
    duration_sec    DOUBLE PRECISION,
    -- released_at drives recency weighting in the Fatigue Index. Defaults to
    -- ingestion time when the artist doesn't supply a real release date.
    released_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tracks_genre       ON tracks (genre);
CREATE INDEX IF NOT EXISTS idx_tracks_released_at ON tracks (released_at DESC);
CREATE INDEX IF NOT EXISTS idx_tracks_title_trgm  ON tracks USING gin (title gin_trgm_ops);

-- ── Acoustic features ──────────────────────────────────────────────────────
-- Every column here is COMPUTED FROM THE AUDIO by librosa. None of it comes
-- from Spotify, whose audio-features endpoint was deprecated for new apps in
-- November 2024.
CREATE TABLE IF NOT EXISTS audio_features (
    track_id            BIGINT PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
    bpm                 DOUBLE PRECISION,
    beat_strength       DOUBLE PRECISION,
    musical_key         TEXT,
    mode                TEXT,
    key_confidence      DOUBLE PRECISION,
    energy              DOUBLE PRECISION,
    valence             DOUBLE PRECISION,
    danceability        DOUBLE PRECISION,
    acousticness        DOUBLE PRECISION,
    spectral_centroid   DOUBLE PRECISION,
    spectral_bandwidth  DOUBLE PRECISION,
    spectral_rolloff    DOUBLE PRECISION,
    spectral_flatness   DOUBLE PRECISION,
    zero_crossing_rate  DOUBLE PRECISION,
    rms_mean            DOUBLE PRECISION,
    dynamic_range       DOUBLE PRECISION,
    -- Full descriptor block, kept for explainability in the narrative layer.
    raw                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    analyzed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Acoustic embeddings ────────────────────────────────────────────────────
-- Fixed at 512 dims so the "stats" and "clap" backends share one column.
-- Backends with a smaller native dimension zero-pad the tail; zero padding
-- leaves cosine similarity mathematically unchanged.
CREATE TABLE IF NOT EXISTS track_embeddings (
    track_id     BIGINT PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
    embedding    vector(512) NOT NULL,
    backend      TEXT NOT NULL,
    native_dim   INTEGER NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_track_embeddings_hnsw
    ON track_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_track_embeddings_backend ON track_embeddings (backend);

-- ── Social signals ─────────────────────────────────────────────────────────
-- One row per observed spike. context_anchor_url is NOT NULL by design: the
-- "where is this data from?" complaint about Exploding Topics is answered at
-- the schema level — an unattributable signal cannot be stored.
CREATE TABLE IF NOT EXISTS social_signals (
    id                       BIGSERIAL PRIMARY KEY,
    signal_id                TEXT UNIQUE NOT NULL,
    platform                 TEXT NOT NULL,
    connector                TEXT NOT NULL,
    target_entity            TEXT NOT NULL,
    entity_type              TEXT,
    velocity_spike_pct       DOUBLE PRECISION NOT NULL,
    engagement_count         BIGINT NOT NULL DEFAULT 0,
    associated_keywords      TEXT[] NOT NULL DEFAULT '{}',
    context_anchor_url       TEXT NOT NULL,
    observed_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw                      JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_signals_observed_at ON social_signals (observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_platform    ON social_signals (platform, observed_at DESC);
-- GIN on the keyword array: the spec's Mongo `$in` lookup was a full scan.
CREATE INDEX IF NOT EXISTS idx_signals_keywords    ON social_signals USING gin (associated_keywords);

-- ── Fatigue snapshots ──────────────────────────────────────────────────────
-- Time-series of saturation per track, so trajectory can be charted and the
-- index can be audited after the fact.
CREATE TABLE IF NOT EXISTS fatigue_snapshots (
    id                  BIGSERIAL PRIMARY KEY,
    track_id            BIGINT NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    fatigue_index       DOUBLE PRECISION NOT NULL,
    confidence          DOUBLE PRECISION NOT NULL,
    neighbor_count      INTEGER NOT NULL,
    density_recent      DOUBLE PRECISION NOT NULL,
    density_slope       DOUBLE PRECISION NOT NULL,
    engagement_slope    DOUBLE PRECISION NOT NULL,
    components          JSONB NOT NULL DEFAULT '{}'::jsonb,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_fatigue_track_time
    ON fatigue_snapshots (track_id, computed_at DESC);

-- ── Narrative insights ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS narrative_insights (
    id                  BIGSERIAL PRIMARY KEY,
    track_id            BIGINT NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    headline            TEXT NOT NULL,
    narrative           TEXT NOT NULL,
    actionable_insight  TEXT NOT NULL,
    -- Attribution: which signals the narrative was built from, with URLs.
    primary_drivers     JSONB NOT NULL DEFAULT '[]'::jsonb,
    fatigue_index       DOUBLE PRECISION,
    fatigue_confidence  DOUBLE PRECISION,
    -- "llm" when Claude wrote it, "deterministic" for the rules-based fallback
    -- used when no API key is configured. Surfaced in the UI — the user always
    -- knows whether they're reading a model's synthesis or a template.
    generation_mode     TEXT NOT NULL DEFAULT 'deterministic',
    model               TEXT,
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_insights_track_time
    ON narrative_insights (track_id, generated_at DESC);

-- ── Analysis jobs ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS analysis_jobs (
    id            BIGSERIAL PRIMARY KEY,
    job_id        TEXT UNIQUE NOT NULL,
    track_id      BIGINT REFERENCES tracks(id) ON DELETE CASCADE,
    status        TEXT NOT NULL DEFAULT 'queued',
    stage         TEXT,
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON analysis_jobs (status, created_at DESC);

-- ── Connector cursors ──────────────────────────────────────────────────────
-- Lets each connector resume where it left off across worker restarts.
CREATE TABLE IF NOT EXISTS connector_state (
    connector    TEXT PRIMARY KEY,
    cursor       TEXT,
    last_run_at  TIMESTAMPTZ,
    last_error   TEXT,
    state        JSONB NOT NULL DEFAULT '{}'::jsonb
);
