"use client";

import type { Fatigue } from "@/lib/types";

const VERDICT_COPY: Record<string, { label: string; color: string }> = {
  saturated: { label: "Saturated", color: "var(--burn)" },
  warming: { label: "Warming", color: "var(--amber)" },
  open: { label: "Open lane", color: "var(--pulse)" },
  low_confidence: { label: "Low confidence", color: "var(--muted)" },
  insufficient_data: { label: "Insufficient data", color: "var(--muted)" },
};

function pct(n: number) {
  return `${Math.round(n * 100)}%`;
}

function slope(n: number) {
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}`;
}

export default function SaturationGauge({ fatigue }: { fatigue: Fatigue }) {
  const v = VERDICT_COPY[fatigue.verdict] ?? VERDICT_COPY.low_confidence;

  return (
    <section className="card">
      <h2>Saturation Matrix</h2>

      <div className="gauge-row">
        <div className="gauge-num" style={{ color: v.color }}>
          {pct(fatigue.fatigue_index)}
        </div>

        <div className="gauge-meta">
          <div className="verdict" style={{ color: v.color }}>
            {v.label}
          </div>
          <div className="track-bar" role="img"
               aria-label={`Fatigue index ${pct(fatigue.fatigue_index)}, ${v.label}`}>
            <i
              style={{
                width: `${Math.max(2, fatigue.fatigue_index * 100)}%`,
                background: v.color,
              }}
            />
          </div>
          <div className="explain">{fatigue.explanation}</div>
        </div>
      </div>

      {/* Confidence is shown as its own bar rather than folded into the score.
          A 70% reading backed by 14 tracks and one backed by 400 are different
          claims, and collapsing them into one number is exactly the opacity
          this tool exists to avoid. */}
      <div style={{ marginTop: 20 }}>
        <div className="feat-label">Confidence in this reading</div>
        <div className="track-bar">
          <i
            style={{
              width: `${Math.max(2, fatigue.confidence * 100)}%`,
              background: "var(--muted)",
            }}
          />
        </div>
        <div className="explain">
          {pct(fatigue.confidence)} — derived from corpus coverage (
          {fatigue.neighbor_count} comparable track
          {fatigue.neighbor_count === 1 ? "" : "s"}) and how much engagement
          history those neighbours carry.
        </div>
      </div>

      <div className="stat-grid">
        <div className="stat">
          <b>{fatigue.neighbor_count}</b>
          <span>Sonic neighbours</span>
        </div>
        <div className="stat">
          <b>{fatigue.density_recent.toFixed(2)}</b>
          <span>Recent density</span>
        </div>
        <div className="stat">
          <b>{slope(fatigue.density_slope)}</b>
          <span>Supply trend</span>
        </div>
        <div className="stat">
          <b>{slope(fatigue.engagement_slope)}</b>
          <span>Response trend</span>
        </div>
      </div>
    </section>
  );
}
