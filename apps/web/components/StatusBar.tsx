"use client";

import type { Health } from "@/lib/types";

export default function StatusBar({ health }: { health: Health | null }) {
  if (!health) {
    return (
      <div className="pills">
        <span className="pill warn">
          <i className="dot" /> API unreachable
        </span>
      </div>
    );
  }

  const active = health.connectors.filter((c) => c.enabled);

  return (
    <div className="pills">
      <span className={health.database === "ok" ? "pill on" : "pill warn"}>
        <i className="dot" /> db {health.database}
      </span>
      <span className={health.narrative_mode === "llm" ? "pill on" : "pill"}>
        <i className="dot" /> narrative: {health.narrative_mode}
      </span>
      <span className="pill">
        <i className="dot" /> embed: {health.embedding_backend}
      </span>
      {health.connectors.map((c) => (
        <span
          key={c.name}
          className={c.enabled ? "pill on" : "pill"}
          title={c.detail ?? (c.enabled ? "" : "No credentials configured")}
        >
          <i className="dot" /> {c.name}
        </span>
      ))}
      {active.length === 0 && (
        <span className="pill warn">
          <i className="dot" /> no social sources configured
        </span>
      )}
    </div>
  );
}
