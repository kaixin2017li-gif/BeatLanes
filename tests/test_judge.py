"""Tests for the judgement windows.

These are the numbers the whole game rests on, so the boundaries are tested on
both sides: exactly 50 ms has to be PERFECT, 50.001 ms has to be GOOD.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from beatlanes import config  # noqa: E402
from beatlanes.judge import (  # noqa: E402
    Judgement,
    Verdict,
    is_inside_good_window,
    judge_tap,
    verdict_for_error,
)


class VerdictTests(unittest.TestCase):
    def test_exact_hit_is_perfect(self):
        self.assertIs(verdict_for_error(0.0), Verdict.PERFECT)

    def test_perfect_window_edges_are_inclusive(self):
        self.assertIs(verdict_for_error(config.PERFECT_MS), Verdict.PERFECT)
        self.assertIs(verdict_for_error(-config.PERFECT_MS), Verdict.PERFECT)

    def test_just_outside_perfect_is_good(self):
        self.assertIs(verdict_for_error(config.PERFECT_MS + 0.001), Verdict.GOOD)
        self.assertIs(verdict_for_error(-(config.PERFECT_MS + 0.001)), Verdict.GOOD)

    def test_good_window_edges_are_inclusive(self):
        self.assertIs(verdict_for_error(config.GOOD_MS), Verdict.GOOD)
        self.assertIs(verdict_for_error(-config.GOOD_MS), Verdict.GOOD)

    def test_beyond_good_is_miss(self):
        self.assertIs(verdict_for_error(config.GOOD_MS + 0.001), Verdict.MISS)
        self.assertIs(verdict_for_error(-400.0), Verdict.MISS)

    def test_good_window_helper(self):
        self.assertTrue(is_inside_good_window(config.GOOD_MS))
        self.assertFalse(is_inside_good_window(config.GOOD_MS + 0.001))


class JudgeTapTests(unittest.TestCase):
    def test_error_is_tap_minus_target(self):
        judgement = judge_tap(tap_ms=1000.0, target_ms=1032.0)
        self.assertAlmostEqual(judgement.error_ms, -32.0)

    def test_early_tap_has_a_negative_error(self):
        self.assertTrue(judge_tap(900.0, 1000.0).early)

    def test_late_tap_is_not_early(self):
        self.assertFalse(judge_tap(1100.0, 1000.0).early)

    def test_verdict_comes_from_the_error(self):
        self.assertIs(judge_tap(1010.0, 1000.0).verdict, Verdict.PERFECT)
        self.assertIs(judge_tap(1090.0, 1000.0).verdict, Verdict.GOOD)
        self.assertIs(judge_tap(1400.0, 1000.0).verdict, Verdict.MISS)

    def test_offset_text_reads_the_sign(self):
        self.assertEqual(judge_tap(968.0, 1000.0).offset_text, "-32 ms early")
        self.assertEqual(judge_tap(1020.0, 1000.0).offset_text, "+20 ms late")

    def test_judgement_is_immutable(self):
        judgement = Judgement(error_ms=10.0, verdict=Verdict.PERFECT)
        with self.assertRaises(Exception):
            judgement.error_ms = 20.0  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
