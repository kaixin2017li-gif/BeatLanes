"""Combo and score bookkeeping.

Combo counts consecutive judged notes that were not missed. Accuracy is the
points earned divided by the points a perfect run would earn, so it can be
read as a percentage.
"""

from __future__ import annotations

from . import config
from .judge import Verdict


class Score:
    """Running totals for one play-through."""

    def __init__(self, note_count: int) -> None:
        self.note_count = note_count
        self.perfect = 0
        self.good = 0
        self.miss = 0
        self.combo = 0
        self.best_combo = 0
        # Key presses that were not close enough to any note to be judged.
        # They are worth watching: a lot of them usually means the player is
        # fighting the calibration offset.
        self.stray_taps = 0
        self.early_taps = 0
        self.late_taps = 0

    def register(self, verdict: Verdict, early: bool = False) -> None:
        """Record one judged note."""
        if verdict is Verdict.PERFECT:
            self.perfect += 1
            self.combo += 1
        elif verdict is Verdict.GOOD:
            self.good += 1
            self.combo += 1
        else:
            self.miss += 1
            self.combo = 0
        if verdict is not Verdict.MISS:
            if early:
                self.early_taps += 1
            else:
                self.late_taps += 1
        self.best_combo = max(self.best_combo, self.combo)

    def register_stray(self) -> None:
        """Record a key press that met no note."""
        self.stray_taps += 1

    @property
    def judged(self) -> int:
        """Notes that have been hit or missed so far."""
        return self.perfect + self.good + self.miss

    @property
    def remaining(self) -> int:
        return max(0, self.note_count - self.judged)

    @property
    def finished(self) -> bool:
        return self.judged >= self.note_count

    @property
    def points(self) -> int:
        return (
            self.perfect * config.POINTS_PERFECT
            + self.good * config.POINTS_GOOD
            + self.miss * config.POINTS_MISS
        )

    @property
    def max_points(self) -> int:
        return self.note_count * config.POINTS_PERFECT

    @property
    def accuracy(self) -> float:
        """Percentage of the available points that were earned."""
        if self.max_points == 0:
            return 0.0
        return 100.0 * self.points / self.max_points

    @property
    def rank(self) -> str:
        """A rough grade for the results screen."""
        accuracy = self.accuracy
        if accuracy >= 98:
            return "S"
        if accuracy >= 92:
            return "A"
        if accuracy >= 80:
            return "B"
        if accuracy >= 65:
            return "C"
        return "D"

    def summary(self) -> str:
        return (
            f"PERFECT {self.perfect}  GOOD {self.good}  MISS {self.miss}  "
            f"best combo {self.best_combo}  accuracy {self.accuracy:.1f}%"
        )
