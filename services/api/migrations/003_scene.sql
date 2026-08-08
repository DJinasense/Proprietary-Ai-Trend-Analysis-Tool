-- Scene: which music world a signal came from.
--
-- 'human' is the default and covers everything MUSE polled before this column
-- existed — charts, general music feeds, the music subreddits. 'ai' covers
-- signals from AI-music communities and tools (Suno, Udio, and the rest).
--
-- This is a column rather than a jsonb key because it is a filter dimension on
-- the trend board, not incidental metadata: every signals query can carry a
-- scene predicate, and a jsonb extraction cannot use a plain index.
--
-- Backfilling to 'human' is the honest default. Existing rows were collected by
-- queries that never asked about AI music, so 'human' is what they were sampled
-- from — it is not a claim that no AI track ever appeared among them.

ALTER TABLE social_signals
    ADD COLUMN IF NOT EXISTS scene TEXT NOT NULL DEFAULT 'human';

CREATE INDEX IF NOT EXISTS idx_signals_scene
    ON social_signals (scene, observed_at DESC);
