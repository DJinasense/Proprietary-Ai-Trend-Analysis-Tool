# MUSE — Claude instructions

This file is new as of 2026-08-14 — created for the standing-permissions section below.
It doesn't yet carry the fuller project-summary that philo-gorillas' `CLAUDE.md` has
(architecture, what's built, immediate tasks); whoever's actually driving MUSE
day-to-day should fill that in when it's useful. See `README.md` and
`Full Instructional Layout.pdf` in this repo for the existing project documentation in
the meantime.

---

## Standing infrastructure permissions (added 2026-08-14, at Dima's request)

Mirrors the same section in `D:\Projects\philo-gorillas\CLAUDE.md`, written the same
day for the same reason: cutting the back-and-forth of re-asking for things Dima's
already said yes to in spirit. Scoped to MUSE's own infrastructure — doesn't extend to
other repos/projects unless stated there too.

**Pre-authorized, no need to check in first:**
- **Cloudflare** — DNS record management (A/CNAME/TXT/MX etc.) and Cloudflare Tunnel
  configuration, for domains/tunnels used by this project (e.g. the `muse.dgrvip.net`
  migration once a zone exists there to configure).
- **Supabase** — configuration changes needed to keep this project's database/backend
  working (connection settings, schema changes this project's code requires).

**Still requires asking, no exceptions, regardless of the above:**
- Any financial transaction, payment, or fund transfer of any kind, and entering
  payment/banking credentials anywhere — this line does not move.
- Permanently destructive actions: dropping a table, deleting a DNS zone outright,
  deleting a Supabase project, hard-deleting data. Additive/reversible changes are
  covered above; irreversible ones are not.
- Anything outside these two named services, or outside this project's own
  infrastructure.
- Anything in Claude's own hard-line prohibited category (financial trades,
  security/system settings, CAPTCHA bypass, downloading/executing untrusted files) —
  not Claude's to waive even here.

**In exchange: everything done under this gets logged, so it's readable and
learnable, not just done silently.** Every action taken under this section gets a
dated entry in `STATUS.md` (new file, same pattern as philo-gorillas') — what changed,
why, and the exact values (secrets redacted to the variable name only) — so Dima can
read and study the actual route taken afterward instead of watching in real time or
hunting for what happened.

**Access note (2026-08-14):** `CLOUDFLARE_API_TOKEN` and `SUPABASE_ACCESS_TOKEN` are
both live and verified — see `C:\Users\Administrator\.secrets\cloudflare.env` and
`.secrets\supabase.env` on inasense. The Cloudflare token is currently scoped to "All
zones from an account" (no zone exists yet to narrow it to) and IP-filtered to
inasense's outbound IP at time of creation — re-scope narrower once `dgrvip.net` (or
whichever zone MUSE ends up using) is actually added to Cloudflare. The Supabase token
is account-wide (management tokens don't support per-project scoping) and can see
three other projects on the account beyond MUSE's own (`Proprietary-Ai-Trend-Analysis-Tool`,
id `pcuyvsgcvhawqfkqzvgk`) — be deliberate about only touching MUSE's project with it.
