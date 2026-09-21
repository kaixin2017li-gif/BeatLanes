"""Tests for one play-through.

This is where the rules meet the notes: a tap inside the window takes the note,
a tap outside it does not, and a note nobody hits is missed when the song walks
past it. The CSV log is checked here too, because a log with the wrong numbers
in it is worse than no log.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from beatlanes import config  # noqa: E402
from beatlanes.chart import Chart, ChartNote  # noqa: E402
from beatlanes.judge import Verdict  # noqa: E402
from beatlanes.logbook import TapLog, read_log  # noqa: E402
from beatlanes.session import NoteState, PlaySession  # noqa: E402
from beatlanes.songclock import SongClock  # noqa: E402


def make_chart(*notes: tuple[int, int]) -> Chart:
    """notes are (time_ms, lane) pairs."""
    ordered = sorted(notes)
    return Chart(
        title="test chart",
        bpm=120.0,
        notes=tuple(
            ChartNote(index=index, lane=lane, time_ms=time_ms)
            for index, (time_ms, lane) in enumerate(ordered)
        ),
    )


class SessionTests(unittest.TestCase):
    def make_session(self, *notes, logger=None) -> PlaySession:
        chart = make_chart(*notes)
        clock = SongClock(ticks_provider=lambda: 0, mixer_pos_provider=lambda: -1)
        return PlaySession(chart, clock, logger=logger)

    def test_a_tap_on_the_note_is_perfect(self):
        session = self.make_session((1000, 0))
        judgement = session.register_tap(0, tap_ms=1000.0)
        self.assertIs(judgement.verdict, Verdict.PERFECT)
        self.assertIs(session.notes[0].state, NoteState.HIT)

    def test_a_tap_80_ms_late_is_good(self):
        # 40 ms would still be inside the 50 ms PERFECT window, so the GOOD
        # case has to be taken from past that edge
        session = self.make_session((1000, 0))
        self.assertIs(session.register_tap(0, tap_ms=1080.0).verdict, Verdict.GOOD)

    def test_the_wrong_lane_does_not_take_the_note(self):
        session = self.make_session((1000, 0))
        self.assertIsNone(session.register_tap(2, tap_ms=1000.0))
        self.assertIs(session.notes[0].state, NoteState.PENDING)

    def test_a_tap_far_from_every_note_is_a_stray(self):
        session = self.make_session((1000, 0))
        self.assertIsNone(session.register_tap(0, tap_ms=1400.0))
        self.assertEqual(session.score.stray_taps, 1)
        self.assertIs(session.notes[0].state, NoteState.PENDING)

    def test_a_note_nobody_hits_is_missed_by_the_song(self):
        session = self.make_session((1000, 0))
        self.assertEqual(session.update(1000.0), 0)  # still inside the window
        self.assertEqual(session.update(1000.0 + config.GOOD_MS + 1), 1)
        self.assertIs(session.notes[0].state, NoteState.MISSED)
        self.assertEqual(session.score.miss, 1)

    def test_update_does_not_miss_the_same_note_twice(self):
        session = self.make_session((1000, 0))
        session.update(5000.0)
        session.update(6000.0)
        self.assertEqual(session.score.miss, 1)

    def test_the_closest_note_in_the_lane_wins(self):
        session = self.make_session((1000, 0), (1200, 0))
        judgement = session.register_tap(0, tap_ms=1180.0)
        self.assertAlmostEqual(judgement.error_ms, -20.0)
        states = {note.time_ms: note.state for note in session.notes}
        self.assertIs(states[1200], NoteState.HIT)
        self.assertIs(states[1000], NoteState.PENDING)

    def test_a_hit_note_is_not_offered_again(self):
        session = self.make_session((1000, 0))
        session.register_tap(0, tap_ms=1000.0)
        self.assertIsNone(session.register_tap(0, tap_ms=1000.0))

    def test_notes_in_other_lanes_are_untouched(self):
        session = self.make_session((1000, 0), (1000, 3))
        session.register_tap(0, tap_ms=1000.0)
        by_lane = {note.lane: note.state for note in session.notes}
        self.assertIs(by_lane[0], NoteState.HIT)
        self.assertIs(by_lane[3], NoteState.PENDING)

    def test_the_session_finishes_when_every_note_is_judged(self):
        session = self.make_session((1000, 0), (1500, 1))
        self.assertFalse(session.finished)
        session.update(5000.0)
        self.assertTrue(session.finished)

    def test_results_text_carries_the_headline_numbers(self):
        session = self.make_session((1000, 0))
        session.register_tap(0, tap_ms=1000.0)
        text = "\n".join(session.results_text())
        self.assertIn("RANK", text)
        self.assertIn("ACCURACY", text)

    def test_lane_press_times_are_kept_for_the_flash(self):
        session = self.make_session((1000, 0))
        session.register_tap(0, tap_ms=980.0)
        self.assertEqual(session.last_press_song_ms[0], 980.0)


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "taps.csv"

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_hit_writes_target_tap_and_error(self):
        with TapLog(path=self.path, calibration_ms=0.0) as log:
            session = PlaySession(
                make_chart((1000, 0)),
                SongClock(ticks_provider=lambda: 0, mixer_pos_provider=lambda: -1),
                logger=log,
            )
            session.register_tap(0, tap_ms=1090.0, mixer_pos_ms=990)
        rows = read_log(self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target_ms"], "1000")
        self.assertEqual(rows[0]["tap_ms"], "1090")
        self.assertEqual(rows[0]["error_ms"], "+90")
        self.assertEqual(rows[0]["verdict"], "GOOD")
        self.assertEqual(rows[0]["mixer_pos_ms"], "990")

    def test_a_miss_is_logged_with_empty_tap_columns(self):
        with TapLog(path=self.path) as log:
            session = PlaySession(
                make_chart((1000, 0)),
                SongClock(ticks_provider=lambda: 0, mixer_pos_provider=lambda: -1),
                logger=log,
            )
            session.update(9000.0)
        rows = read_log(self.path)
        self.assertEqual(rows[0]["verdict"], "MISS")
        self.assertEqual(rows[0]["tap_ms"], "")
        self.assertEqual(rows[0]["error_ms"], "")

    def test_every_note_gets_exactly_one_row(self):
        with TapLog(path=self.path) as log:
            session = PlaySession(
                make_chart((1000, 0), (1500, 1), (2000, 2)),
                SongClock(ticks_provider=lambda: 0, mixer_pos_provider=lambda: -1),
                logger=log,
            )
            session.register_tap(0, tap_ms=1000.0)
            session.update(9000.0)
        rows = read_log(self.path)
        self.assertEqual(len(rows), 3)
        self.assertEqual({row["note_index"] for row in rows}, {"0", "1", "2"})

    def test_the_header_records_the_calibration(self):
        with TapLog(path=self.path, song="demo", calibration_ms=-42.0) as log:
            pass
        raw = self.path.read_text(encoding="utf-8")
        self.assertIn("# song demo", raw)
        self.assertIn("# calibration_offset_ms -42", raw)

    def test_a_run_without_a_logger_does_not_crash(self):
        session = PlaySession(
            make_chart((1000, 0)),
            SongClock(ticks_provider=lambda: 0, mixer_pos_provider=lambda: -1),
            logger=None,
        )
        session.register_tap(0, tap_ms=1000.0)
        session.update(9000.0)


if __name__ == "__main__":
    unittest.main()
