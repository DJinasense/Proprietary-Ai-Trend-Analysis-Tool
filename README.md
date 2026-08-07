# MUSE — Music Utility & Structural Intelligence Engine

Narrative-first music trend intelligence. MUSE does not hand you another chart.
It analyses a track you own, fingerprints its sound, compares it against
everything else in your corpus, cross-references live social signals, and
returns a plain-language sentence explaining **why** something is moving —
plus a **Fatigue Index** telling you how much room is left in that lane.

---

## What it actually does

| Tier | What runs | Where |
|---|---|---|
| 1. Ingestion | librosa DSP on your uploaded audio + polling of open social sources | `muse/audio`, `muse/connectors` |
| 2. Contextual cross-reference | Matches title/genre/keyword against recent social spikes | `muse/intelligence/correlation.py` |
| 3. Narrative synthesis | Fatigue Index, then a Claude-written explanation with a deterministic fallback | `muse/intelligence/fatigue.py`, `narrative.py` |
| 4. Delivery | FastAPI + a Next.js dashboard | `muse/routers`, `apps/web` |

---

## Quick start

```bash
cp .env.example .env
```

Fill in `MUSE_ANTHROPIC_API_KEY` if you want model-written narratives. Everything
else is optional — each connector without credentials is skipped, and the
narrative layer falls back to a deterministic summary assembled from the
measured signals.

```bash
docker compose up -d --build
```

```bash
cd apps/web && npm install && npm run dev
```

Then open http://localhost:3000. API docs are at http://localhost:8000/docs.

**Ports:** web `3000`, API `8000`, Postgres `5433` (deliberately not 5432, so it
doesn't collide with a local Postgres).

### Verify it works

```bash
python scripts/make_test_audio.py testdata && python scripts/smoke_test.py
```

This uploads three synthetic tracks with a known tempo and key, waits for each
analysis, and prints the narrative, the fatigue reading, the drivers with their
source URLs, and the measured acoustic values. It exits non-zero if any stage
fails. Stdlib only — nothing to install.

---

## Honest limits

These are stated up front because the whole point of this tool is not
overstating what it knows.

**No TikTok or Instagram data.** TikTok's Research API is gated to accredited
academic institutions in the US/EU; Instagram has no usable trend endpoint.
Anything claiming open access to either is scraping against terms of service.
MUSE ships with Reddit, YouTube Data API, Bluesky, and Google Trends — all free
and permitted. The `Connector` interface in `muse/connectors/base.py` exists so a
licensed aggregator (Soundcharts, Songstats, Chartmetric) becomes one new file
with no downstream changes.

**No Spotify audio features.** Spotify deprecated `audio-features`,
`audio-analysis`, `recommendations`, and related-artists for new applications in
November 2024. MUSE computes tempo, key, and spectral shape itself from the
waveform, which also means it works on unreleased material that no platform has
ever seen.

**Measured is kept separate from estimated.** Tempo, key, spectral centroid,
RMS, and dynamic range are measured from the audio. Energy, valence,
danceability, and acousticness are documented heuristics derived from those
measurements — labelled as such in the schema, the API response, the LLM prompt,
and the UI. They are useful for comparing tracks inside this corpus. They are
not a drop-in replacement for a platform-provided figure.

**The Fatigue Index needs a corpus.** It measures whether the supply of similar
music is rising *while* engagement response falls — a scissors, not a single
line. Rising supply with rising engagement is a boom, not fatigue, and scoring
it as fatigue is the failure mode this design avoids. With a handful of tracks
loaded, readings are honest but low-confidence, and the UI says so rather than
hiding it behind a confident-looking percentage.

**Every signal is attributable.** `social_signals.context_anchor_url` is
`NOT NULL` at the schema level: a datapoint that can't say where it came from
cannot be stored. Every driver in the UI links back to the exact post.

**Correlation has a floor, and it says so when nothing clears it.** A shared
keyword is not a cause. A single common token overlapping between a track title
and a news story is a collision, not evidence — so one is not enough. MUSE
accepts a signal as a driver only on a verbatim multi-word title match, two or
more distinctive terms, or one distinctive term from a source that was already
asking about music. Terms carried by more than 15% of all signals in the window
are treated as this corpus's own boilerplate and cannot carry a match alone.
Each accepted driver shows what it matched on. When nothing clears the bar the
answer is "no external driver detected", which is a finding rather than a gap.

**Bluesky now requires credentials.** `public.api.bsky.app` returns `403` for
unauthenticated `app.bsky.feed.searchPosts` — public profile reads on the same
host still work, so this is a deliberate narrowing rather than an outage. The
connector logs in with an app password and reports itself disabled without one,
instead of appearing live in the status bar while returning nothing.

---

## Configuration

All environment variables are `MUSE_`-prefixed. See `.env.example` for the full
list. The ones worth knowing:

| Variable | Default | Notes |
|---|---|---|
| `MUSE_ANTHROPIC_API_KEY` | — | Blank ⇒ deterministic narratives |
| `MUSE_EMBEDDING_BACKEND` | `stats` | `stats` (fast, no download) or `clap` (~600MB first run) |
| `MUSE_FATIGUE_NEIGHBOR_RADIUS` | `0.82` | Cosine similarity above which a track counts as a neighbour |
| `MUSE_FATIGUE_HALF_LIFE_DAYS` | `90` | Recency decay on neighbour density |
| `MUSE_FATIGUE_MIN_NEIGHBORS` | `12` | Below this, readings are reported as low-confidence |
| `MUSE_INGEST_INTERVAL_SECONDS` | `900` | Social polling cadence |
| `MUSE_CORRELATION_MIN_DISTINCT_TERMS` | `2` | Distinctive terms needed to call a signal a driver |
| `MUSE_CORRELATION_MAX_DF_RATIO` | `0.15` | Above this share of all signals, a term is boilerplate |

### Getting connector credentials

All of these go in `.env` in the repo root, `MUSE_`-prefixed. `docker compose`
reads that file, so `docker compose up -d api worker` after editing is what
picks up a change.

- **Reddit** — https://www.reddit.com/prefs/apps → create a **script** app.
  `MUSE_REDDIT_CLIENT_ID` is the string under the app name, `MUSE_REDDIT_CLIENT_SECRET`
  is the field labelled *secret*. Free tier is 100 queries/min per OAuth client
  and is non-commercial only; commercial use needs an agreement with Reddit.
  Set `MUSE_REDDIT_USER_AGENT` to something identifying — generic agents are rejected.
- **YouTube** — Google Cloud Console → enable **YouTube Data API v3** → Credentials
  → API key → `MUSE_YOUTUBE_API_KEY`. Restrict the key to that one API. Free quota
  is 10,000 units/day and a search costs 100, so roughly 100 searches a day.
- **Bluesky** — **required**, not optional. Settings → Privacy and security →
  App passwords. Set `MUSE_BLUESKY_IDENTIFIER` (your handle) and
  `MUSE_BLUESKY_APP_PASSWORD`. Never the account password.
- **Google Trends** — no key; unofficial endpoint, best-effort.

---

## Layout

```
docker-compose.yml          db (pgvector) + api + ingestion worker
services/api/
  migrations/001_init.sql   schema, HNSW index, GIN keyword index
  muse/
    audio/                  librosa feature extraction + embedding backends
    connectors/             Reddit, YouTube, Bluesky, Google Trends
    intelligence/           fatigue, correlation, narrative synthesis
    routers/                tracks, insights, trends
    pipeline.py             the four tiers, end to end
    worker/scheduler.py     periodic social ingestion
apps/web/                   Next.js dashboard
```

---

## Notes on the source specification

The build follows the MUSE spec's product thesis and design system closely. Four
deviations were necessary, each for a stated reason:

1. **Postgres + pgvector replaces MongoDB + Pinecone + Kafka.** The Fatigue Index
   has to join embedding neighbours against engagement time-series in one query.
   With vectors in a separate service that join is impossible.
2. **The spec's `compute_fatigue_index()` is replaced.** It queried the vector
   index with `np.random.uniform(-1, 1, 512)` and averaged the cosine scores. In
   512 dimensions a random vector is near-orthogonal to everything, so the output
   was uncorrelated with the track being analysed — a random number rendered as a
   percentage.
3. **Acoustic features are computed locally** rather than fetched from Spotify,
   whose relevant endpoints are deprecated for new applications.
4. **Web only for v1.** The spec's SwiftUI and Jetpack Compose layouts remain as
   reference for a native build; the dashboard is responsive and works on a phone.

Several spec snippets also did not execute as written — `pydantic.BaseSettings`
(removed in Pydantic v2), `pinecone.PodSpec` (legacy client), module-level
`await`, and `if name == "main"` with the dunders stripped. Those are corrected
throughout.
