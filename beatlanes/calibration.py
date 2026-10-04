# Tap-to-metronome calibration.
# Key presses carry extra delay (audio buffer, OS, human), which shows up as a
# constant shift. This measures the shift once and the clock subtracts it.

import json  # the offset is saved as JSON
import statistics  # mean and median of the taps
from datetime import datetime  # stamp on the saved file
from pathlib import Path
from typing import Optional

from . import config  # beats, beat length, tolerance


class CalibrationRun:  # collects tap offsets during one metronome run
    def __init__(
        self,
        beats: int = config.CALIBRATION_BEATS,  # number of clicks
        beat_ms: float = config.CALIBRATION_BEAT_MS,  # click spacing
        tolerance_ms: float = config.CALIBRATION_TOLERANCE_MS,  # misfire cutoff
    ) -> None:
        self.beats = beats  # clicks in this run
        self.beat_ms = beat_ms  # spacing between clicks
        self.tolerance_ms = tolerance_ms  # must stay below half a beat
        self.offsets: list[float] = []  # one offset per usable tap
        self.skipped = 0  # taps ignored as misfires

    @property
    def duration_ms(self) -> float:  # how long the click track lasts
        return self.beats * self.beat_ms

    def beat_time_ms(self, index: int) -> float:  # when one click happens
        return index * self.beat_ms

    def nearest_beat_index(self, song_ms: float) -> int:  # the click a tap is scored against
        return int(round(song_ms / self.beat_ms))

    def beat_phase(self, song_ms: float) -> float:  # 0.0..1.0 through the current beat
        if self.beat_ms <= 0:  # guards a nonsense beat length
            return 0.0
        return (song_ms % self.beat_ms) / self.beat_ms

    def register_tap(self, song_ms: float) -> Optional[float]:
        # score a tap against the closest click; None when it was too far away
        # to mean anything
        index = self.nearest_beat_index(song_ms)
        if index < 0 or index >= self.beats:  # outside the run
            self.skipped += 1
            return None
        offset = song_ms - self.beat_time_ms(index)  # signed: negative = early
        if abs(offset) > self.tolerance_ms:  # probably a double tap or wrong click
            self.skipped += 1
            return None
        self.offsets.append(offset)
        return offset

    @property
    def tap_count(self) -> int:  # usable taps so far
        return len(self.offsets)

    @property
    def finished(self) -> bool:  # enough taps to trust the number
        return self.tap_count >= max(6, self.beats // 2)

    @property
    def mean_offset_ms(self) -> Optional[float]:  # average, kept for comparison
        if not self.offsets:
            return None
        return statistics.fmean(self.offsets)

    @property
    def median_offset_ms(self) -> Optional[float]:  # median, not mean: one
        if not self.offsets:  # distracted tap cannot drag it
            return None
        return statistics.median(self.offsets)

    @property
    def spread_ms(self) -> Optional[float]:  # std dev, a read on consistency
        if len(self.offsets) < 2:  # need at least two taps
            return None
        return statistics.pstdev(self.offsets)

    @property
    def offset_ms(self) -> Optional[float]:  # the value that gets saved
        return self.median_offset_ms

    def summary(self) -> str:  # one line describing the run
        offset = self.median_offset_ms
        if offset is None:  # nothing usable was tapped
            return f"no usable taps ({self.skipped} ignored)"
        spread = self.spread_ms
        spread_text = "" if spread is None else f", spread {spread:.0f} ms"
        return (
            f"median {offset:+.0f} ms from {self.tap_count} taps"
            f" (mean {self.mean_offset_ms:+.0f} ms{spread_text}), "
            f"{self.skipped} ignored"
        )


def save_calibration(offset_ms: float, taps: int = 0, path: Optional[Path | str] = None) -> Path:
    # write the offset so the next run starts with it
    target = Path(path) if path is not None else config.CALIBRATION_PATH
    payload = {
        "latency_offset_ms": round(float(offset_ms), 1),  # the useful number
        "measured_from_taps": taps,  # how many taps backed it
        "measured_at": datetime.now().isoformat(timespec="seconds"),  # when
        "note": "subtracted from the tick clock to get song time",  # what it means
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def load_calibration(path: Optional[Path | str] = None) -> float:
    # read a saved offset; a missing or broken file means zero
    target = Path(path) if path is not None else config.CALIBRATION_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):  # no file / broken file
        return 0.0
    try:
        return float(data["latency_offset_ms"])
    except (KeyError, TypeError, ValueError):  # file exists but is wrong
        return 0.0
