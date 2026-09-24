# MUSE — Cloud Deployment & Online Hosting Guide

This guide describes how to host MUSE 100% online without local Docker dependencies or running files on your local machine.

---

## System Architecture

```
                  ┌────────────────────────────────────────────────────────┐
                  │                 DNS / Custom Domain                    │
                  │                   Cloudflare DNS                       │
                  │             (muse.dgrvip.net / dgrvip.net)             │
                  └───────────────┬────────────────────────┬───────────────┘
                                  │                        │
                                  ▼                        ▼
               ┌───────────────────────┐      ┌────────────────────────┐
               │    Frontend Web App   │      │      Backend API       │
               │        Vercel         │      │     Render / Railway   │
               │   (apps/web Next.js)  │      │  (services/api FastAPI)│
               └───────────────┬───────┘      └────────────┬───────────┘
                               │                           │
                               │  HTTPS API Calls          │ DB queries
                               └──────────────────────────►│ (pgvector)
                                                           │
                                                           ▼
                                              ┌────────────────────────┐
                                              │    Database Storage    │
                                              │   Supabase Postgres    │
                                              │ (pcuyvsgcvhawqfkqzvgk) │
                                              └────────────────────────┘
```

---

## Step 1: Database Setup (Supabase)

MUSE uses PostgreSQL with `pgvector` for acoustic embeddings and trend storage.

1. **Active Supabase Project**: `Proprietary-Ai-Trend-Analysis-Tool` (ID: `pcuyvsgcvhawqfkqzvgk`).
2. **Connection String Format**:
   ```env
   MUSE_DATABASE_URL=postgresql+asyncpg://postgres:[YOUR-PASSWORD]@db.pcuyvsgcvhawqfkqzvgk.supabase.co:5432/postgres
   ```
3. Tables and migrations (`services/api/migrations/`) are automatically initialized on startup by FastAPI (`muse.db.run_migrations()`).

---

## Step 2: Deploy Backend API & Worker (Render or Railway)

The backend consists of:
1. **Web Service**: FastAPI (`muse.main:app`) serving REST endpoints.
2. **Background Worker**: Ingestion scheduler (`python -m muse.worker.scheduler`) running 24/7 social trend polling.

### Option A: Render (Automated via Blueprint `render.yaml`)
1. Go to [Render Blueprints](https://dashboard.render.com/blueprints).
2. Connect your GitHub repository `DJinasense/Proprietary-Ai-Trend-Analysis-Tool`.
3. Render reads `render.yaml` and provisions both services automatically.
4. Set Environment Variables in Render Dashboard:
   - `MUSE_DATABASE_URL`: Your Supabase URI.
   - `MUSE_ANTHROPIC_API_KEY`: Anthropic API Key.
   - `MUSE_EMBEDDING_BACKEND`: `stats` (Fast spectral embedder, no heavy PyTorch downloads required).

---

## Step 3: Deploy Frontend Web App (Vercel)

1. Go to [Vercel Dashboard](https://vercel.com/new).
2. Import repository `DJinasense/Proprietary-Ai-Trend-Analysis-Tool`.
3. Set **Root Directory** to `apps/web`.
4. Add Environment Variable:
   - `NEXT_PUBLIC_API_BASE`: `https://muse-api.onrender.com` (or your custom domain `https://api-muse.dgrvip.net`).
5. Click **Deploy**. Vercel will build and host Next.js automatically on every `git push`.

---

## Step 4: Custom Domain Routing (Cloudflare)

In Cloudflare DNS for `dgrvip.net`:
1. `muse.dgrvip.net` → CNAME to Vercel deployment URL (`cname.vercel-dns.com`).
2. `api-muse.dgrvip.net` → CNAME to Render backend URL.
