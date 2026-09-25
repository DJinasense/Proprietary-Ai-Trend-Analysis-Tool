"use client";

import { useCallback, useEffect, useState } from "react";
import AcousticPanel from "@/components/AcousticPanel";
import DriverList from "@/components/DriverList";
import NarrativePanel from "@/components/NarrativePanel";
import SaturationGauge from "@/components/SaturationGauge";
import StatusBar from "@/components/StatusBar";
import StripeCheckoutModal from "@/components/StripeCheckoutModal";
import ThreeBackground from "@/components/ThreeBackground";
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
  const [showStripeModal, setShowStripeModal] = useState(false);

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

  // Auto-retry background ping if API is cold-starting or asleep
  useEffect(() => {
    if (health) return;
    const interval = setInterval(() => {
      refresh().then((t) => {
        if (t.length > 0) setSelected((s) => s ?? t[0].track_id);
      });
    }, 5000);
    return () => clearInterval(interval);
  }, [health, refresh]);

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
    <>
      <ThreeBackground />

      <main className="shell">
        {/* Top Header Navigation with True Header Image */}
        <header className="topbar" style={{ marginBottom: "16px" }}>
          <div style={{ flex: "1 1 300px", maxWidth: "480px" }}>
            <img
              src="/logo.jpg"
              alt="MUSE - Music Utility & Structural Intelligence Engine"
              style={{
                width: "100%",
                height: "auto",
                maxHeight: "90px",
                objectFit: "contain",
                borderRadius: "12px",
                boxShadow: "0 0 24px rgba(0, 245, 212, 0.4)",
                border: "1px solid rgba(0, 245, 212, 0.3)",
                display: "block",
              }}
            />
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
            <StatusBar health={health} />
            <button
              className="btn"
              onClick={() => setShowStripeModal(true)}
              style={{
                marginTop: 0,
                width: "auto",
                padding: "10px 18px",
                fontSize: "13px",
                background: "linear-gradient(135deg, #00f5d4 0%, #3b82f6 100%)",
                boxShadow: "0 0 20px rgba(0, 245, 212, 0.35)",
                color: "#04120f",
                fontWeight: 800,
                borderRadius: "8px",
              }}
            >
              ★ Upgrade to Pro ($13.99/mo)
            </button>
          </div>
        </header>

        {/* Tagline Banner */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "16px",
            flexWrap: "wrap",
            margin: "0 0 24px",
            padding: "14px 20px",
            background: "rgba(16, 18, 26, 0.75)",
            backdropFilter: "blur(12px)",
            borderRadius: "12px",
            border: "1px solid rgba(0, 245, 212, 0.2)",
          }}
        >
          <p style={{ margin: 0, fontSize: "14px", color: "var(--muted)", maxWidth: "68ch" }}>
            Not another chart. MUSE tells you <em style={{ color: "var(--pulse)", fontStyle: "normal" }}>why</em> a sound is moving, in a
            sentence, and warns you when the lane is closing.
          </p>

          <div
            style={{
              fontSize: "11px",
              fontFamily: "var(--mono)",
              background: "rgba(0, 245, 212, 0.08)",
              border: "1px solid rgba(0, 245, 212, 0.3)",
              color: "var(--pulse)",
              padding: "5px 12px",
              borderRadius: "6px",
              whiteSpace: "nowrap",
              fontWeight: 600,
            }}
          >
            FREE PLAN: 15–30s Sample Hooks
          </div>
        </div>

        {loadError && (
          <div className="error">
            {loadError} — unable to connect to the MUSE API. Please verify backend status.
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
              <section className="card" style={{ backdropFilter: "blur(12px)", background: "rgba(16, 18, 26, 0.85)" }}>
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
              <section className="card" style={{ backdropFilter: "blur(12px)", background: "rgba(16, 18, 26, 0.85)" }}>
                <h2>Narrative Synthesis</h2>
                <p className="empty">
                  Upload a 15–30s sample hook of a track you own to see its narrative. MUSE analyses the
                  audio locally, fingerprints it, compares it against the corpus,
                  and cross-references live social signals to explain what is
                  driving movement around that sound.
                </p>
              </section>
            ) : (
              <>
                <section className="card" style={{ paddingBottom: 14, backdropFilter: "blur(12px)", background: "rgba(16, 18, 26, 0.85)" }}>
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

      <StripeCheckoutModal
        isOpen={showStripeModal}
        onClose={() => setShowStripeModal(false)}
      />
    </>
  );
}
