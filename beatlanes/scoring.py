# Combo, score and accuracy for one run.

from . import config  # the point values live there
from .judge import Verdict  # the three verdicts


class Score:  # running totals for one play-through
    def __init__(self, note_count: int) -> None:
        self.note_count = note_count  # total notes in the chart
        self.perfect = 0  # PERFECT count
        self.good = 0  # GOOD count
        self.miss = 0  # MISS count
        self.combo = 0  # consecutive non-miss notes right now
        self.best_combo = 0  # highest the combo reached
        self.stray_taps = 0  # presses too far from any note to count
        self.early_taps = 0  # hits that were before the target
        self.late_taps = 0  # hits that were after the target

    def register(self, verdict: Verdict, early: bool = False) -> None:
        # record one judged note, update the combo
        if verdict is Verdict.PERFECT:  # full points, combo keeps going
            self.perfect += 1
            self.combo += 1
        elif verdict is Verdict.GOOD:  # half points, combo also keeps going
            self.good += 1
            self.combo += 1
        else:  # a miss breaks the combo
            self.miss += 1
            self.combo = 0
        if verdict is not Verdict.MISS:  # only hits have a direction
            if early:
                self.early_taps += 1
            else:
                self.late_taps += 1
        self.best_combo = max(self.best_combo, self.combo)  # remember the peak

    def register_stray(self) -> None:  # a press that met no note
        self.stray_taps += 1  # counted but no note is consumed, combo unaffected

    @property
    def judged(self) -> int:  # notes hit or missed so far
        return self.perfect + self.good + self.miss

    @property
    def remaining(self) -> int:  # notes still to come
        return max(0, self.note_count - self.judged)

    @property
    def finished(self) -> bool:  # True when every note has been judged
        return self.judged >= self.note_count

    @property
    def points(self) -> int:  # points earned so far
        return (
            self.perfect * config.POINTS_PERFECT
            + self.good * config.POINTS_GOOD
            + self.miss * config.POINTS_MISS
        )

    @property
    def max_points(self) -> int:  # what a perfect run would earn
        return self.note_count * config.POINTS_PERFECT

    @property
    def accuracy(self) -> float:  # earned as a percentage of the maximum
        if self.max_points == 0:  # empty chart, avoid dividing by zero
            return 0.0
        return 100.0 * self.points / self.max_points

    @property
    def rank(self) -> str:  # rough grade for the results screen
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

    def summary(self) -> str:  # one line of totals, used in reports and tests
        return (
            f"PERFECT {self.perfect}  GOOD {self.good}  MISS {self.miss}  "
            f"best combo {self.best_combo}  accuracy {self.accuracy:.1f}%"
        )
