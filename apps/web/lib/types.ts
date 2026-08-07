// Mirrors services/api/muse/schemas.py.

export interface Health {
  status: string;
  version: string;
  database: string;
  embedding_backend: string;
  narrative_mode: "llm" | "deterministic";
  connectors: {
    name: string;
    platform: string;
    enabled: boolean;
    /** Why a connector is off — shown on hover rather than left unexplained. */
    detail?: string;
  }[];
}

export interface UploadResponse {
  job_id: string;
  track_id: string;
  status: string;
  message: string;
  /** Set when these exact bytes were already in the corpus; job_id is the original analysis. */
  duplicate?: boolean;
}

export interface JobStatus {
  job_id: string;
  track_id: string | null;
  status: "queued" | "running" | "complete" | "failed";
  stage: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface AcousticSummary {
  bpm: number | null;
  musical_key: string | null;
  mode: string | null;
  key_confidence: number | null;
  duration_sec: number | null;
  spectral_centroid: number | null;
  spectral_bandwidth: number | null;
  spectral_rolloff: number | null;
  spectral_flatness: number | null;
  zero_crossing_rate: number | null;
  rms_mean: number | null;
  dynamic_range: number | null;
  beat_strength: number | null;
  energy: number | null;
  valence: number | null;
  danceability: number | null;
  acousticness: number | null;
}

export interface Driver {
  platform: string;
  entity: string;
  entity_type: string | null;
  originating_event: string;
  velocity_surge: number;
  engagement: number;
  context_anchor_url: string;
  observed_at: string;
  relevance: number;
  /** Why this signal was accepted as a driver, e.g. "3 distinct terms". */
  match_basis?: string;
  matched_terms?: string[];
}

export interface Fatigue {
  fatigue_index: number;
  confidence: number;
  verdict: "saturated" | "warming" | "open" | "low_confidence" | "insufficient_data";
  explanation: string;
  neighbor_count: number;
  density_recent: number;
  density_slope: number;
  engagement_slope: number;
  components: Record<string, unknown>;
}

export interface Narrative {
  headline: string;
  narrative: string;
  actionable_insight: string;
  generation_mode: string;
  model: string | null;
  generated_at: string | null;
}

export interface Insight {
  track_id: string;
  title: string;
  genre: string | null;
  acoustic: AcousticSummary | null;
  fatigue: Fatigue | null;
  drivers: Driver[];
  narrative: Narrative | null;
  embedding_backend: string | null;
}

export interface TrackSummary {
  track_id: string;
  title: string;
  genre: string | null;
  duration_sec: number | null;
  created_at: string;
  fatigue_index: number | null;
  fatigue_confidence: number | null;
  headline: string | null;
}

export interface CorpusStats {
  tracks: number;
  tracks_with_embeddings: number;
  social_signals: number;
  signals_last_24h: number;
  platforms: { platform: string; signals: number; latest: string | null }[];
  fatigue_ready: boolean;
  fatigue_ready_message: string;
}
