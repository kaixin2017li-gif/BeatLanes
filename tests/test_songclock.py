"""Tests for the song clock.

The tick and mixer readings are supplied by small stand-in functions, so this
runs without a sound card and without waiting for real time to pass.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from beatlanes.songclock import SongClock  # noqa: E402


class SongClockTests(unittest.TestCase):
    def setUp(self):
        self.state = {"ticks": 1000, "mixer": -1}
        self.clock = SongClock(
            ticks_provider=lambda: self.state["ticks"],
            mixer_pos_provider=lambda: self.state["mixer"],
        )

    def test_before_start_the_song_is_at_zero(self):
        self.assertFalse(self.clock.running)
        self.assertEqual(self.clock.song_time_ms(), 0.0)

    def test_song_time_is_ticks_since_the_music_started(self):
        self.clock.start()
        self.state["ticks"] = 3500
        self.assertEqual(self.clock.song_time_ms(), 2500.0)

    def test_start_can_be_pinned_to_a_supplied_tick(self):
        self.clock.start(at_ticks=5000)
        self.state["ticks"] = 6000
        self.assertEqual(self.clock.song_time_ms(), 1000.0)

    def test_offset_is_subtracted_from_song_time(self):
        self.clock.latency_offset = 80.0
        self.clock.start()
        self.state["ticks"] = 2000
        self.assertEqual(self.clock.song_time_ms(), 920.0)

    def test_offset_can_be_changed_after_a_calibration_run(self):
        self.clock.start()
        self.clock.latency_offset = -25.0
        self.state["ticks"] = 2000
        self.assertEqual(self.clock.song_time_ms(), 1025.0)

    def test_mixer_minus_one_means_no_reading(self):
        self.assertEqual(self.clock.mixer_position_ms(), None)
        self.assertIsNone(self.clock.drift_ms())

    def test_mixer_reading_is_passed_through(self):
        self.state["mixer"] = 1500
        self.assertEqual(self.clock.mixer_position_ms(), 1500)

    def test_drift_is_the_difference_between_the_two_clocks(self):
        self.clock.start()
        self.state["ticks"] = 4000
        self.state["mixer"] = 2940
        self.assertAlmostEqual(self.clock.drift_ms(), 60.0)

    def test_sample_keeps_both_readings_together(self):
        self.clock.start()
        self.state["ticks"] = 3000
        self.state["mixer"] = 1990
        song_ms, position = self.clock.sample()
        self.assertEqual(song_ms, 2000.0)
        self.assertEqual(position, 1990)
        self.assertEqual(self.clock.samples, [(2000.0, 1990)])

    def test_starting_again_clears_old_samples(self):
        self.clock.start()
        self.clock.sample()
        self.clock.start()
        self.assertEqual(self.clock.samples, [])

    def test_a_broken_mixer_provider_does_not_crash_the_game(self):
        def explode() -> int:
            raise RuntimeError("mixer went away")

        clock = SongClock(ticks_provider=lambda: 0, mixer_pos_provider=explode)
        self.assertIsNone(clock.mixer_position_ms())

    def test_stop_puts_the_clock_back_to_zero(self):
        self.clock.start()
        self.state["ticks"] = 9000
        self.clock.stop()
        self.assertEqual(self.clock.song_time_ms(), 0.0)


if __name__ == "__main__":
    unittest.main()
