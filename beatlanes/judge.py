# The judgement: decides if a key press counted.
# Kept free of pygame so the tests can call it directly.
# The whole rule is error = tap_ms - target_ms, then two windows.

from __future__ import annotations

from dataclasses import dataclass  # gives Judgement its fields for free
from enum import Enum  # for the three verdicts

from . import config  # the window constants live there


class Verdict(Enum):  # the three outcomes a note can end with
    PERFECT = "PERFECT"
    GOOD = "GOOD"
    MISS = "MISS"


@dataclass(frozen=True)  # frozen so a judgement cannot be edited by accident
class Judgement:  # one tap that was scored against a note
    error_ms: float  # signed: negative = early, positive = late
    verdict: Verdict  # what the error was worth

    @property
    def early(self) -> bool:  # True when the tap came before the target time
        return self.error_ms < 0

    @property
    def offset_text(self) -> str:  # the offset as the HUD shows it
        if self.error_ms == 0:  # exact hit reads better than "+0 ms late"
            return "+0 ms on time"
        direction = "early" if self.early else "late"  # pick the word from the sign
        return f"{self.error_ms:+.0f} ms {direction}"


def verdict_for_error(error_ms: float) -> Verdict:
    # abs(error) against the two windows in config
    error = abs(error_ms)
    if error <= config.PERFECT_MS:  # inside 50 ms
        return Verdict.PERFECT
    if error <= config.GOOD_MS:  # inside 120 ms
        return Verdict.GOOD
    return Verdict.MISS  # anything further is not a hit


def judge_tap(tap_ms: float, target_ms: float) -> Judgement:
    # the whole judgement: one subtraction, then the windows decide
    error_ms = float(tap_ms) - float(target_ms)
    return Judgement(error_ms=error_ms, verdict=verdict_for_error(error_ms))


def is_inside_good_window(error_ms: float) -> bool:
    # used before scoring, to check a press is even close enough to a note
    return abs(error_ms) <= config.GOOD_MS
