"""Acoustic feature extraction from real audio.

Two things worth being explicit about, because the difference matters when
someone acts on these numbers:

* **Measured** — bpm, key, spectral statistics, RMS, dynamic range, ZCR.
  These are signal-processing outputs. They are what they say they are.

* **Proxied** — valence, danceability, acousticness, energy. There is no
  ground truth for "how happy is this track" in a waveform. These are
  documented heuristics over measured features, calibrated to land in a
  Spotify-comparable 0..1 range so existing intuitions transfer. They are
  labelled as proxies everywhere they surface, including the API response.

The spec assumed these would arrive from Spotify's ``audio-features``
endpoint. That endpoint was deprecated for new applications in November 2024,
so MUSE computes them from the audio itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any

import librosa
import numpy as np

from muse.config import settings

logger = logging.getLogger(__name__)

PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl-Schmuckler key profiles — the standard published weights for
# major and minor tonal hierarchies.
KS_MAJOR = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
KS_MINOR = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)


@dataclass
class AcousticProfile:
    """Full descriptor block for one track."""

    duration_sec: float
    bpm: float
    beat_strength: float
    musical_key: str
    mode: str
    key_confidence: float
    energy: float
    valence: float
    danceability: float
    acousticness: float
    spectral_centroid: float
    spectral_bandwidth: float
    spectral_rolloff: float
    spectral_flatness: float
    zero_crossing_rate: float
    rms_mean: float
    dynamic_range: float
    # Vector blocks retained for the embedding stage and for explainability.
    mfcc_mean: list[float] = field(default_factory=list)
    mfcc_std: list[float] = field(default_factory=list)
    chroma_mean: list[float] = field(default_factory=list)
    contrast_mean: list[float] = field(default_factory=list)
    tonnetz_mean: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def scalar_summary(self) -> dict[str, Any]:
        """Just the scalars — what the UI and the narrative prompt consume."""
        d = self.to_dict()
        for k in ("mfcc_mean", "mfcc_std", "chroma_mean", "contrast_mean", "tonnetz_mean"):
            d.pop(k, None)
        return d


def _safe_float(value: Any, default: float = 0.0) -> float:
    """numpy scalars, NaN and inf all reach JSON serialization otherwise."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(f):
        return default
    return f


def _minmax(value: float, lo: float, hi: float) -> float:
    """Clamp `value` into 0..1 given an expected operating range."""
    if hi <= lo:
        return 0.0
    return float(np.clip((value - lo) / (hi - lo), 0.0, 1.0))


def detect_key(chroma: np.ndarray) -> tuple[str, str, float]:
    """Krumhansl-Schmuckler key detection.

    Correlates the track's average chroma vector against all 24 rotated
    major/minor profiles. Returns (key, mode, confidence) where confidence is
    the margin between the best and second-best correlation — a flat margin
    means the track is tonally ambiguous and the key should not be trusted.
    """
    profile = chroma.mean(axis=1)
    if profile.sum() <= 0:
        return "unknown", "unknown", 0.0
    profile = profile / profile.sum()

    scores: list[tuple[float, str, str]] = []
    for i in range(12):
        rotated = np.roll(profile, -i)
        maj = float(np.corrcoef(rotated, KS_MAJOR)[0, 1])
        minr = float(np.corrcoef(rotated, KS_MINOR)[0, 1])
        if np.isfinite(maj):
            scores.append((maj, PITCH_CLASSES[i], "major"))
        if np.isfinite(minr):
            scores.append((minr, PITCH_CLASSES[i], "minor"))

    if not scores:
        return "unknown", "unknown", 0.0

    scores.sort(key=lambda s: s[0], reverse=True)
    best = scores[0]
    runner_up = scores[1][0] if len(scores) > 1 else 0.0
    # Margin scaled so a clear tonal centre lands near 1.0.
    confidence = float(np.clip((best[0] - runner_up) * 4.0, 0.0, 1.0))
    return best[1], best[2], round(confidence, 3)


def analyze_audio(path: str) -> AcousticProfile:
    """Extract a full acoustic profile from an audio file on disk."""
    logger.info("Loading audio: %s", path)

    y, sr = librosa.load(
        path,
        sr=settings.analysis_sample_rate,
        mono=True,
        duration=settings.analysis_max_seconds,
    )

    if y.size == 0:
        raise ValueError("Decoded audio is empty — file may be corrupt or unsupported.")

    duration = float(librosa.get_duration(y=y, sr=sr))

    # Separating harmonic from percussive content up front; several
    # descriptors below are far more stable on one component than on the mix.
    y_harmonic, y_percussive = librosa.effects.hpss(y)

    # ── Rhythm ────────────────────────────────────────────────────────────
    onset_env = librosa.onset.onset_strength(y=y_percussive, sr=sr)
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
    bpm = _safe_float(np.atleast_1d(tempo)[0], 0.0)

    # Beat strength: how pronounced the onsets are relative to the noise floor.
    if onset_env.size > 1 and onset_env.mean() > 0:
        beat_strength = _safe_float(onset_env.max() / (onset_env.mean() + 1e-9))
    else:
        beat_strength = 0.0

    # Pulse regularity — a steady grid scores high, rubato/freetime scores low.
    if len(beats) > 2:
        beat_times = librosa.frames_to_time(beats, sr=sr)
        intervals = np.diff(beat_times)
        regularity = 1.0 - _safe_float(
            np.std(intervals) / (np.mean(intervals) + 1e-9)
        )
        regularity = float(np.clip(regularity, 0.0, 1.0))
    else:
        regularity = 0.0

    # ── Spectral ──────────────────────────────────────────────────────────
    centroid = _safe_float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
    bandwidth = _safe_float(np.mean(librosa.feature.spectral_bandwidth(y=y, sr=sr)))
    rolloff = _safe_float(np.mean(librosa.feature.spectral_rolloff(y=y, sr=sr)))
    flatness = _safe_float(np.mean(librosa.feature.spectral_flatness(y=y)))
    zcr = _safe_float(np.mean(librosa.feature.zero_crossing_rate(y=y)))

    contrast = librosa.feature.spectral_contrast(y=y, sr=sr)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=40)
    chroma = librosa.feature.chroma_cqt(y=y_harmonic, sr=sr)
    tonnetz = librosa.feature.tonnetz(y=y_harmonic, sr=sr)

    # ── Loudness ──────────────────────────────────────────────────────────
    rms = librosa.feature.rms(y=y)[0]
    rms_mean = _safe_float(np.mean(rms))
    rms_db = librosa.amplitude_to_db(rms + 1e-9)
    # 5th-to-95th percentile spread in dB: resistant to a single loud transient
    # in a way that peak-minus-floor is not.
    dynamic_range = _safe_float(
        np.percentile(rms_db, 95) - np.percentile(rms_db, 5)
    )

    # ── Tonality ──────────────────────────────────────────────────────────
    key, mode, key_conf = detect_key(chroma)

    # ── Derived proxies (heuristic — see module docstring) ────────────────

    # Energy: perceived intensity. Loudness plus high-frequency content plus
    # rhythmic drive.
    energy = float(
        np.clip(
            0.45 * _minmax(rms_mean, 0.01, 0.25)
            + 0.30 * _minmax(centroid, 800.0, 4500.0)
            + 0.25 * _minmax(beat_strength, 1.5, 6.0),
            0.0,
            1.0,
        )
    )

    # Valence: musical positivity. Mode is the dominant term (major reads
    # brighter), modulated by brightness and tempo, and pulled down by a
    # heavily compressed mix which tends to read as aggressive rather than
    # happy.
    mode_term = 0.68 if mode == "major" else 0.32
    # Weight the mode term by how confident the key detection actually was —
    # an ambiguous key shouldn't swing valence.
    mode_term = 0.5 + (mode_term - 0.5) * max(key_conf, 0.15) / 0.15 * 0.5
    mode_term = float(np.clip(mode_term, 0.0, 1.0))
    valence = float(
        np.clip(
            0.40 * mode_term
            + 0.25 * _minmax(centroid, 700.0, 3800.0)
            + 0.20 * _minmax(bpm, 70.0, 150.0)
            + 0.15 * _minmax(dynamic_range, 4.0, 22.0),
            0.0,
            1.0,
        )
    )

    # Danceability: steady pulse in a danceable tempo band with real low-end.
    # Tempo term is a triangular window peaking around 120 BPM.
    tempo_fit = float(np.clip(1.0 - abs(bpm - 120.0) / 60.0, 0.0, 1.0)) if bpm else 0.0
    low_energy_ratio = _safe_float(
        np.sum(np.abs(y_percussive)) / (np.sum(np.abs(y)) + 1e-9)
    )
    danceability = float(
        np.clip(
            0.40 * regularity
            + 0.35 * tempo_fit
            + 0.25 * _minmax(low_energy_ratio, 0.15, 0.60),
            0.0,
            1.0,
        )
    )

    # Acousticness: harmonic-dominant, spectrally peaky (not noise-like),
    # wide dynamics. Electronic production inverts all three.
    harmonic_ratio = _safe_float(
        np.sum(np.abs(y_harmonic)) / (np.sum(np.abs(y)) + 1e-9)
    )
    acousticness = float(
        np.clip(
            0.45 * harmonic_ratio
            + 0.30 * (1.0 - _minmax(flatness, 0.001, 0.35))
            + 0.25 * _minmax(dynamic_range, 6.0, 26.0),
            0.0,
            1.0,
        )
    )

    profile = AcousticProfile(
        duration_sec=round(duration, 2),
        bpm=round(bpm, 2),
        beat_strength=round(beat_strength, 4),
        musical_key=key,
        mode=mode,
        key_confidence=key_conf,
        energy=round(energy, 4),
        valence=round(valence, 4),
        danceability=round(danceability, 4),
        acousticness=round(acousticness, 4),
        spectral_centroid=round(centroid, 2),
        spectral_bandwidth=round(bandwidth, 2),
        spectral_rolloff=round(rolloff, 2),
        spectral_flatness=round(flatness, 6),
        zero_crossing_rate=round(zcr, 6),
        rms_mean=round(rms_mean, 6),
        dynamic_range=round(dynamic_range, 3),
        mfcc_mean=[round(_safe_float(v), 5) for v in mfcc.mean(axis=1)],
        mfcc_std=[round(_safe_float(v), 5) for v in mfcc.std(axis=1)],
        chroma_mean=[round(_safe_float(v), 5) for v in chroma.mean(axis=1)],
        contrast_mean=[round(_safe_float(v), 5) for v in contrast.mean(axis=1)],
        tonnetz_mean=[round(_safe_float(v), 5) for v in tonnetz.mean(axis=1)],
    )

    logger.info(
        "Analyzed %s — %.1f BPM, %s %s (conf %.2f), energy %.2f",
        path, profile.bpm, profile.musical_key, profile.mode,
        profile.key_confidence, profile.energy,
    )
    return profile
