# Judgement: checks if a keypress is a hit.
# separated from pygame to allow for easier testing.
# all of it can be summed up to error = tap time - target time. we have two windows.

from __future__ import annotations

from dataclasses import dataclass  # gives Judgement its attributes
from enum import Enum  # corresponding to each verdict

from . import config  # window sizes go here


class Verdict(Enum):  # can return good, late or miss
    PERFECT = "PERFECT"
    GOOD = "GOOD"
    MISS = "MISS"


@dataclass(frozen=True)  # immutable so you cant mess up your judgement
class Judgement:  # represents a single tap that hit a note
    error_ms: float  # can be negative (early) or positive (late)
    verdict: Verdict  # how far off you were

    @property
    def early(self) -> bool:  # if error is negative we know your early
        return self.error_ms < 0

    @property
    def offset_text(self) -> str:  # displayable version of your error
        if self.error_ms == 0:  # "+0 ms late" didnt look as cool
            return "+0 ms on time"
        direction = "early" if self.early else "late"  # based on if your late or early
        return f"{self.error_ms:+.0f} ms {direction}"


def verdict_for_error(error_ms: float) -> Verdict:
    # we compare the absolute value of our error to these 2 windows in our config
    error = abs(error_ms)
    if error <= config.PERFECT_MS:  # within 50 milliseconds of the target time
        return Verdict.PERFECT
    if error <= config.GOOD_MS:  # within 120 milliseconds of the target time
        return Verdict.GOOD
    return Verdict.MISS  # if your not within these windows you missed


def judge_tap(tap_ms: float, target_ms: float) -> Judgement:
    # error = tap time - target time, then judge the windows
    error_ms = float(tap_ms) - float(target_ms)
    return Judgement(error_ms=error_ms, verdict=verdict_for_error(error_ms))


def is_inside_good_window(error_ms: float) -> bool:
    # this will be used to determine if the key press should even be scored
    return abs(error_ms) <= config.GOOD_MS
