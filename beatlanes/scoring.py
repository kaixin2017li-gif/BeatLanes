# Used to keep track of your combo score and accuracy during a run.

from . import config  # will hold the constants for scoring
from .judge import Verdict  # our different verdicts


class Score:  # used to keep track of your score through a run
    def __init__(self, note_count: int) -> None:
        self.note_count = note_count  # amount of notes in the song
        self.perfect = 0  # amount of PERFECT notes hit
        self.good = 0  # amount of GOOD notes hit
        self.miss = 0  # amount of notes missed
        self.combo = 0  # how many notes you have hit without missing in a row
        self.best_combo = 0  # highest combo achieved during the run
        self.stray_taps = 0  # clicks that were to far away to be considered a tap on a note
        self.early_taps = 0  # how many notes you have tapped early on
        self.late_taps = 0  # how many notes you have tapped late on

    def register(self, verdict: Verdict, early: bool = False) -> None:  # take a note that was judged and update combo
        if verdict is Verdict.PERFECT:  # will add all points and keep your combo going
            self.perfect += 1
            self.combo += 1
        elif verdict is Verdict.GOOD:  # will add half the points and keep combo going
            self.good += 1
            self.combo += 1
        else:  # resets your combo
            self.miss += 1
            self.combo = 0
        if verdict is not Verdict.MISS:  # will only be true if the press is on a note
            if early:
                self.early_taps += 1
            else:
                self.late_taps += 1
        self.best_combo = max(self.best_combo, self.combo)  # keep track of your best combo

    def register_stray(self) -> None:  # click that did not land on any notes
        self.stray_taps += 1  # still registers as a click but will not consume a note nor affect your combo

    @property
    def judged(self) -> int:  # amount of notes you have completed or missed
        return self.perfect + self.good + self.miss

    @property
    def remaining(self) -> int:  # how many notes you have left
        return max(0, self.note_count - self.judged)

    @property
    def finished(self) -> bool:  # True if you have finished all the notes in the song
        return self.judged >= self.note_count

    @property
    def points(self) -> int:  # current amount of points you have
        return (
            self.perfect * config.POINTS_PERFECT
            + self.good * config.POINTS_GOOD
            + self.miss * config.POINTS_MISS
        )

    @property
    def max_points(self) -> int:  # what you would have gotten if you got them all
        return self.note_count * config.POINTS_PERFECT

    @property
    def accuracy(self) -> float:  # current score / max possible score
        if self.max_points == 0:  # if there is no notes dont divide by 0
            return 0.0
        return 100.0 * self.points / self.max_points

    @property
    def rank(self) -> str:  # give yourself a general idea of how well you did for the ending screen
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

    def summary(self) -> str:  # one line summary of all stats used in printing and unit testing
        return (
            f"PERFECT {self.perfect}  GOOD {self.good}  MISS {self.miss}  "
            f"best combo {self.best_combo}  accuracy {self.accuracy:.1f}%"
        )
