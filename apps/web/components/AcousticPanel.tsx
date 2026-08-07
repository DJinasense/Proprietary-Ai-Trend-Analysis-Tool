"use client";

import type { AcousticSummary } from "@/lib/types";

function num(v: number | null, digits = 2, suffix = "") {
  return v === null || v === undefined ? "—" : `${v.toFixed(digits)}${suffix}`;
}

function pct(v: number | null) {
  return v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;
}

function Feat({
  label,
  value,
  estimated = false,
}: {
  label: string;
  value: string;
  estimated?: boolean;
}) {
  return (
    <div className={estimated ? "feat estimated" : "feat"}>
      <b>{value}</b>
      <span>{label}</span>
    </div>
  );
}

export default function AcousticPanel({ a }: { a: AcousticSummary }) {
  const mins = a.duration_sec ? Math.floor(a.duration_sec / 60) : 0;
  const secs = a.duration_sec ? Math.round(a.duration_sec % 60) : 0;

  return (
    <section className="card">
      <h2>Acoustic Profile</h2>

      {/* The measured/estimated split runs all the way through the stack —
          schema, API, and prompt — because presenting a heuristic with the
          same authority as a DSP measurement is how tools in this category
          lose trust. */}
      <div className="feat-group">
        <div className="feat-label">Measured</div>
        <div className="feat-note">
          Computed directly from the waveform with librosa.
        </div>
        <div className="feat-grid">
          <Feat label="Tempo" value={num(a.bpm, 1, " BPM")} />
          <Feat
            label="Key"
            value={
              a.musical_key
                ? `${a.musical_key} ${a.mode ?? ""}`.trim()
                : "—"
            }
          />
          <Feat label="Key confidence" value={pct(a.key_confidence)} />
          <Feat
            label="Duration"
            value={a.duration_sec ? `${mins}:${String(secs).padStart(2, "0")}` : "—"}
          />
          <Feat label="Beat strength" value={num(a.beat_strength)} />
          <Feat label="Brightness" value={num(a.spectral_centroid, 0, " Hz")} />
          <Feat label="Bandwidth" value={num(a.spectral_bandwidth, 0, " Hz")} />
          <Feat label="Rolloff" value={num(a.spectral_rolloff, 0, " Hz")} />
          <Feat label="Flatness" value={num(a.spectral_flatness, 4)} />
          <Feat label="Zero crossings" value={num(a.zero_crossing_rate, 4)} />
          <Feat label="RMS level" value={num(a.rms_mean, 4)} />
          <Feat label="Dynamic range" value={num(a.dynamic_range, 2, " dB")} />
        </div>
      </div>

      <div className="feat-group">
        <div className="feat-label">Estimated</div>
        <div className="feat-note">
          Heuristic proxies derived from the measured values above. Useful for
          comparison between tracks in this corpus; not equivalent to a
          platform-provided figure, and not interchangeable with one.
        </div>
        <div className="feat-grid">
          <Feat label="Energy" value={pct(a.energy)} estimated />
          <Feat label="Valence" value={pct(a.valence)} estimated />
          <Feat label="Danceability" value={pct(a.danceability)} estimated />
          <Feat label="Acousticness" value={pct(a.acousticness)} estimated />
        </div>
      </div>
    </section>
  );
}
