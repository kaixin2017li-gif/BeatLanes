#!/usr/bin/env python3
"""Synthesise the backing track.

The song is generated rather than downloaded. Two reasons: the repository then
contains no third party audio at all, so there is no licence to track and no
link that can go dead, and the generator is itself part of the project's code.

The arrangement follows tools/beatplan.py, which is the same file the chart is
generated from, so the drums and the notes share a grid:

    bars 0-3    intro - kick and hats only
    bars 4-7    bass joins
    bars 8-15   lead arpeggio joins
    bar 15      everything, then a fade

    python tools/make_song.py             # -> assets/beatlanes_120.ogg
    python tools/make_song.py --keep-wav  # also keep the intermediate wav
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from beatlanes import config  # noqa: E402
from tools import beatplan  # noqa: E402

SAMPLE_RATE = 44_100
TAIL_MS = 1_000  # room for the last hits to ring out

# One root note per bar, cycling through the progression.
BASS_HZ = (55.00, 55.00, 43.65, 49.00)  # A1 A1 F1 G1
LEAD_HZ = (440.00, 523.25, 587.33, 659.25, 783.99, 659.25, 587.33, 523.25)


# --- the instruments --------------------------------------------------------
def _decay(length: int, tau_seconds: float) -> np.ndarray:
    return np.exp(-np.arange(length) / (SAMPLE_RATE * tau_seconds))


def kick(duration: float = 0.30) -> np.ndarray:
    """Sine with a fast downward pitch sweep: the usual cheap kick drum."""
    length = int(SAMPLE_RATE * duration)
    t = np.arange(length) / SAMPLE_RATE
    frequency = 48.0 + 120.0 * np.exp(-t / 0.035)
    phase = 2.0 * np.pi * np.cumsum(frequency) / SAMPLE_RATE
    return np.sin(phase) * _decay(length, 0.075)


def hat(duration: float = 0.06, rng: np.random.Generator | None = None) -> np.ndarray:
    """Filtered noise with a very short decay."""
    length = int(SAMPLE_RATE * duration)
    noise = (rng or np.random.default_rng(11)).standard_normal(length)
    return noise * _decay(length, 0.010) * 0.30


def bass(frequency: float, duration: float = 0.42) -> np.ndarray:
    """Sine plus a soft saw, which gives the low end some edge."""
    length = int(SAMPLE_RATE * duration)
    t = np.arange(length) / SAMPLE_RATE
    saw = 2.0 * (t * frequency - np.floor(0.5 + t * frequency))
    tone = 0.60 * np.sin(2.0 * np.pi * frequency * t) + 0.25 * saw
    envelope = np.minimum(1.0, t / 0.006) * _decay(length, 0.16)
    return tone * envelope * 0.55


def lead(frequency: float, duration: float = 0.26) -> np.ndarray:
    """Triangle wave: quiet, sits above the bass."""
    length = int(SAMPLE_RATE * duration)
    t = np.arange(length) / SAMPLE_RATE
    triangle = 2.0 * np.abs(2.0 * (t * frequency - np.floor(0.5 + t * frequency))) - 1.0
    envelope = np.minimum(1.0, t / 0.004) * _decay(length, 0.075)
    return triangle * envelope * 0.16


def place(track: np.ndarray, sound: np.ndarray, at_ms: float, gain: float = 1.0) -> None:
    """Add a sound into the track at a time in milliseconds."""
    start = int(SAMPLE_RATE * at_ms / 1000.0)
    if start >= len(track):
        return
    end = min(len(track), start + len(sound))
    track[start:end] += sound[: end - start] * gain


# --- arrangement ------------------------------------------------------------
def build_track() -> np.ndarray:
    total = int(SAMPLE_RATE * (beatplan.SONG_MS + TAIL_MS) / 1000.0)
    track = np.zeros(total)
    rng = np.random.default_rng(11)

    for bar in range(beatplan.BARS):
        bar_ms = bar * beatplan.BAR_MS
        intro = bar < beatplan.INTRO_BARS

        for beat in range(beatplan.BEATS_PER_BAR):
            at_ms = bar_ms + beat * beatplan.BEAT_MS
            if beat % 2 == 0:
                place(track, kick(), at_ms, 0.95)
            place(track, hat(0.07 if beat % 2 == 0 else 0.05, rng), at_ms, 0.50 if intro else 0.75)
            if beat % 2 == 1:
                # extra hat on the off-beat, which is what gives it a pulse
                place(track, hat(0.04, rng), at_ms + beatplan.BEAT_MS / 2.0, 0.40)

        if not intro:
            root = BASS_HZ[bar % len(BASS_HZ)]
            place(track, bass(root), bar_ms, 0.90)
            place(track, bass(root), bar_ms + 2 * beatplan.BEAT_MS, 0.85)
            place(track, bass(root * 2.0), bar_ms + 3 * beatplan.BEAT_MS, 0.70)

        if bar >= 8:
            for beat in range(beatplan.BEATS_PER_BAR):
                index = (bar * beatplan.BEATS_PER_BAR + beat) % len(LEAD_HZ)
                place(track, lead(LEAD_HZ[index]), bar_ms + beat * beatplan.BEAT_MS, 0.80)

    return track


def finalise(track: np.ndarray) -> np.ndarray:
    """Normalise, then fade in and out so the file does not start or end with a click."""
    peak = float(np.max(np.abs(track))) if track.size else 0.0
    if peak > 0:
        track = track / peak * 0.89
    fade_in = int(SAMPLE_RATE * 0.04)
    fade_out = int(SAMPLE_RATE * 0.90)
    track[:fade_in] *= np.linspace(0.0, 1.0, fade_in)
    track[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)
    return track


# --- output -----------------------------------------------------------------
def write_audio(track: np.ndarray, target: Path, keep_wav: bool) -> None:
    """Encode the track. Vorbis is written directly when the local soundfile
    supports it, otherwise a wav is written and ffmpeg does the encoding."""
    target.parent.mkdir(parents=True, exist_ok=True)
    samples = track.astype(np.float32)

    try:
        sf.write(str(target), samples, SAMPLE_RATE, format="OGG", subtype="VORBIS")
        if keep_wav:
            sf.write(str(target.with_suffix(".wav")), samples, SAMPLE_RATE)
        return
    except Exception as exc:  # libsndfile without vorbis support
        print(f"soundfile could not write OGG ({exc}); falling back to ffmpeg")

    wav_path = target.with_suffix(".wav")
    sf.write(str(wav_path), samples, SAMPLE_RATE)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        print(f"ffmpeg not found: leaving {wav_path} in place, and the game will play the wav")
        return
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(wav_path), "-c:a", "libvorbis", "-q:a", "5", str(target)],
        check=True,
    )
    if not keep_wav:
        wav_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the BeatLanes backing track.")
    parser.add_argument("--out", type=Path, default=config.SONG_PATH, help="output file")
    parser.add_argument("--keep-wav", action="store_true", help="keep the intermediate wav too")
    args = parser.parse_args()

    track = finalise(build_track())
    write_audio(track, Path(args.out), args.keep_wav)

    seconds = len(track) / SAMPLE_RATE
    print(
        f"wrote {args.out}  ({seconds:.1f} s, {beatplan.BARS} bars at {beatplan.BPM:.0f} BPM, "
        f"peak {float(np.max(np.abs(track))):.2f})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
