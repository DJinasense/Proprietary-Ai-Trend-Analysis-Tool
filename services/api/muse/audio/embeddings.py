"""Acoustic embedding backends.

The embedding is the substrate the Fatigue Index runs on: "how saturated is
this sound" is answered by asking how crowded this track's neighbourhood in
embedding space has become. So the vector has to actually encode timbre and
harmony. The spec PDF used ``np.random.uniform(-1, 1, 512)``, which encodes
nothing — every track lands at an arbitrary point and neighbourhood density
becomes noise.

Two backends:

* ``stats`` (default) — a deterministic 118-dim descriptor built from the
  librosa feature blocks, block-normalised so no single family dominates the
  distance metric. No model download, sub-second, runs anywhere. Good enough
  to separate genres and production styles.

* ``clap`` (opt-in) — LAION CLAP audio encoder, 512-dim, semantically far
  richer. ~600MB on first run. Set MUSE_EMBEDDING_BACKEND=clap.

Both write into the same ``vector(512)`` column. A backend narrower than 512
zero-pads its tail; because cosine similarity divides by the vector norms and
zeros contribute to neither the dot product nor the norm, padding is
mathematically inert. Mixing backends in one corpus is not — the API records
which backend produced each vector and the Fatigue Index only compares
like with like.
"""

from __future__ import annotations

import logging
from typing import Protocol

import numpy as np

from muse.audio.features import AcousticProfile
from muse.config import settings

logger = logging.getLogger(__name__)


class EmbeddingBackend(Protocol):
    name: str
    native_dim: int

    def embed(self, profile: AcousticProfile, audio_path: str) -> np.ndarray: ...


def _block(values: list[float], expected: int) -> np.ndarray:
    """Coerce a feature block to fixed length, then L2-normalise it.

    Per-block normalisation is what stops the 40-dim MFCC family from
    swamping the 6-dim tonnetz family purely by having more numbers in it.
    """
    arr = np.asarray(values, dtype=np.float32)
    if arr.size < expected:
        arr = np.pad(arr, (0, expected - arr.size))
    elif arr.size > expected:
        arr = arr[:expected]
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    norm = np.linalg.norm(arr)
    return arr / norm if norm > 0 else arr


class StatsBackend:
    """Deterministic spectral/harmonic descriptor. No model, no download."""

    name = "stats"
    native_dim = 118

    # Relative influence of each family on the final distance metric.
    # Timbre (MFCC) leads because it's what listeners register as "this sounds
    # like X"; harmony and the scalar summary refine it.
    WEIGHTS = {
        "mfcc_mean": 1.00,
        "mfcc_std": 0.60,
        "chroma": 0.70,
        "contrast": 0.70,
        "tonnetz": 0.55,
        "scalars": 0.85,
    }

    def embed(self, profile: AcousticProfile, audio_path: str) -> np.ndarray:
        scalars = [
            np.clip(profile.bpm / 200.0, 0.0, 1.0),
            np.clip(profile.beat_strength / 8.0, 0.0, 1.0),
            profile.energy,
            profile.valence,
            profile.danceability,
            profile.acousticness,
            np.clip(profile.spectral_centroid / 6000.0, 0.0, 1.0),
            np.clip(profile.spectral_bandwidth / 5000.0, 0.0, 1.0),
            np.clip(profile.spectral_rolloff / 10000.0, 0.0, 1.0),
            np.clip(profile.spectral_flatness / 0.5, 0.0, 1.0),
            np.clip(profile.zero_crossing_rate / 0.35, 0.0, 1.0),
            np.clip(profile.rms_mean / 0.3, 0.0, 1.0),
            np.clip(profile.dynamic_range / 40.0, 0.0, 1.0),
        ]

        parts = [
            self.WEIGHTS["mfcc_mean"] * _block(profile.mfcc_mean, 40),
            self.WEIGHTS["mfcc_std"] * _block(profile.mfcc_std, 40),
            self.WEIGHTS["chroma"] * _block(profile.chroma_mean, 12),
            self.WEIGHTS["contrast"] * _block(profile.contrast_mean, 7),
            self.WEIGHTS["tonnetz"] * _block(profile.tonnetz_mean, 6),
            self.WEIGHTS["scalars"] * _block(scalars, 13),
        ]

        vec = np.concatenate(parts).astype(np.float32)
        assert vec.size == self.native_dim, f"expected {self.native_dim}, got {vec.size}"
        return vec


class ClapBackend:
    """LAION CLAP audio encoder. Loaded lazily — importing transformers and
    materialising the weights is expensive and pointless unless selected."""

    name = "clap"
    native_dim = 512
    MODEL_ID = "laion/clap-htsat-unfused"

    def __init__(self) -> None:
        self._model = None
        self._processor = None
        self._device = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        import torch  # noqa: F401  (imported for side effects / availability check)
        from transformers import ClapModel, ClapProcessor

        # from_pretrained defaults to CPU regardless of what's available; a
        # GPU sitting idle while every embed call runs on CPU is not opt-in
        # by anyone's definition.
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(
            "Loading CLAP model %s on %s (first run downloads ~600MB)",
            self.MODEL_ID,
            self._device,
        )
        self._model = ClapModel.from_pretrained(self.MODEL_ID).to(self._device)
        self._processor = ClapProcessor.from_pretrained(self.MODEL_ID)
        self._model.eval()

    def embed(self, profile: AcousticProfile, audio_path: str) -> np.ndarray:
        import librosa
        import torch

        self._ensure_loaded()
        # CLAP is trained at 48kHz; resample rather than feed it our 22050.
        y, _ = librosa.load(audio_path, sr=48000, mono=True, duration=30.0)
        inputs = self._processor(audios=y, sampling_rate=48000, return_tensors="pt")
        inputs = {k: v.to(self._device) for k, v in inputs.items()}
        with torch.no_grad():
            features = self._model.get_audio_features(**inputs)
        return features[0].cpu().numpy().astype(np.float32)


_BACKENDS: dict[str, EmbeddingBackend] = {}


def get_backend(name: str | None = None) -> EmbeddingBackend:
    key = (name or settings.embedding_backend).lower()
    if key not in _BACKENDS:
        if key == "clap":
            _BACKENDS[key] = ClapBackend()
        elif key == "stats":
            _BACKENDS[key] = StatsBackend()
        else:
            raise ValueError(
                f"Unknown embedding backend {key!r}. Use 'stats' or 'clap'."
            )
    return _BACKENDS[key]


def embed_track(profile: AcousticProfile, audio_path: str) -> tuple[list[float], str, int]:
    """Produce a storage-ready 512-dim vector.

    Returns (vector, backend_name, native_dim). The vector is L2-normalised
    before padding so cosine distance and inner product agree.
    """
    backend = get_backend()
    raw = backend.embed(profile, audio_path)
    raw = np.nan_to_num(raw, nan=0.0, posinf=0.0, neginf=0.0)

    norm = float(np.linalg.norm(raw))
    if norm > 0:
        raw = raw / norm

    storage_dim = settings.embedding_storage_dim
    if raw.size > storage_dim:
        raise ValueError(
            f"Backend {backend.name} emits {raw.size} dims, exceeding storage "
            f"width {storage_dim}. Widen the vector column."
        )
    padded = np.zeros(storage_dim, dtype=np.float32)
    padded[: raw.size] = raw

    return padded.tolist(), backend.name, backend.native_dim
