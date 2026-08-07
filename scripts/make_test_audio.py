"""Generate synthetic test tracks with known tempo and key.

Pure stdlib, so it runs on any Python 3 with nothing installed. Each track gets
a kick on the beat (so beat tracking has something to lock onto) and a
sustained triad (so chroma-based key detection has a real answer to find),
which makes the output verifiable rather than merely non-empty.

    python scripts/make_test_audio.py ./testdata
"""

import math
import pathlib
import struct
import sys
import wave

SR = 44100

NOTE = {
    "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
    "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11,
}


def freq(name: str, octave: int = 3) -> float:
    midi = 12 * (octave + 1) + NOTE[name]
    return 440.0 * (2 ** ((midi - 69) / 12.0))


def render(path: pathlib.Path, bpm: float, root: str, minor: bool,
           seconds: float = 30.0) -> None:
    n = int(SR * seconds)
    beat_len = 60.0 / bpm
    third = 3 if minor else 4
    chord = [
        freq(root, 3),
        freq(root, 3) * 2 ** (third / 12),
        freq(root, 3) * 2 ** (7 / 12),
        freq(root, 4),
    ]

    frames = []
    for i in range(n):
        t = i / SR
        pos = (t % beat_len) / beat_len

        kick = (math.sin(2 * math.pi * (150.0 * math.exp(-pos * 9.0)) * t)
                * math.exp(-pos * 26.0) * 0.55)

        eighth = (t % (beat_len / 2)) / (beat_len / 2)
        hat = ((i * 2654435761) % 1000 / 500.0 - 1.0) * math.exp(-eighth * 60.0) * 0.06

        pad = sum(math.sin(2 * math.pi * f * t) for f in chord)
        pad *= 0.075 * (0.85 + 0.15 * math.sin(2 * math.pi * 0.4 * t))

        fade = min(1.0, t / 0.4, (seconds - t) / 0.4)
        s = max(-1.0, min(1.0, (kick + hat + pad) * fade))
        frames.append(struct.pack("<h", int(s * 32000)))

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(frames))

    print(f"{path}  {bpm:g} BPM  {root}{'m' if minor else ''}  {seconds:g}s")


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "testdata")
    out.mkdir(parents=True, exist_ok=True)
    render(out / "test_120_Am.wav", 120.0, "A", True)
    render(out / "test_124_Am.wav", 124.0, "A", True)
    render(out / "test_92_F.wav", 92.0, "F", False)
