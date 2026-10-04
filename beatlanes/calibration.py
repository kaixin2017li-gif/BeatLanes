# allows the user to calibrate with there metronome
# there will be an added latency from the user tapping keys(audio, os and user) this will show as an added time this finds that added time and the clock will use it to compensate.

import json  # this will be stored as json
import statistics  # average and middle of taps
from datetime import datetime  # timestamp of when its stored
from pathlib import Path
from typing import Optional

from . import config  # total beats beat length and allowed error


class CalibrationRun:  # get all tap times while going through a metronome
    def __init__(
        self,
        beats: int = config.CALIBRATION_BEATS,  # how many clicks were played
        beat_ms: float = config.CALIBRATION_BEAT_MS,  # distance between each click
        tolerance_ms: float = config.CALIBRATION_TOLERANCE_MS,  # if they are farther then this its considered a miss fire
    ) -> None:
        self.beats = beats  # list of clicks during this session
        self.beat_ms = beat_ms  # time between each click
        self.tolerance_ms = tolerance_ms  # can only be no larger than .5 beat length
        self.offsets: list[float] = []  # stores all good taps as offsets
        self.skipped = 0  # taps that were consider miss fires

    @property
    def duration_ms(self) -> float:  # how long the clicks last
        return self.beats * self.beat_ms

    def beat_time_ms(self, index: int) -> float:  # time a click occurs
        return index * self.beat_ms

    def nearest_beat_index(self, song_ms: float) -> int:  # click your comparing to
        return int(round(song_ms / self.beat_ms))

    def beat_phase(self, song_ms: float) -> float:  # from 0-1 on current beat
        if self.beat_ms <= 0:  # prevents beat length of inf
            return 0.0
        return (song_ms % self.beat_ms) / self.beat_ms

    def register_tap(self, song_ms: float) -> Optional[float]:
        # compare a tap to the closest click returns none if it was to high of an offset
        index = self.nearest_beat_index(song_ms)
        if index < 0 or index >= self.beats:  # if tap is not within a run
            self.skipped += 1
            return None
        offset = song_ms - self.beat_time_ms(index)  # - means you were early
        if abs(offset) > self.tolerance_ms:  # most likely doubled tap or compared to the wrong click
            self.skipped += 1
            return None
        self.offsets.append(offset)
        return offset

    @property
    def tap_count(self) -> int:  # amount of taps that can be used
        return len(self.offsets)

    @property
    def finished(self) -> bool:  # minimum amount to get a reliable number
        return self.tap_count >= max(6, self.beats // 2)

    @property
    def mean_offset_ms(self) -> Optional[float]:  # keeps average
        if not self.offsets:
            return None
        return statistics.fmean(self.offsets)

    @property
    def median_offset_ms(self) -> Optional[float]:  # median, not mean: one
        if not self.offsets:  # distracted tap cannot drag it
            return None
        return statistics.median(self.offsets)  # median instead of average in case of 1 off tap

    @property
    def spread_ms(self) -> Optional[float]:  # standard deviation
        if len(self.offsets) < 2:  # requires at least 2 taps
            return None
        return statistics.pstdev(self.offsets)

    @property
    def offset_ms(self) -> Optional[float]:  # value to save
        return self.median_offset_ms

    def summary(self) -> str:  # information about the run
        offset = self.median_offset_ms
        if offset is None:  # if no good taps were collected
            return f"no usable taps ({self.skipped} ignored)"
        spread = self.spread_ms
        spread_text = "" if spread is None else f", spread {spread:.0f} ms"
        return (
            f"median {offset:+.0f} ms from {self.tap_count} taps"
            f" (mean {self.mean_offset_ms:+.0f} ms{spread_text}), "
            f"{self.skipped} ignored"
        )


def save_calibration(offset_ms: float, taps: int = 0, path: Optional[Path | str] = None) -> Path:
    # sets offset for next run
    target = Path(path) if path is not None else config.CALIBRATION_PATH
    payload = {
        "latency_offset_ms": round(float(offset_ms), 1),  # offset
        "measured_from_taps": taps,  # how many taps to get the offset
        "measured_at": datetime.now().isoformat(timespec="seconds"),  # time
        "note": "subtracted from the tick clock to get song time",  # information about tap
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def load_calibration(path: Optional[Path | str] = None) -> float:
    # get saved offset will default to 0
    target = Path(path) if path is not None else config.CALIBRATION_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):  # if there is no offset or corrupt file
        return 0.0
    try:
        return float(data["latency_offset_ms"])
    except (KeyError, TypeError, ValueError):  # if file is found but not correct format
        return 0.0
