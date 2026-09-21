"""Tests for combo, score and accuracy."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from beatlanes import config  # noqa: E402
from beatlanes.judge import Verdict  # noqa: E402
from beatlanes.scoring import Score  # noqa: E402


class ScoreTests(unittest.TestCase):
    def test_a_perfect_note_is_full_points(self):
        score = Score(1)
        score.register(Verdict.PERFECT)
        self.assertEqual(score.points, config.POINTS_PERFECT)
        self.assertEqual(score.accuracy, 100.0)

    def test_a_good_note_is_half_points(self):
        score = Score(1)
        score.register(Verdict.GOOD)
        self.assertEqual(score.points, config.POINTS_GOOD)
        self.assertEqual(score.accuracy, 50.0)

    def test_a_miss_scores_nothing(self):
        score = Score(1)
        score.register(Verdict.MISS)
        self.assertEqual(score.points, 0)
        self.assertEqual(score.accuracy, 0.0)

    def test_combo_counts_consecutive_hits(self):
        score = Score(4)
        score.register(Verdict.PERFECT)
        score.register(Verdict.GOOD)
        self.assertEqual(score.combo, 2)

    def test_a_miss_resets_the_combo_but_keeps_the_best(self):
        score = Score(4)
        for _ in range(3):
            score.register(Verdict.PERFECT)
        score.register(Verdict.MISS)
        self.assertEqual(score.combo, 0)
        self.assertEqual(score.best_combo, 3)

    def test_early_and_late_taps_are_counted(self):
        score = Score(3)
        score.register(Verdict.PERFECT, early=True)
        score.register(Verdict.GOOD, early=False)
        score.register(Verdict.MISS)
        self.assertEqual(score.early_taps, 1)
        self.assertEqual(score.late_taps, 1)

    def test_stray_taps_are_counted_separately(self):
        score = Score(1)
        score.register_stray()
        score.register_stray()
        self.assertEqual(score.stray_taps, 2)
        self.assertEqual(score.judged, 0)

    def test_progress_and_completion(self):
        score = Score(3)
        self.assertEqual(score.remaining, 3)
        self.assertFalse(score.finished)
        for _ in range(3):
            score.register(Verdict.PERFECT)
        self.assertTrue(score.finished)
        self.assertEqual(score.remaining, 0)

    def test_accuracy_over_a_mixed_run(self):
        # 21 perfect, 21 good, 6 miss out of 48 notes
        score = Score(48)
        for _ in range(21):
            score.register(Verdict.PERFECT)
        for _ in range(21):
            score.register(Verdict.GOOD)
        for _ in range(6):
            score.register(Verdict.MISS)
        self.assertAlmostEqual(score.accuracy, 65.625, places=3)

    def test_rank_thresholds(self):
        cases = [(48, 48, "S"), (45, 48, "A"), (40, 48, "B"), (33, 48, "C"), (10, 48, "D")]
        for perfect, total, expected in cases:
            score = Score(total)
            for _ in range(perfect):
                score.register(Verdict.PERFECT)
            for _ in range(total - perfect):
                score.register(Verdict.MISS)
            self.assertEqual(score.rank, expected, f"{perfect}/{total}")

    def test_an_empty_chart_does_not_divide_by_zero(self):
        score = Score(0)
        self.assertEqual(score.accuracy, 0.0)
        self.assertTrue(score.finished)

    def test_summary_mentions_the_totals(self):
        score = Score(2)
        score.register(Verdict.PERFECT)
        score.register(Verdict.MISS)
        summary = score.summary()
        self.assertIn("PERFECT 1", summary)
        self.assertIn("MISS 1", summary)


if __name__ == "__main__":
    unittest.main()
