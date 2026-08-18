# Handoff from the philo-gorillas session (2026-08-14)

Written by the Claude Code session working in `D:\Projects\philo-gorillas` on inasense,
for whichever session picks up MUSE next. Covers infrastructure that's now shared
across both projects, plus two things MUSE specifically needs to finish.

## 1. Cross-machine SSH is now live — "ClaudiVersal"

Both of Dima's machines are reachable from a session running on either one, over
Tailscale, with a matching PowerShell 5.1 default shell:

```
ssh inasense      # or: ssh office   — 100.110.104.63, user Administrator
ssh ultraprovip   # or: ssh ultravip / ssh dgr — 100.77.57.25, user DGR
```

Auth is key-based (inasense's `~/.ssh/id_ed25519`, public half added to ultraprovip's
`administrators_authorized_keys`) — no password prompt. Config lives in
`C:\Users\Administrator\.ssh\config` on inasense. If a session on ultraprovip needs the
reverse direction (SSH into inasense), that's not set up yet — ask Dima, same process
(generate a key there, get its public half into inasense's `administrators_authorized_keys`).

Two real gotchas hit while setting this up, worth knowing before they bite twice:
- Windows OpenSSH's admin-account auth file is `%ProgramData%\ssh\administrators_authorized_keys`
  specifically — NOT the per-user `~/.ssh/authorized_keys`, which is silently ignored
  for accounts in the Administrators group.
- `whoami`/`$env:USERNAME` before assuming the account name — ultraprovip's real login
  is `DGR`, not `Administrator` (that built-in account is likely disabled there).

## 2. Local secrets convention (shared across projects, not project-scoped)

`C:\Users\Administrator\.secrets\` on inasense — one `.env`-style file per service,
`chmod 600`, never in any git repo. Currently holds:
- `godaddy.env` (`GODADDY_PAT`) — a GoDaddy Personal Access Token. Auth header is
  **`Authorization: Bearer <token>`** (GoDaddy's newer PAT format — NOT the classic
  `sso-key key:secret` scheme most docs describe). Confirmed working, can see
  `dgrvip.net` plus Dima's other domains.
- `vercel.env` (`VERCEL_TOKEN`) — scoped to Dima's Vercel **team** (not personal
  account), confirmed working against the philo-gorillas project
  (`prj_MHSRmClzwhxhiGpbxwov21pQtSfO`, team `team_Sobv1MI7sCNtzuJDGwffI85s`).

**Done, MUSE-specific — both confirmed working 2026-08-14:**
- `cloudflare.env` (`CLOUDFLARE_API_TOKEN`) — `Authorization: Bearer <token>` (standard
  Cloudflare format, no surprises like GoDaddy's). Verified via
  `GET /client/v4/user/tokens/verify`. Scoped "All zones from an account" (Zone:DNS:Edit)
  because no zone exists on the Cloudflare account yet to scope narrower to — confirmed
  via `GET /client/v4/zones` returning empty. **Re-scope to the specific zone once
  `dgrvip.net` (or whatever zone MUSE ends up using) actually gets added to Cloudflare**
  — this token is broader than it needs to be until then. Also IP-filtered to inasense's
  outbound IP (`99.162.252.223` at time of creation) — if that ISP-assigned IP changes,
  the token will start failing until updated; not a bug, just a thing to remember.
- `supabase.env` (`SUPABASE_ACCESS_TOKEN`) — verified via `GET /v1/projects` on the
  Supabase Management API. Confirms MUSE's actual project: `Proprietary-Ai-Trend-Analysis-Tool`,
  id `pcuyvsgcvhawqfkqzvgk`, region `us-west-2`, status `ACTIVE_HEALTHY`. Three other
  projects also visible on this account (DGR - WORKS, Claudius, community-board — all
  currently INACTIVE) — this token isn't scoped to MUSE alone, it's account-wide
  (Supabase management tokens don't support per-project scoping), so be deliberate about
  only touching the MUSE project with it.

Both live in `C:\Users\Administrator\.secrets\` now, same pattern as GoDaddy/Vercel.
When testing any of these four going forward, hit a real read-only endpoint and check
the actual response — don't just trust that a paste "looks right."

## 3. Standing infrastructure permissions — apply the equivalent to MUSE's CLAUDE.md

philo-gorillas' `CLAUDE.md` now has a "Standing infrastructure permissions" section
(added 2026-08-14) that pre-authorizes routine, non-destructive changes — DNS records,
env vars, deploy config — on that project's own accounts (GoDaddy + Vercel there),
without asking each time. Full financial/destructive/security-setting actions are
explicitly carved out and stay hard-blocked regardless. Every action taken under it
gets logged with a dated entry in that project's STATUS.md — what changed, why, exact
values with secrets redacted to the variable name — so Dima can read the actual route
taken afterward instead of watching in real time.

Dima wants the same pattern in MUSE, scoped to **Cloudflare + Supabase** (the two
services that are actually MUSE's, not philo-gorillas'). Recommend copying the
structure from `D:\Projects\philo-gorillas\CLAUDE.md` (search for "Standing
infrastructure permissions"), swap the two named services, and point the logging
commitment at whatever MUSE's own status/log file is (check if one already exists in
this repo before inventing a new one — README.md and the two docs at the repo root may
already serve that role here).

## 4. The memory-mirror-sync conflict (background, not yet resolved)

Both this project's dream skill and philo-gorillas' independently hit the same
discovery this session: `~/.claude/memory/` on inasense is documented (in this
machine's own top-level CLAUDE.md) as a **one-way mirror pushed from `C:\Users\DGR`**
— edits made directly here are liable to be silently overwritten by the next sync.
Concretely proved: philo-gorillas' dream report got overwritten mid-conversation by
what looks like this same MUSE session's own dream run happening concurrently.

**Recommendation given to Dima** (not yet implemented, needs his decision + likely
his hands on the DGR/ultraprovip side): move memory to a git-backed repo instead of
the current one-way push, with per-project write ownership — whichever machine
actually runs a project owns writing its memory (inasense owns philo-gorillas + MUSE +
whatever else runs here), each `/dream` run does pull → write only its owned files →
commit → push, instead of blind overwrite. This is what "dream skill synced with
UltraVIPpro's Claude Desktop" actually needs to become non-fragile — worth raising
with Dima directly rather than assuming it's this session's call to make alone.

Note also: **Claude Desktop and Claude Code may not share the same memory/context
mechanism at all** — this whole `~/.claude/memory/` system is Claude Code's. Before
building toward "synced with Claude Desktop," confirm what Desktop's own memory
feature actually is and whether it's the same store, a different one, or something
that doesn't apply here.

## 5. What NOT to re-litigate

- GoDaddy's `dgrvip.net` DNS is confirmed correctly configured for `philotalk.dgrvip.net`
  (CNAME → Vercel) — don't re-diagnose that specific record, it's done.
- The GoDaddy PAT format (`Authorization: Bearer`, not `sso-key`) took real back-and-forth
  to nail down — trust section 2 above rather than re-deriving it from GoDaddy's own docs,
  which mostly describe the older scheme.
