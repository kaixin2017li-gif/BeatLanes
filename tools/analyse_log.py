#!/usr/bin/env python3
"""Read a tap log and report on the timing.

This is the tool behind the calibration step in the plan. A finished run writes
a CSV with one row per note, and the questions worth asking of it are:

    how did the judgements come out?
    what did the errors look like - a constant shift, or random scatter?
    were taps early or late, and by how much on average?
    did the mixer reading agree with the tick clock?

A constant shift is what the calibration offset is for: if every tap is 40 ms
late, nothing is wrong with the playing, the folder offset is wrong. Scatter
with no shift means the player, not the machine.

    python tools/analyse_log.py logs/taps-20260916-095210.csv
    python tools/analyse_log.py logs/taps-*.csv --plot docs/shots/error-histogram.png
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from beatlanes import config  # noqa: E402
from beatlanes.logbook import read_log  # noqa: E402


def load_rows(path: Path) -> list[dict[str, str]]:
    rows = read_log(path)
    if not rows:
        raise SystemExit(f"{path} has no rows")
    return rows


def errors_from(rows: list[dict[str, str]]) -> list[float]:
    return [float(row["error_ms"]) for row in rows if row.get("error_ms")]


def mixer_differences(rows: list[dict[str, str]]) -> list[float]:
    """tick clock song time minus the mixer reading, per tap.

    For a log written by real key presses this difference is the input and audio
    delay that the calibration offset has to absorb. For an automatic run the
    mixer is read on the frame the tap was released, so the figure carries up to
    one frame of the feed delay on top.
    """
    differences: list[float] = []
    for row in rows:
        if row.get("error_ms") and row.get("mixer_pos_ms"):
            differences.append(float(row["tap_ms"]) - float(row["mixer_pos_ms"]))
    return differences


def describe(values: list[float]) -> str:
    if not values:
        return "none"
    return (
        f"mean {statistics.fmean(values):+7.1f} ms   "
        f"median {statistics.median(values):+7.1f} ms   "
        f"spread {statistics.pstdev(values):5.1f} ms   "
        f"range {min(values):+.0f} to {max(values):+.0f} ms"
    )


def verdict_tally(rows: list[dict[str, str]]) -> dict[str, int]:
    tally = {"PERFECT": 0, "GOOD": 0, "MISS": 0}
    for row in rows:
        tally[row["verdict"]] = tally.get(row["verdict"], 0) + 1
    return tally


def print_report(path: Path, rows: list[dict[str, str]]) -> None:
    tally = verdict_tally(rows)
    errors = errors_from(rows)
    early = [value for value in errors if value < 0]
    late = [value for value in errors if value > 0]

    print(f"log        {path}")
    print(f"notes      {len(rows)}")
    print(
        f"verdicts   PERFECT {tally['PERFECT']}   GOOD {tally['GOOD']}   MISS {tally['MISS']}"
    )
    print()
    print(f"all taps   {describe(errors)}")
    print(f"early      {describe(early)}   ({len(early)} taps)")
    print(f"late       {describe(late)}   ({len(late)} taps)")

    if errors:
        mean = statistics.fmean(errors)
        median = statistics.median(errors)
        print()
        print(f"suggested calibration offset  {median:+.0f} ms  (median of the taps)")
        print(
            "  a large mean and median the same way round means the offset is "
            f"wrong, not the player. mean {mean:+.0f} ms against median {median:+.0f} ms"
        )

    differences = mixer_differences(rows)
    print()
    if differences:
        print(f"tick clock vs mixer        {describe(differences)}")
        print("  each figure is tap_ms - mixer_pos_ms for the same tap")
    else:
        print("tick clock vs mixer        no mixer readings in this log")
        print("  the mixer column is only filled when the music is actually playing")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyse a BeatLanes tap log.")
    parser.add_argument("logs", type=Path, nargs="+")
    parser.add_argument("--plot", type=Path, default=None, help="write an error histogram to this PNG")
    args = parser.parse_args()

    for path in args.logs:
        rows = load_rows(path)
        print_report(path, rows)
        print()

    if args.plot is not None and args.logs:
        rows = load_rows(args.logs[0])
        write_plot(errors_from(rows), args.plot, args.logs[0].name)
    return 0


def write_plot(errors: list[float], target: Path, title: str) -> None:
    """A histogram of the tap errors, with the judgement windows marked."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is not installed, so no plot was written")
        return

    if not errors:
        print("no scored taps in this log, so no plot was written")
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(figsize=(7.2, 3.6), dpi=140)
    span = max(200.0, max(abs(value) for value in errors) * 1.2)
    axes.hist(errors, bins=24, range=(-span, span), color="#4d7fd0", edgecolor="#1a2a44")
    for edge, colour, label in (
        (-config.GOOD_MS, "#e07070", f"GOOD -{config.GOOD_MS:.0f} ms"),
        (-config.PERFECT_MS, "#76e6be", f"PERFECT -{config.PERFECT_MS:.0f} ms"),
        (config.PERFECT_MS, "#76e6be", f"PERFECT +{config.PERFECT_MS:.0f} ms"),
        (config.GOOD_MS, "#e07070", f"GOOD +{config.GOOD_MS:.0f} ms"),
    ):
        axes.axvline(edge, color=colour, linewidth=1.2, linestyle="--", label=label)
    axes.axvline(0, color="#1a2a44", linewidth=1.0)
    axes.set_xlabel("tap error (ms)   negative = early, positive = late")
    axes.set_ylabel("notes")
    axes.set_title(f"BeatLanes tap errors - {title}")
    axes.legend(fontsize=7, frameon=False)
    figure.tight_layout()
    figure.savefig(target)
    print(f"wrote {target}")


if __name__ == "__main__":
    raise SystemExit(main())
