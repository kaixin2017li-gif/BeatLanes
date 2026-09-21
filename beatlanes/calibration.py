"""Tap-to-metronome calibration.

Key presses cannot be timestamped as precisely as the song clock can be read.
There is a buffer in the audio path, the operating system takes its time to hand
the key event over, and a player does not hit exactly on the beat either. All
three end up as a constant shift in the same direction, so BeatLanes measures it
once and subtracts it.

The test: sixteen clicks at 120 BPM, the player taps D on each one, and the
offset of every tap from its click is recorded. The value that gets saved is the
median, not the mean - one distracted tap of 200 ms should not drag the
calibration with it.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import config


class CalibrationRun:
    """Collects tap offsets during one metronome run."""

    def __init__(
        self,
        beats: int = config.CALIBRATION_BEATS,
        beat_ms: float = config.CALIBRATION_BEAT_MS,
        tolerance_ms: float = config.CALIBRATION_TOLERANCE_MS,
    ) -> None:
        self.beats = beats
        self.beat_ms = beat_ms
        self.tolerance_ms = tolerance_ms
        self.offsets: list[float] = []
        self.skipped = 0

    # --- the click track --------------------------------------------------
    @property
    def duration_ms(self) -> float:
        return self.beats * self.beat_ms

    def beat_time_ms(self, index: int) -> float:
        return index * self.beat_ms

    def nearest_beat_index(self, song_ms: float) -> int:
        return int(round(song_ms / self.beat_ms))

    def beat_phase(self, song_ms: float) -> float:
        """How far through the current beat we are, 0.0 to 1.0."""
        if self.beat_ms <= 0:
            return 0.0
        return (song_ms % self.beat_ms) / self.beat_ms

    # --- the player -------------------------------------------------------
    def register_tap(self, song_ms: float) -> Optional[float]:
        """Score one tap against the closest click.

        Returns the signed offset, or None when the tap was too far from any
        click to mean anything (or landed outside the run).
        """
        index = self.nearest_beat_index(song_ms)
        if index < 0 or index >= self.beats:
            self.skipped += 1
            return None
        offset = song_ms - self.beat_time_ms(index)
        if abs(offset) > self.tolerance_ms:
            self.skipped += 1
            return None
        self.offsets.append(offset)
        return offset

    # --- results ----------------------------------------------------------
    @property
    def tap_count(self) -> int:
        return len(self.offsets)

    @property
    def finished(self) -> bool:
        """Enough taps to trust the number."""
        return self.tap_count >= max(6, self.beats // 2)

    @property
    def mean_offset_ms(self) -> Optional[float]:
        if not self.offsets:
            return None
        return statistics.fmean(self.offsets)

    @property
    def median_offset_ms(self) -> Optional[float]:
        if not self.offsets:
            return None
        return statistics.median(self.offsets)

    @property
    def spread_ms(self) -> Optional[float]:
        """Standard deviation of the taps, a rough read on consistency."""
        if len(self.offsets) < 2:
            return None
        return statistics.pstdev(self.offsets)

    @property
    def offset_ms(self) -> Optional[float]:
        """The value that should be saved."""
        return self.median_offset_ms

    def summary(self) -> str:
        offset = self.median_offset_ms
        if offset is None:
            return f"no usable taps ({self.skipped} ignored)"
        spread = self.spread_ms
        spread_text = "" if spread is None else f", spread {spread:.0f} ms"
        return (
            f"median {offset:+.0f} ms from {self.tap_count} taps"
            f" (mean {self.mean_offset_ms:+.0f} ms{spread_text}), "
            f"{self.skipped} ignored"
        )


def save_calibration(offset_ms: float, taps: int = 0, path: Optional[Path | str] = None) -> Path:
    """Write the offset to disk so the next run starts with it."""
    target = Path(path) if path is not None else config.CALIBRATION_PATH
    payload = {
        "latency_offset_ms": round(float(offset_ms), 1),
        "measured_from_taps": taps,
        "measured_at": datetime.now().isoformat(timespec="seconds"),
        "note": "subtracted from the tick clock to get song time",
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def load_calibration(path: Optional[Path | str] = None) -> float:
    """Read a saved offset. A missing or broken file means zero."""
    target = Path(path) if path is not None else config.CALIBRATION_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return 0.0
    try:
        return float(data["latency_offset_ms"])
    except (KeyError, TypeError, ValueError):
        return 0.0
