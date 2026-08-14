import type {
  CorpusStats,
  Health,
  Insight,
  JobStatus,
  TrackSummary,
  UploadResponse,
} from "./types";

// `?.replace(...) || default` would treat an explicit "" (same-origin,
// relative /api/... calls, proxied via next.config.mjs rewrites) as unset
// and silently override it — falsy, not just missing. Check presence
// instead of truthiness so "" means what it says.
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE !== undefined
    ? process.env.NEXT_PUBLIC_API_BASE.replace(/\/$/, "")
    : "http://localhost:8000";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    // FastAPI puts the useful message in `detail`; surfacing it beats a bare
    // status code when the failure is something the user can act on.
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const getHealth = () => get<Health>("/api/health");
export const getTracks = () => get<TrackSummary[]>("/api/tracks");
export const getJob = (id: string) => get<JobStatus>(`/api/tracks/jobs/${id}`);
export const getInsight = (id: string) => get<Insight>(`/api/insights/${id}`);
export const getCorpus = () => get<CorpusStats>("/api/trends/corpus");

export async function uploadTrack(form: FormData): Promise<UploadResponse> {
  const res = await fetch(`${API_BASE}/api/tracks`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    let detail = `Upload failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json();
}
