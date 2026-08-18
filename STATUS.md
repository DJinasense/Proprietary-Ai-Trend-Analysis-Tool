# MUSE — running status & action log

Living scratchpad, same role as philo-gorillas' `STATUS.md`. Two purposes: engineering
state that doesn't belong in `README.md`, and — as of 2026-08-14 — the required log for
anything done under `CLAUDE.md`'s "Standing infrastructure permissions" section
(Cloudflare + Supabase changes made without asking first each time).

Log entries below should read like: what changed, why, and the exact values with
secrets redacted to the variable name only — written so Dima can read the actual route
taken afterward, not just that something happened.

## 2026-08-14 — Cloudflare + Supabase API access established

- Generated and verified `CLOUDFLARE_API_TOKEN` (Zone:DNS:Edit, "All zones from an
  account" — no zone exists on the Cloudflare account yet to scope narrower to;
  confirmed via `GET /client/v4/zones` returning empty). IP-filtered to inasense's
  outbound IP at creation time. Stored at
  `C:\Users\Administrator\.secrets\cloudflare.env` on inasense.
- Generated and verified `SUPABASE_ACCESS_TOKEN` (account-wide management token, no
  per-project scoping available). Confirms MUSE's project
  (`Proprietary-Ai-Trend-Analysis-Tool`, id `pcuyvsgcvhawqfkqzvgk`, region `us-west-2`,
  status `ACTIVE_HEALTHY`). Stored at `C:\Users\Administrator\.secrets\supabase.env`.
- No infrastructure changes made yet with either token — this entry just records that
  they exist and were verified against real, read-only API calls before being trusted.

See `HANDOFF-from-philo-gorillas-2026-08-14.md` in this repo for the fuller context
this came out of (also covers: cross-machine SSH between inasense and ultraprovip, the
GoDaddy PAT's non-obvious auth header format, and an open question about whether the
memory-mirror-sync setup between machines needs to change).

## 2026-08-14 — dgrvip.net added as a Cloudflare zone

- Pulled the authoritative current DNS record set for `dgrvip.net` directly from
  GoDaddy's API first, rather than trusting Cloudflare's auto-scan (good thing —
  the scan only found `www`/`_domainconnect`/`_dmarc`, missing both `trending` A
  records, the `muse` CNAME, and — critically — `philotalk`'s CNAME to Vercel,
  which is philo-gorillas' live site, not MUSE's).
- First zone-creation attempt landed in a separate, brand-new Cloudflare account
  instead of the existing `Dgromensky@gmail.com's Account` (Dima created a new
  account by mistake going through "Add a domain" the first time). Recreated it
  under the correct account; zone ID `47b58cb9d5d9b90616314acafe65509f`, status
  `pending`, assigned nameservers `brynne.ns.cloudflare.com` /
  `damien.ns.cloudflare.com`.
- Added the four missing records via API: both `trending` A records (unused
  GoDaddy leftovers, kept for fidelity), `muse` CNAME → the tunnel
  (`d34238d6-...cfargotunnel.com`, proxied), and `philotalk` CNAME → Vercel
  (unproxied, matching its GoDaddy config exactly). Verified the full 7-record
  zone contents afterward against the GoDaddy source of truth — matches exactly.
- Not yet done: tunnel public-hostname routing (blocked on this same zone not
  existing until now — retrying via the dashboard now that it does), and the
  actual nameserver switch at GoDaddy (out of scope for this section's
  pre-authorization — that's a registrar-level change, and GoDaddy isn't one of
  MUSE's two named services here; needs Dima's explicit go-ahead separately).
- `CLOUDFLARE_API_TOKEN` used for all of this is `Zone:DNS:Edit` only — doesn't
  cover Cloudflare Tunnel config, so that step needs either the dashboard or a
  differently-scoped token.
