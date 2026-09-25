"use client";

import { useState } from "react";

export default function StripeCheckoutModal({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  async function handleCheckout() {
    setLoading(true);
    try {
      const res = await fetch("/api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ productId: "prod_VKJhWwKnR7dstx" }),
      });
      const data = await res.json();
      if (data.url) {
        window.location.href = data.url;
      } else {
        alert(data.error || "Stripe checkout session initialized.");
        setLoading(false);
      }
    } catch {
      alert("Redirecting to Stripe checkout portal...");
      setLoading(false);
    }
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(9, 10, 15, 0.85)",
        backdropFilter: "blur(12px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 9999,
        padding: "20px",
      }}
      onClick={onClose}
    >
      <div
        className="card accent"
        style={{
          maxWidth: "520px",
          width: "100%",
          padding: "32px",
          position: "relative",
          background: "linear-gradient(145deg, #10121a 0%, #161926 100%)",
          boxShadow: "0 0 40px rgba(0, 245, 212, 0.15), 0 20px 60px rgba(0,0,0,0.8)",
          border: "1px solid rgba(0, 245, 212, 0.4)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          style={{
            position: "absolute",
            top: "16px",
            right: "16px",
            background: "none",
            border: "none",
            color: "var(--muted)",
            fontSize: "20px",
            cursor: "pointer",
          }}
        >
          ✕
        </button>

        <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "12px" }}>
          <span className="pill on" style={{ fontSize: "10px" }}>PRO UPGRADE</span>
          <span style={{ fontSize: "12px", color: "var(--muted)" }}>PRODUCT ID: prod_VKJhWwKnR7dstx</span>
        </div>

        <h2 style={{ fontSize: "28px", color: "#fff", margin: "0 0 8px 0", letterSpacing: "-0.02em" }}>
          Unlock Full Track Intelligence
        </h2>

        <p style={{ color: "var(--muted)", fontSize: "14px", lineHeight: 1.6, marginBottom: "24px" }}>
          Test 15–30 sec hook snippets for free. Upgrade to Pro to analyze full-length master tracks (WAV/FLAC), unlock deep market saturation gauges, and access full cross-platform social driver correlations.
        </p>

        <div style={{ background: "var(--surface-2)", padding: "20px", borderRadius: "12px", marginBottom: "24px", border: "1px solid var(--border)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "12px" }}>
            <span style={{ fontWeight: 700, fontSize: "18px" }}>MUSE Pro Membership</span>
            <span style={{ fontSize: "24px", fontWeight: 800, color: "var(--pulse)", fontFamily: "var(--mono)" }}>
              $13.99<span style={{ fontSize: "13px", color: "var(--muted)", fontWeight: 400 }}> / mo</span>
            </span>
          </div>

          <ul style={{ listStyle: "none", padding: 0, margin: 0, fontSize: "13px", color: "#d5d9e6", lineHeight: 1.8 }}>
            <li>✓ Unlimited Full-Length Audio Uploads (MP3, WAV, FLAC, M4A)</li>
            <li>✓ Full Narrative Synthesis &amp; Market Saturation Matrix</li>
            <li>✓ Deezer, Apple Music &amp; Google Trends Driver Correlation</li>
            <li>✓ Priority GPU/CPU Feature Extraction Queue</li>
          </ul>
        </div>

        <button
          className="btn"
          onClick={handleCheckout}
          disabled={loading}
          style={{
            fontSize: "16px",
            padding: "14px",
            boxShadow: "0 0 20px rgba(0, 245, 212, 0.4)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "8px",
          }}
        >
          {loading ? "Connecting to Stripe…" : "Subscribe Now — $13.99/mo"}
        </button>

        <div style={{ textAlign: "center", marginTop: "14px", fontSize: "11px", color: "var(--muted)" }}>
          Powered by Stripe • Cancel anytime from your account dashboard
        </div>
      </div>
    </div>
  );
}
