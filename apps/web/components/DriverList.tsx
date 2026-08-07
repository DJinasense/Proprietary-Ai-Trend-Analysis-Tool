"use client";

import type { Driver } from "@/lib/types";

function ago(iso: string) {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 48) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

export default function DriverList({ drivers }: { drivers: Driver[] }) {
  return (
    <section className="card">
      <h2>Primary Drivers</h2>

      {drivers.length === 0 ? (
        <p className="empty">
          No external driver was detected for this track. That is a finding,
          not a gap — the movement in the acoustic corpus is not currently
          traceable to a social event MUSE can see. Running the ingestion
          worker for longer, or adding connector credentials in{" "}
          <code>.env</code>, widens what it can see.
        </p>
      ) : (
        <>
          {/* Every driver links back to the exact post it came from. A claim
              you cannot click through to is a claim you cannot check. */}
          {drivers.map((d, i) => (
            <div className="driver" key={`${d.platform}-${d.entity}-${i}`}>
              <div className="driver-platform">{d.platform}</div>
              <div className="driver-body">
                <div className="event">{d.originating_event}</div>
                <div className="sub">
                  {d.velocity_surge !== 0 && (
                    <span className="surge">
                      {d.velocity_surge > 0 ? "+" : ""}
                      {d.velocity_surge.toFixed(0)}% vs. its own 21-day median
                    </span>
                  )}
                  <span>{d.engagement.toLocaleString()} engagements</span>
                  <span>{ago(d.observed_at)}</span>
                  {d.match_basis && d.match_basis !== "unspecified" && (
                    <span title={(d.matched_terms ?? []).join(", ")}>
                      matched on {d.match_basis}
                    </span>
                  )}
                  <a
                    href={d.context_anchor_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    view source ↗
                  </a>
                </div>
              </div>
            </div>
          ))}
        </>
      )}
    </section>
  );
}
