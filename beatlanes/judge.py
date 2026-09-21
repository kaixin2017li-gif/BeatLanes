"""The judgement system.

This is the part of BeatLanes that decides whether a key press counted, and it
is deliberately kept away from pygame so the tests can call it directly.

The whole thing is a subtraction:

    error = tap_ms - target_ms

A negative error means the player pressed early, a positive error means late.
The absolute value decides the verdict:

    <= PERFECT_MS (50 ms)   -> PERFECT
    <= GOOD_MS   (120 ms)   -> GOOD
    anything further away   -> MISS (the press is not counted against a note)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from . import config


class Verdict(Enum):
    """The three outcomes a note can end with."""

    PERFECT = "PERFECT"
    GOOD = "GOOD"
    MISS = "MISS"


@dataclass(frozen=True)
class Judgement:
    """A tap that was scored against a note."""

    error_ms: float
    verdict: Verdict

    @property
    def early(self) -> bool:
        """True when the tap came before the target time."""
        return self.error_ms < 0

    @property
    def offset_text(self) -> str:
        """Signed offset as it is shown on screen, e.g. '-32 ms early'."""
        if self.error_ms == 0:
            return "+0 ms on time"
        direction = "early" if self.early else "late"
        return f"{self.error_ms:+.0f} ms {direction}"


def verdict_for_error(error_ms: float) -> Verdict:
    """Map a signed timing error onto a verdict using the window settings."""
    error = abs(error_ms)
    if error <= config.PERFECT_MS:
        return Verdict.PERFECT
    if error <= config.GOOD_MS:
        return Verdict.GOOD
    return Verdict.MISS


def judge_tap(tap_ms: float, target_ms: float) -> Judgement:
    """Score one tap against one note's target time."""
    error_ms = float(tap_ms) - float(target_ms)
    return Judgement(error_ms=error_ms, verdict=verdict_for_error(error_ms))


def is_inside_good_window(error_ms: float) -> bool:
    """Whether a press is close enough to a note to be judged against it."""
    return abs(error_ms) <= config.GOOD_MS
