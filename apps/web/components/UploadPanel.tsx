"use client";

import { useRef, useState } from "react";
import { getJob, uploadTrack } from "@/lib/api";
import type { JobStatus } from "@/lib/types";

// Keys match the stage values written by services/api/muse/pipeline.py.
const STAGE_COPY: Record<string, string> = {
  queued: "Queued",
  acoustic_analysis: "Decoding audio and extracting features",
  correlation: "Cross-referencing social signals",
  fatigue: "Measuring saturation",
  narrative: "Writing the narrative",
  done: "Complete",
};

export default function UploadPanel({
  onComplete,
}: {
  onComplete: (trackId: string) => void;
}) {
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [genre, setGenre] = useState("");
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function poll(jobId: string) {
    // Analysis is CPU-bound and runs out-of-band, so the only honest UI is one
    // that reports the stage it is actually on.
    for (let i = 0; i < 300; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      let status: JobStatus;
      try {
        status = await getJob(jobId);
      } catch {
        continue; // transient; keep polling
      }
      setJob(status);
      if (status.status === "complete") {
        setBusy(false);
        if (status.track_id) onComplete(status.track_id);
        return;
      }
      if (status.status === "failed") {
        setBusy(false);
        setError(status.error || "Analysis failed.");
        return;
      }
    }
    setBusy(false);
    setError("Analysis timed out after 7 minutes. Check the API logs.");
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);

    const file = fileRef.current?.files?.[0];
    if (!file) {
      setError("Choose an audio file first.");
      return;
    }
    if (!title.trim()) {
      setError("A title is required.");
      return;
    }

    const form = new FormData();
    form.append("file", file);
    form.append("title", title.trim());
    if (artist.trim()) form.append("artist", artist.trim());
    if (genre.trim()) form.append("genre", genre.trim());

    setBusy(true);
    setJob(null);
    try {
      const res = await uploadTrack(form);
      if (res.duplicate) {
        // Nothing was queued — the API handed back the original analysis. Say so
        // plainly rather than showing a fake progress run, then jump to it.
        setBusy(false);
        setNotice(res.message);
        onComplete(res.track_id);
        return;
      }
      setJob({
        job_id: res.job_id,
        track_id: res.track_id,
        status: "queued",
        stage: "queued",
        error: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
      await poll(res.job_id);
    } catch (err) {
      setBusy(false);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <section className="card">
      <h2>Analyze a track</h2>
      <form onSubmit={submit}>
        <label htmlFor="file">Audio file (MP3, WAV, FLAC, M4A, OGG, AIFF)</label>
        <input
          id="file"
          ref={fileRef}
          type="file"
          accept=".mp3,.wav,.flac,.m4a,.aac,.ogg,.aiff,.aif,audio/*"
          disabled={busy}
        />

        <label htmlFor="title">Title</label>
        <input
          id="title"
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Midnight Static"
          disabled={busy}
        />

        <label htmlFor="artist">Artist (optional)</label>
        <input
          id="artist"
          type="text"
          value={artist}
          onChange={(e) => setArtist(e.target.value)}
          disabled={busy}
        />

        <label htmlFor="genre">Genre (optional)</label>
        <input
          id="genre"
          type="text"
          value={genre}
          onChange={(e) => setGenre(e.target.value)}
          placeholder="hyperpop"
          disabled={busy}
        />

        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Analyzing…" : "Run analysis"}
        </button>
      </form>

      {busy && job && (
        <div className="progress">
          <span className="spinner" />
          {STAGE_COPY[job.stage ?? ""] ?? job.stage ?? job.status}…
        </div>
      )}

      {notice && <div className="notice">{notice}</div>}

      {error && <div className="error">{error}</div>}
    </section>
  );
}
