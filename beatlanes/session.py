"""One play-through of a chart.

The session owns the state of every note and turns key presses into
judgements. It holds no Pygame objects at all: it is given song times and lane
numbers, and it answers with verdicts. That is what makes the timing rules
testable without a window or a sound card.

Flow for a single note:

    PENDING --tap inside the good window--> HIT
    PENDING --song time passes it by-------> MISSED

A press that no note is close enough to is counted as a stray tap. It does not
consume a note and it does not break the combo; it usually means the player is
tired, or that the calibration offset is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from . import config
from .chart import Chart
from .judge import Judgement, Verdict, judge_tap
from .logbook import TapLog
from .scoring import Score
from .songclock import SongClock


class NoteState(Enum):
    """Where a note is in its life."""

    PENDING = "pending"
    HIT = "hit"
    MISSED = "missed"


@dataclass
class LiveNote:
    """A chart note plus its state during play."""

    index: int
    lane: int
    time_ms: int
    state: NoteState = NoteState.PENDING

    @property
    def live(self) -> bool:
        return self.state is NoteState.PENDING

    def screen_y(self, song_ms: float) -> float:
        """Where this note is drawn at the given song time.

        A note sits on the judgement line at its own target time, and is
        APPROACH_MS above it one approach-length earlier. Everything else is
        linear, which is why the notes stay locked to the music even when the
        frame rate wobbles: the position comes from the clock, not from a
        per-frame movement step.
        """
        px_per_ms = (config.JUDGE_LINE_Y - config.NOTE_SPAWN_Y) / config.APPROACH_MS
        return config.JUDGE_LINE_Y - (self.time_ms - song_ms) * px_per_ms


class PlaySession:
    """Turns key presses into judgements for one run."""

    def __init__(
        self,
        chart: Chart,
        clock: SongClock,
        logger: Optional[TapLog] = None,
        calibration_offset_ms: float = 0.0,
    ) -> None:
        self.chart = chart
        self.clock = clock
        self.logger = logger
        self.calibration_offset_ms = calibration_offset_ms
        self.notes = [LiveNote(note.index, note.lane, note.time_ms) for note in chart.notes]
        self.score = Score(chart.note_count)
        # last verdict and the song time it happened at, for the on-screen popup
        self.last_judgement: Optional[Judgement] = None
        self.last_judged_song_ms: float = 0.0
        # lane -> song time of the last press, used for the lane flash
        self.last_press_song_ms: dict[int, float] = {}

    # --- lookups ----------------------------------------------------------
    @property
    def live_notes(self) -> list[LiveNote]:
        return [note for note in self.notes if note.live]

    def nearest_live_note(self, lane: int, at_ms: float) -> Optional[LiveNote]:
        """The pending note in this lane closest in time to the press."""
        best: Optional[LiveNote] = None
        for note in self.notes:
            if note.lane != lane or not note.live:
                continue
            if best is None or abs(note.time_ms - at_ms) < abs(best.time_ms - at_ms):
                best = note
        return best

    # --- play -------------------------------------------------------------
    def update(self, song_ms: float) -> int:
        """Miss every note the song has already passed. Returns how many."""
        missed = 0
        for note in self.notes:
            if note.live and song_ms - note.time_ms > config.GOOD_MS:
                note.state = NoteState.MISSED
                self.score.register(Verdict.MISS)
                self._log(note, None, None, Verdict.MISS, None)
                missed += 1
        return missed

    def register_tap(
        self,
        lane: int,
        tap_ms: Optional[float] = None,
        mixer_pos_ms: Optional[int] = None,
    ) -> Optional[Judgement]:
        """Judge one key press.

        Returns the Judgement when a note was scored, or None when the press
        was too far from any note to count.
        """
        if tap_ms is None:
            tap_ms = self.clock.song_time_ms()
        self.last_press_song_ms[lane] = tap_ms

        note = self.nearest_live_note(lane, tap_ms)
        if note is None:
            self.score.register_stray()
            return None

        judgement = judge_tap(tap_ms, note.time_ms)
        if judgement.verdict is Verdict.MISS:
            # too far away to be credited: the note stays live and will be
            # missed on its own if nothing better comes along
            self.score.register_stray()
            return None

        note.state = NoteState.HIT
        self.score.register(judgement.verdict, early=judgement.early)
        self.last_judgement = judgement
        self.last_judged_song_ms = tap_ms
        self._log(note, tap_ms, judgement.error_ms, judgement.verdict, mixer_pos_ms)
        return judgement

    # --- internals --------------------------------------------------------
    def _log(
        self,
        note: LiveNote,
        tap_ms: Optional[float],
        error_ms: Optional[float],
        verdict: Verdict,
        mixer_pos_ms: Optional[int],
    ) -> None:
        if self.logger is None:
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

    # --- results ----------------------------------------------------------
    @property
    def finished(self) -> bool:
        """True once nothing is left to judge."""
        return self.score.finished

    def results_text(self) -> list[str]:
        """Lines for the results screen."""
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
