"use client";

import type { TrackSummary } from "@/lib/types";

export default function TrackRail({
  tracks,
  selected,
  onSelect,
}: {
  tracks: TrackSummary[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <section className="card">
      <h2>Corpus</h2>
      {tracks.length === 0 ? (
        <p className="empty">
          Nothing analyzed yet. The Fatigue Index compares a track against
          everything else in this corpus, so the first few readings will be
          low-confidence by construction.
        </p>
      ) : (
        tracks.map((t) => (
          <button
            key={t.track_id}
            className={
              t.track_id === selected ? "rail-item active" : "rail-item"
            }
            onClick={() => onSelect(t.track_id)}
          >
            <div className="t">{t.title}</div>
            <div className="m">
              <span>{t.genre || "—"}</span>
              <span>
                {t.fatigue_index === null
                  ? "no reading"
                  : `${Math.round(t.fatigue_index * 100)}% sat.`}
              </span>
            </div>
          </button>
        ))
      )}
    </section>
  );
}
