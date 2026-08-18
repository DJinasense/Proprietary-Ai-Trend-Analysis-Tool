-- ── Lock down the Supabase PostgREST surface ────────────────────────────────
-- MUSE never talks to Postgres through Supabase's client SDK, Auth, or
-- PostgREST — the API service connects directly via MUSE_DATABASE_URL
-- (services/api/muse/db.py). But Supabase auto-exposes every table in the
-- `public` schema over its REST API using the project's `anon` key, which is
-- meant to be embeddable and is not a secret. With Row-Level Security off,
-- that REST API can read/write/delete every row in every table below to
-- anyone holding the project URL and anon key.
--
-- Enabling RLS with no policies makes those tables default-deny for the
-- anon/authenticated roles PostgREST uses. It does not affect this app: the
-- backend connects with the Postgres owner/service-role credentials, which
-- bypass RLS. If a future feature needs the public API to reach one of these
-- tables directly, add a scoped policy for it then — don't relax this
-- wholesale.

ALTER TABLE artists            ENABLE ROW LEVEL SECURITY;
ALTER TABLE tracks             ENABLE ROW LEVEL SECURITY;
ALTER TABLE audio_features     ENABLE ROW LEVEL SECURITY;
ALTER TABLE track_embeddings   ENABLE ROW LEVEL SECURITY;
ALTER TABLE social_signals     ENABLE ROW LEVEL SECURITY;
ALTER TABLE fatigue_snapshots  ENABLE ROW LEVEL SECURITY;
ALTER TABLE narrative_insights ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_jobs      ENABLE ROW LEVEL SECURITY;
ALTER TABLE connector_state    ENABLE ROW LEVEL SECURITY;
