"""End-to-end smoke test against a running MUSE stack.

Uploads three synthetic tracks, waits for each analysis to finish, and prints
what actually came back — narrative, fatigue reading, drivers, and the
measured acoustic values. Uses only the standard library so it runs against
the API without installing anything.

    docker compose up -d
    python scripts/make_test_audio.py testdata
    python scripts/smoke_test.py

Exits non-zero if any stage fails, so it is usable in CI.
"""

from __future__ import annotations

import json
import mimetypes
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid

API = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
TESTDATA = pathlib.Path(__file__).resolve().parent.parent / "testdata"

failures: list[str] = []


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{API}{path}", timeout=30) as r:
        return json.loads(r.read())


def post_file(path: str, file: pathlib.Path, fields: dict[str, str]) -> dict:
    """Multipart POST, hand-rolled to avoid a requests dependency."""
    boundary = f"----muse{uuid.uuid4().hex}"
    body = bytearray()

    for key, value in fields.items():
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
        body += value.encode() + b"\r\n"

    ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    body += f"--{boundary}\r\n".encode()
    body += (
        f'Content-Disposition: form-data; name="file"; filename="{file.name}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode()
    body += file.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{API}{path}",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def wait_for_job(job_id: str, timeout: float = 420.0) -> dict:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        job = get(f"/api/tracks/jobs/{job_id}")
        if job["stage"] != last:
            last = job["stage"]
            print(f"      … {last}")
        if job["status"] == "complete":
            return job
        if job["status"] == "failed":
            raise RuntimeError(job.get("error") or "analysis failed")
        time.sleep(2)
    raise TimeoutError(f"job {job_id} did not finish within {timeout:g}s")


def rule(title: str) -> None:
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")


# ── 1. Health ────────────────────────────────────────────────────────────────
rule("1. Health")
try:
    health = get("/api/health")
except urllib.error.URLError as exc:
    print(f"  cannot reach {API}: {exc}")
    print("  Is the stack up? `docker compose up -d`")
    sys.exit(1)

print(f"  status           {health['status']}")
print(f"  database         {health['database']}")
print(f"  narrative mode   {health['narrative_mode']}")
print(f"  embedding        {health['embedding_backend']}")
for c in health["connectors"]:
    print(f"  connector        {c['name']:<14s} {'enabled' if c['enabled'] else 'disabled (no credentials)'}")

if health["database"] != "ok":
    failures.append("database unreachable")

# ── 2. Upload and analyze ────────────────────────────────────────────────────
rule("2. Upload and analyze")
if not TESTDATA.exists():
    print(f"  no test audio at {TESTDATA}")
    print("  Run: python scripts/make_test_audio.py testdata")
    sys.exit(1)

files = sorted(TESTDATA.glob("*.wav")) + sorted(TESTDATA.glob("*.mp3"))
if not files:
    print(f"  {TESTDATA} contains no audio files.")
    sys.exit(1)

track_ids: list[str] = []
for f in files:
    print(f"\n  uploading {f.name} ({f.stat().st_size // 1024} KB)")
    try:
        res = post_file(
            "/api/tracks",
            f,
            {"title": f.stem.replace("_", " "), "genre": "test"},
        )
        job = wait_for_job(res["job_id"])
        track_ids.append(res["track_id"])
        print(f"      done in {job['updated_at']}")
    except Exception as exc:  # noqa: BLE001
        print(f"      FAILED: {exc}")
        failures.append(f"{f.name}: {exc}")

if not track_ids:
    print("\nNo track analysed successfully.")
    sys.exit(1)

# ── 3. Insight ───────────────────────────────────────────────────────────────
rule("3. Insight for the most recent track")
insight = get(f"/api/insights/{track_ids[-1]}")

n = insight.get("narrative")
if n:
    print(f"\n  HEADLINE   {n['headline']}")
    print(f"\n  NARRATIVE  {n['narrative']}")
    print(f"\n  ACTION     {n['actionable_insight']}")
    print(f"\n  written by {n['generation_mode']}"
          + (f" ({n['model']})" if n.get("model") else ""))
else:
    failures.append("no narrative generated")
    print("  no narrative returned")

fa = insight.get("fatigue")
if fa:
    print(f"\n  FATIGUE    {fa['fatigue_index']:.1%}  [{fa['verdict']}]"
          f"  confidence {fa['confidence']:.1%}")
    print(f"             {fa['explanation']}")
    print(f"             neighbours={fa['neighbor_count']} "
          f"supply_slope={fa['density_slope']:+.3f} "
          f"response_slope={fa['engagement_slope']:+.3f}")
else:
    failures.append("no fatigue snapshot")
    print("  no fatigue reading returned")

drivers = insight.get("drivers") or []
print(f"\n  DRIVERS    {len(drivers)}")
for d in drivers[:5]:
    print(f"    [{d['platform']}] {d['originating_event'][:70]}")
    print(f"        {d['velocity_surge']:+.0f}%  {d['engagement']} engagements")
    print(f"        {d['context_anchor_url']}")
    if not d["context_anchor_url"]:
        failures.append("driver with no source URL")

a = insight.get("acoustic")
if a:
    print(f"\n  MEASURED   {a['bpm']} BPM · {a['musical_key']} {a['mode']} "
          f"(confidence {a['key_confidence']}) · {a['duration_sec']}s")
    print(f"             centroid {a['spectral_centroid']} Hz · "
          f"dynamic range {a['dynamic_range']} dB")
    print(f"  ESTIMATED  energy {a['energy']} · valence {a['valence']} · "
          f"danceability {a['danceability']} · acousticness {a['acousticness']}")
    if a["bpm"] is None or a["musical_key"] is None:
        failures.append("acoustic features missing")
else:
    failures.append("no acoustic profile")
    print("  no acoustic profile returned")

# ── 4. Corpus and trends ─────────────────────────────────────────────────────
rule("4. Corpus and trend endpoints")
corpus = get("/api/trends/corpus")
print(f"  tracks            {corpus['tracks']}")
print(f"  fingerprinted     {corpus['tracks_with_embeddings']}")
print(f"  social signals    {corpus['social_signals']} ({corpus['signals_last_24h']} in 24h)")
print(f"  fatigue ready     {corpus['fatigue_ready']}")
print(f"                    {corpus['fatigue_ready_message']}")

if corpus["tracks_with_embeddings"] < len(track_ids):
    failures.append("some tracks were not fingerprinted")

spikes = get("/api/trends/spikes?hours=168&limit=5")
print(f"  top spikes        {len(spikes)}")
for s in spikes:
    print(f"    [{s['platform']}] {s['target_entity'][:50]} {s['velocity_spike_pct']:+.0f}%")

listed = get("/api/tracks")
print(f"  tracks listed     {len(listed)}")

# ── Verdict ──────────────────────────────────────────────────────────────────
rule("Result")
if failures:
    print("  FAILED:")
    for f in failures:
        print(f"    - {f}")
    sys.exit(1)

print("  All checks passed.")
print("  Open http://localhost:3000 to see it rendered.")
