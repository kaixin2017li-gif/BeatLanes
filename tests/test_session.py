"""Tests for one play-through.

This is where the rules meet the notes: a tap inside the window takes the note,
a tap outside it does not, and a note nobody hits is missed when the song walks
past it. The CSV log is checked here too, because a log with the wrong numbers
in it is worse than no log.
"""

from __future__ import annotations  # modern hint syntax

import sys  # to reach the repo root
import tempfile  # for the log file tests
import unittest  # the runner
from pathlib import Path  # for the temp paths

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the same line in every test file, tests run from any folder

from beatlanes import config  # noqa: E402  # the good window
from beatlanes.chart import Chart, ChartNote  # noqa: E402  # tiny charts get built here
from beatlanes.judge import Verdict  # noqa: E402  # the verdicts
from beatlanes.logbook import TapLog, read_log  # noqa: E402  # the log and its reader
from beatlanes.session import NoteState, PlaySession  # noqa: E402  # the thing under test
from beatlanes.songclock import SongClock  # noqa: E402  # a frozen clock


def make_chart(*notes: tuple[int, int]) -> Chart:  # helper: build a chart from (time, lane) pairs
    """notes are (time_ms, lane) pairs."""
    ordered = sorted(notes)  # sort so the indexes come out right
    return Chart(  # the chart object
        title="test chart",  # any title
        bpm=120.0,  # any bpm
        notes=tuple(  # the notes
            ChartNote(index=index, lane=lane, time_ms=time_ms)  # fresh index per note
            for index, (time_ms, lane) in enumerate(ordered)  # from the sorted pairs
        ),  # from the sorted pairs
    )  # chart built


class SessionTests(unittest.TestCase):  # the tap and miss rules
    def make_session(self, *notes, logger=None) -> PlaySession:  # shared builder for the tests
        chart = make_chart(*notes)  # the tiny chart
        clock = SongClock(ticks_provider=lambda: 0, mixer_pos_provider=lambda: -1)  # a clock that never moves
        return PlaySession(chart, clock, logger=logger)  # the session

    def test_a_tap_on_the_note_is_perfect(self):  # dead on the note
        session = self.make_session((1000, 0))  # one note at 1000
        judgement = session.register_tap(0, tap_ms=1000.0)  # tap at exactly 1000
        self.assertIs(judgement.verdict, Verdict.PERFECT)  # perfect
        self.assertIs(session.notes[0].state, NoteState.HIT)  # note used up

    def test_a_tap_80_ms_late_is_good(self):  # good, but not perfect
        # 40 ms would still be inside the 50 ms PERFECT window, so the GOOD
        # case has to be taken from past that edge
        session = self.make_session((1000, 0))  # same note
        self.assertIs(session.register_tap(0, tap_ms=1080.0).verdict, Verdict.GOOD)  # 80 ms late lands in good

    def test_the_wrong_lane_does_not_take_the_note(self):  # lanes are separate
        session = self.make_session((1000, 0))  # note in lane 0
        self.assertIsNone(session.register_tap(2, tap_ms=1000.0))  # press lane 2 instead
        self.assertIs(session.notes[0].state, NoteState.PENDING)  # note still waiting

    def test_a_tap_far_from_every_note_is_a_stray(self):  # too far from everything
        session = self.make_session((1000, 0))  # one note at 1000
        self.assertIsNone(session.register_tap(0, tap_ms=1400.0))  # 400 ms away
        self.assertEqual(session.score.stray_taps, 1)  # counted as a stray
        self.assertIs(session.notes[0].state, NoteState.PENDING)  # and the note survives

    def test_a_note_nobody_hits_is_missed_by_the_song(self):  # the song does the missing
        session = self.make_session((1000, 0))  # one note
        self.assertEqual(session.update(1000.0), 0)  # still inside the window  # inside the window still
        self.assertEqual(session.update(1000.0 + config.GOOD_MS + 1), 1)  # one ms past the window
        self.assertIs(session.notes[0].state, NoteState.MISSED)  # now missed
        self.assertEqual(session.score.miss, 1)  # and scored as a miss

    def test_update_does_not_miss_the_same_note_twice(self):  # a miss happens once
        session = self.make_session((1000, 0))  # one note
        session.update(5000.0)  # way past it
        session.update(6000.0)  # and again
        self.assertEqual(session.score.miss, 1)  # still just one miss

    def test_the_closest_note_in_the_lane_wins(self):  # the aiming rule
        session = self.make_session((1000, 0), (1200, 0))  # two notes in lane 0
        judgement = session.register_tap(0, tap_ms=1180.0)  # closer to the second one
        self.assertAlmostEqual(judgement.error_ms, -20.0)  # judged against 1200
        states = {note.time_ms: note.state for note in session.notes}  # state by note time
        self.assertIs(states[1200], NoteState.HIT)  # the close one was hit
        self.assertIs(states[1000], NoteState.PENDING)  # the far one waits

    def test_a_hit_note_is_not_offered_again(self):  # a used note stays used
        session = self.make_session((1000, 0))  # one note
        session.register_tap(0, tap_ms=1000.0)  # hit it
        self.assertIsNone(session.register_tap(0, tap_ms=1000.0))  # second press finds nothing

    def test_notes_in_other_lanes_are_untouched(self):  # other lanes keep their notes
        session = self.make_session((1000, 0), (1000, 3))  # same time, two lanes
        session.register_tap(0, tap_ms=1000.0)  # take lane 0's note
        by_lane = {note.lane: note.state for note in session.notes}  # state by lane
        self.assertIs(by_lane[0], NoteState.HIT)  # lane 0 hit
        self.assertIs(by_lane[3], NoteState.PENDING)  # lane 3 untouched

    def test_the_session_finishes_when_every_note_is_judged(self):  # the end of a run
        session = self.make_session((1000, 0), (1500, 1))  # two notes
        self.assertFalse(session.finished)  # not done yet
        session.update(5000.0)  # song walks past both
        self.assertTrue(session.finished)  # now finished

    def test_results_text_carries_the_headline_numbers(self):  # the results screen text
        session = self.make_session((1000, 0))  # one note
        session.register_tap(0, tap_ms=1000.0)  # hit it
        text = "\n".join(session.results_text())  # the lines joined
        self.assertIn("RANK", text)  # rank is in there
        self.assertIn("ACCURACY", text)  # accuracy too

    def test_lane_press_times_are_kept_for_the_flash(self):  # the lane flash data
        session = self.make_session((1000, 0))  # one note
        session.register_tap(0, tap_ms=980.0)  # a slightly early press
        self.assertEqual(session.last_press_song_ms[0], 980.0)  # the time is kept for the renderer


class LoggingTests(unittest.TestCase):  # the csv side
    def setUp(self):  # fresh temp dir per test
        self._tmp = tempfile.TemporaryDirectory()  # a throwaway folder
        self.path = Path(self._tmp.name) / "taps.csv"  # the log file in it

    def tearDown(self):  # clean up
        self._tmp.cleanup()  # gone

    def test_a_hit_writes_target_tap_and_error(self):  # a hit row has the full numbers
        with TapLog(path=self.path, calibration_ms=0.0) as log:  # the log open
            session = PlaySession(  # a session writing to it
                make_chart((1000, 0)),  # one note
                SongClock(ticks_provider=lambda: 0, mixer_pos_provider=lambda: -1),  # the frozen clock
                logger=log,  # log attached
            )  # session built
            session.register_tap(0, tap_ms=1090.0, mixer_pos_ms=990)  # hit 90 ms late
        rows = read_log(self.path)  # read the file back
        self.assertEqual(len(rows), 1)  # one data row
        self.assertEqual(rows[0]["target_ms"], "1000")  # the target
        self.assertEqual(rows[0]["tap_ms"], "1090")  # the tap
        self.assertEqual(rows[0]["error_ms"], "+90")  # the signed error
        self.assertEqual(rows[0]["verdict"], "GOOD")  # the verdict
        self.assertEqual(rows[0]["mixer_pos_ms"], "990")  # the mixer reading too

    def test_a_miss_is_logged_with_empty_tap_columns(self):  # a miss row is mostly empty
        with TapLog(path=self.path) as log:  # the log open
            session = PlaySession(  # a session
                make_chart((1000, 0)),  # one note
                SongClock(ticks_provider=lambda: 0, mixer_pos_provider=lambda: -1),  # frozen clock
                logger=log,  # log attached
            )  # session built
            session.update(9000.0)  # song walks past the note
        rows = read_log(self.path)  # read it back
        self.assertEqual(rows[0]["verdict"], "MISS")  # verdict says miss
        self.assertEqual(rows[0]["tap_ms"], "")  # no tap time
        self.assertEqual(rows[0]["error_ms"], "")  # no error either

    def test_every_note_gets_exactly_one_row(self):  # one row per note, whatever happened
        with TapLog(path=self.path) as log:  # log open
            session = PlaySession(  # three notes
                make_chart((1000, 0), (1500, 1), (2000, 2)),  # one per lane
                SongClock(ticks_provider=lambda: 0, mixer_pos_provider=lambda: -1),  # frozen clock
                logger=log,  # log attached
            )  # session built
            session.register_tap(0, tap_ms=1000.0)  # hit the first
            session.update(9000.0)  # miss the other two
        rows = read_log(self.path)  # read it back
        self.assertEqual(len(rows), 3)  # three rows
        self.assertEqual({row["note_index"] for row in rows}, {"0", "1", "2"})  # each note exactly once

    def test_the_header_records_the_calibration(self):  # the header notes the offset
        with TapLog(path=self.path, song="demo", calibration_ms=-42.0) as log:  # a run with a known offset
            pass  # close it straight away
        raw = self.path.read_text(encoding="utf-8")  # raw text this time
        self.assertIn("# song demo", raw)  # the song name is in there
        self.assertIn("# calibration_offset_ms -42", raw)  # and the offset

    def test_a_run_without_a_logger_does_not_crash(self):  # no logger must not crash
        session = PlaySession(  # a session with no log
            make_chart((1000, 0)),  # one note
            SongClock(ticks_provider=lambda: 0, mixer_pos_provider=lambda: -1),  # frozen clock
            logger=None,  # explicitly no logger
        )  # session built
        session.register_tap(0, tap_ms=1000.0)  # tap it
        session.update(9000.0)  # miss it


if __name__ == "__main__":  # run directly
    unittest.main()  # run the tests
