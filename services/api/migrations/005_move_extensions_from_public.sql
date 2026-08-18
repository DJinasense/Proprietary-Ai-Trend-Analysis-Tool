-- ── Move extensions out of the public schema ────────────────────────────────
-- 001_init.sql ran `CREATE EXTENSION vector` / `CREATE EXTENSION pg_trgm`
-- without a target schema, so both landed in `public` — flagged by Supabase's
-- advisor as "Extension in Public". Objects in `public` are the most exposed
-- in the database (widest default grants, first hit on a manipulated
-- search_path), so extensions conventionally live in their own schema
-- instead. This is a hygiene fix, not an access-control one: unlike RLS, it
-- doesn't change who can reach any data.
--
-- ALTER EXTENSION ... SET SCHEMA relocates the extension's types, operators,
-- and opclasses by their existing catalog entries — it does not drop and
-- recreate them. That means every object already depending on them keeps
-- working unchanged after the move:
--   * tracks.title's gin index on gin_trgm_ops (001_init.sql:39)
--   * track_embeddings.embedding, typed `vector(512)`, and its hnsw index on
--     vector_cosine_ops (001_init.sql:73-82)
--
-- What *does* need help is anything written after this migration that names
-- `vector(...)`, `gin_trgm_ops`, `vector_cosine_ops`, etc. unqualified — those
-- resolve through search_path. Adding `extensions` to the database's default
-- search_path keeps that working without schema-qualifying every reference.
-- current_database() is used instead of a literal name because it differs
-- between the local compose Postgres and wherever this runs in Supabase.

CREATE SCHEMA IF NOT EXISTS extensions;

ALTER EXTENSION vector   SET SCHEMA extensions;
ALTER EXTENSION pg_trgm  SET SCHEMA extensions;

DO $$
BEGIN
    EXECUTE format(
        'ALTER DATABASE %I SET search_path TO public, extensions',
        current_database()
    );
END $$;

-- Only affects new sessions. This migration's own connection keeps whatever
-- search_path it started with, which is fine — it issues no further
-- extension-dependent DDL after this point.
