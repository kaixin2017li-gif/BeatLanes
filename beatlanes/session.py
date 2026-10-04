# One play-through: which notes are still live, and what each key press scored.
# No pygame objects in here, so the timing rules can be tested without a window.

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from . import config  # the GOOD window decides when a note is missed
from .chart import Chart  # the chart being played
from .judge import Judgement, Verdict, judge_tap  # the scoring rule
from .logbook import TapLog  # the CSV log
from .scoring import Score  # combo and totals
from .songclock import SongClock  # the clock


class NoteState(Enum):  # where a note is in its life
    PENDING = "pending"  # still falling, can still be hit
    HIT = "hit"  # was hit inside the window
    MISSED = "missed"  # the song walked past it


@dataclass
class LiveNote:  # a chart note plus its state during play
    index: int  # position in the chart
    lane: int  # which lane, 0..3
    time_ms: int  # target time
    state: NoteState = NoteState.PENDING  # starts as falling

    @property
    def live(self) -> bool:  # True while it can still be hit
        return self.state is NoteState.PENDING

    def screen_y(self, song_ms: float) -> float:
        # a note sits on the judgement line at its own target time; the position
        # comes from the clock, not from a per-frame step, so slow frames never
        # change when a note is judged
        px_per_ms = (config.JUDGE_LINE_Y - config.NOTE_SPAWN_Y) / config.APPROACH_MS
        return config.JUDGE_LINE_Y - (self.time_ms - song_ms) * px_per_ms


class PlaySession:  # owns the note states for one run
    def __init__(
        self,
        chart: Chart,
        clock: SongClock,
        logger: Optional[TapLog] = None,
        calibration_offset_ms: float = 0.0,
    ) -> None:
        self.chart = chart  # the chart being played
        self.clock = clock  # the song clock
        self.logger = logger  # CSV log, may be None in tests
        self.calibration_offset_ms = calibration_offset_ms  # kept for the log header
        self.notes = [LiveNote(note.index, note.lane, note.time_ms) for note in chart.notes]  # all notes, in play order
        self.score = Score(chart.note_count)  # combo and totals
        self.last_judgement: Optional[Judgement] = None  # for the on-screen popup
        self.last_judged_song_ms: float = 0.0  # when that popup appeared
        self.last_press_song_ms: dict[int, float] = {}  # lane -> song time of the last press, for the flash

    @property
    def live_notes(self) -> list[LiveNote]:  # the notes not yet hit or missed
        return [note for note in self.notes if note.live]

    def nearest_live_note(self, lane: int, at_ms: float) -> Optional[LiveNote]:
        # the pending note in this lane closest in time to the press
        best: Optional[LiveNote] = None
        for note in self.notes:
            if note.lane != lane or not note.live:  # wrong lane or already used
                continue
            if best is None or abs(note.time_ms - at_ms) < abs(best.time_ms - at_ms):
                best = note  # closer than the current best
        return best

    def update(self, song_ms: float) -> int:
        # miss every note the song has passed; returns how many
        missed = 0
        for note in self.notes:
            if note.live and song_ms - note.time_ms > config.GOOD_MS:  # window is over
                note.state = NoteState.MISSED  # nothing hit it, so it counts against the run
                self.score.register(Verdict.MISS)
                self._log(note, None, None, Verdict.MISS, None)  # logged with empty tap columns
                missed += 1
        return missed

    def register_tap(
        self,
        lane: int,  # which lane key was pressed
        tap_ms: Optional[float] = None,  # press time; sampled now if not given
        mixer_pos_ms: Optional[int] = None,  # mixer reading for the log
    ) -> Optional[Judgement]:
        # judge one key press. Returns a Judgement, or None when no note was
        # close enough to be scored.
        if tap_ms is None:  # real key press: use the clock right now
            tap_ms = self.clock.song_time_ms()
        self.last_press_song_ms[lane] = tap_ms  # kept for the lane flash

        note = self.nearest_live_note(lane, tap_ms)
        if note is None:  # nothing pending in this lane
            self.score.register_stray()
            return None

        judgement = judge_tap(tap_ms, note.time_ms)  # the subtraction
        if judgement.verdict is Verdict.MISS:
            # too far to be credited: the note stays live and will be missed on
            # its own if nothing better comes along
            self.score.register_stray()
            return None

        note.state = NoteState.HIT  # this note is used up
        self.score.register(judgement.verdict, early=judgement.early)
        self.last_judgement = judgement  # shown by the popup
        self.last_judged_song_ms = tap_ms  # popup animation starts here
        self._log(note, tap_ms, judgement.error_ms, judgement.verdict, mixer_pos_ms)
        return judgement

    def _log(self, note: LiveNote, tap_ms: Optional[float], error_ms: Optional[float], verdict: Verdict, mixer_pos_ms: Optional[int]) -> None:
        # write one row for this note, hit or missed
        if self.logger is None:  # tests run without a log
            return
        self.logger.write_tap(
            note_index=note.index,
            lane=note.lane,
            target_ms=note.time_ms,
            tap_ms=tap_ms,
            error_ms=error_ms,
            verdict=verdict,
            mixer_pos_ms=mixer_pos_ms,
        )

    @property
    def finished(self) -> bool:  # True once nothing is left to judge
        return self.score.finished

    def results_text(self) -> list[str]:  # the lines shown on the results screen
        score = self.score
        lines = [
            f"SCORE      {score.points} / {score.max_points}",
            f"RANK       {score.rank}",
            f"ACCURACY   {score.accuracy:.1f}%",
            "",
            f"PERFECT    {score.perfect}",
            f"GOOD       {score.good}",
            f"MISS       {score.miss}",
            "",
            f"BEST COMBO {score.best_combo}",
            f"EARLY/LATE {score.early_taps} / {score.late_taps}",
            f"STRAY TAPS {score.stray_taps}",
        ]
        return lines
