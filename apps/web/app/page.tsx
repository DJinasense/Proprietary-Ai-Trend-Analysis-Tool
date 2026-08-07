"use client";

import { useCallback, useEffect, useState } from "react";
import AcousticPanel from "@/components/AcousticPanel";
import DriverList from "@/components/DriverList";
import NarrativePanel from "@/components/NarrativePanel";
import SaturationGauge from "@/components/SaturationGauge";
import StatusBar from "@/components/StatusBar";
import TrackRail from "@/components/TrackRail";
import UploadPanel from "@/components/UploadPanel";
import { getCorpus, getHealth, getInsight, getTracks } from "@/lib/api";
import type { CorpusStats, Health, Insight, TrackSummary } from "@/lib/types";

export default function Page() {
  const [health, setHealth] = useState<Health | null>(null);
  const [corpus, setCorpus] = useState<CorpusStats | null>(null);
  const [tracks, setTracks] = useState<TrackSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [insight, setInsight] = useState<Insight | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [h, c, t] = await Promise.all([
        getHealth(),
        getCorpus(),
        getTracks(),
      ]);
      setHealth(h);
      setCorpus(c);
      setTracks(t);
      setLoadError(null);
      return t;
    } catch (err) {
      setHealth(null);
      setLoadError(
        err instanceof Error ? err.message : "Could not reach the MUSE API."
      );
      return [];
    }
  }, []);

  useEffect(() => {
    refresh().then((t) => {
      if (t.length > 0) setSelected((s) => s ?? t[0].track_id);
    });
  }, [refresh]);

  useEffect(() => {
    if (!selected) {
      setInsight(null);
      return;
    }
    let cancelled = false;
    getInsight(selected)
      .then((i) => {
        if (!cancelled) setInsight(i);
      })
      .catch(() => {
        if (!cancelled) setInsight(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const onAnalyzed = useCallback(
    async (trackId: string) => {
      await refresh();
      setSelected(trackId);
    },
    [refresh]
  );

  return (
    <main className="shell">
      <header className="topbar">
        <div className="wordmark">
          <h1>MUSE</h1>
          <span>Music Utility &amp; Structural Intelligence Engine</span>
        </div>
        <StatusBar health={health} />
      </header>

      <p className="tagline">
        Not another chart. MUSE tells you <em>why</em> a sound is moving, in a
        sentence, and warns you when the lane is closing.
      </p>

      {loadError && (
        <div className="error">
          {loadError} — is the API running? Start it with{" "}
          <code>docker compose up</code> from the project root.
        </div>
      )}

      {corpus && !corpus.fatigue_ready && (
        <div className="banner">{corpus.fatigue_ready_message}</div>
      )}

      <div className="grid">
        <div>
          <UploadPanel onComplete={onAnalyzed} />
          <TrackRail
            tracks={tracks}
            selected={selected}
            onSelect={setSelected}
          />
          {corpus && (
            <section className="card">
              <h2>Signal Coverage</h2>
              <div className="stat-grid">
                <div className="stat">
                  <b>{corpus.tracks_with_embeddings}</b>
                  <span>Fingerprinted</span>
                </div>
                <div className="stat">
                  <b>{corpus.social_signals.toLocaleString()}</b>
                  <span>Social signals</span>
                </div>
                <div className="stat">
                  <b>{corpus.signals_last_24h.toLocaleString()}</b>
                  <span>Last 24h</span>
                </div>
              </div>
              {corpus.platforms.length > 0 && (
                <div className="pills" style={{ marginTop: 14 }}>
                  {corpus.platforms.map((p) => (
                    <span className="pill" key={p.platform}>
                      {p.platform} · {p.signals}
                    </span>
                  ))}
                </div>
              )}
            </section>
          )}
        </div>

        <div>
          {!insight ? (
            <section className="card">
              <h2>Narrative Synthesis</h2>
              <p className="empty">
                Upload a track you own to see its narrative. MUSE analyses the
                audio locally, fingerprints it, compares it against the corpus,
                and cross-references live social signals to explain what is
                driving movement around that sound.
              </p>
            </section>
          ) : (
            <>
              <section className="card" style={{ paddingBottom: 14 }}>
                <h2>Now analysing</h2>
                <div style={{ fontSize: 20, fontWeight: 650 }}>
                  {insight.title}
                </div>
                <div
                  style={{
                    color: "var(--muted)",
                    fontSize: 13,
                    marginTop: 4,
                  }}
                >
                  {insight.genre || "no genre set"} ·{" "}
                  {insight.embedding_backend
                    ? `${insight.embedding_backend} fingerprint`
                    : "not fingerprinted"}
                </div>
              </section>

              {insight.narrative && (
                <NarrativePanel narrative={insight.narrative} />
              )}
              {insight.fatigue && <SaturationGauge fatigue={insight.fatigue} />}
              <DriverList drivers={insight.drivers} />
              {insight.acoustic && <AcousticPanel a={insight.acoustic} />}
            </>
          )}
        </div>
      </div>
    </main>
  );
}
