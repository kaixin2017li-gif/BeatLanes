"""Tests for the tap-to-metronome calibration."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from beatlanes import config  # noqa: E402
from beatlanes.calibration import (  # noqa: E402
    CalibrationRun,
    load_calibration,
    save_calibration,
)


class CalibrationRunTests(unittest.TestCase):
    def setUp(self):
        self.run = CalibrationRun(beats=8, beat_ms=500.0, tolerance_ms=150.0)

    def test_taps_land_on_the_clicks(self):
        self.assertEqual(self.run.beat_time_ms(3), 1500.0)
        self.assertEqual(self.run.nearest_beat_index(1520.0), 3)

    def test_a_tap_records_its_offset_from_the_click(self):
        offset = self.run.register_tap(1480.0)
        self.assertAlmostEqual(offset, -20.0)
        self.assertEqual(self.run.tap_count, 1)

    def test_a_tap_far_from_any_click_is_ignored(self):
        self.assertIsNone(self.run.register_tap(1700.0))
        self.assertEqual(self.run.tap_count, 0)
        self.assertEqual(self.run.skipped, 1)

    def test_a_tap_outside_the_run_is_ignored(self):
        self.assertIsNone(self.run.register_tap(9000.0))
        self.assertEqual(self.run.skipped, 1)

    def test_the_saved_value_is_the_median(self):
        # a distracted tap that is still inside the tolerance: the mean moves,
        # the median does not, which is why the median is what gets saved
        for offset in (10.0, 12.0, 8.0, 120.0):
            self.run.register_tap(offset)
        self.assertAlmostEqual(self.run.median_offset_ms, 11.0)
        self.assertGreater(self.run.mean_offset_ms, 30.0)
        self.assertAlmostEqual(self.run.offset_ms, 11.0)

    def test_spread_reports_consistency(self):
        for offset in (0.0, 0.0, 0.0):
            self.run.register_tap(offset)
        self.assertEqual(self.run.spread_ms, 0.0)

    def test_not_finished_until_enough_taps_arrive(self):
        # eight beats, so at least six have to land before the number is trusted
        self.assertFalse(self.run.finished)
        for offset in (-5.0, -4.0, -6.0, 0.0, 3.0):
            self.run.register_tap(offset)
        self.assertFalse(self.run.finished)
        self.run.register_tap(2.0)
        self.assertTrue(self.run.finished)

    def test_no_taps_means_no_offset(self):
        self.assertIsNone(self.run.offset_ms)
        self.assertIsNone(self.run.mean_offset_ms)
        self.assertIn("no usable taps", self.run.summary())

    def test_the_tolerance_has_to_stay_under_half_a_beat(self):
        # otherwise every tap is within tolerance of some click and the filter
        # does nothing at all
        self.assertLess(config.CALIBRATION_TOLERANCE_MS, config.CALIBRATION_BEAT_MS / 2.0)

    def test_beat_phase_runs_from_zero_to_one(self):
        self.assertAlmostEqual(self.run.beat_phase(0.0), 0.0)
        self.assertAlmostEqual(self.run.beat_phase(250.0), 0.5)
        self.assertAlmostEqual(self.run.beat_phase(500.0), 0.0)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "calibration.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_round_trip(self):
        save_calibration(-37.5, taps=14, path=self.path)
        self.assertAlmostEqual(load_calibration(self.path), -37.5)

    def test_saved_file_explains_itself(self):
        save_calibration(12.0, taps=16, path=self.path)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["measured_from_taps"], 16)
        self.assertIn("tick clock", payload["note"])

    def test_a_missing_file_means_no_offset(self):
        self.assertEqual(load_calibration(self.path), 0.0)

    def test_a_broken_file_means_no_offset(self):
        self.path.write_text("not json at all", encoding="utf-8")
        self.assertEqual(load_calibration(self.path), 0.0)

    def test_a_file_without_the_key_means_no_offset(self):
        self.path.write_text(json.dumps({"something": "else"}), encoding="utf-8")
        self.assertEqual(load_calibration(self.path), 0.0)


if __name__ == "__main__":
    unittest.main()
