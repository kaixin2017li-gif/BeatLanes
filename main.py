#!/usr/bin/env python3
"""BeatLanes - entry point.

Normal use:

    python main.py

Headless modes used while building and testing:

    python main.py --selftest
    python main.py --screenshot docs/shots/play.png --at 14000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow "python main.py" from the repository root without installing anything.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from beatlanes import config  # noqa: E402
from beatlanes.app import BeatLanesApp  # noqa: E402
from beatlanes.chart import load_chart  # noqa: E402

# Timing errors, in milliseconds, applied to each note in turn by --selftest.
# Three cycles of this list cover the generated chart exactly, and between them
# the values land inside PERFECT, inside GOOD, and outside GOOD.
SELFTEST_ERROR_CYCLE = (0, 5, -5, 30, -40, 15, 60, -70, 0, 110, -115, 130, -125, 0, 10, -20)


def build_selftest_taps(chart) -> list[tuple[int, float]]:
    """One tap per note, shifted by the error cycle."""
    taps: list[tuple[int, float]] = []
    for position, note in enumerate(chart.notes):
        error = SELFTEST_ERROR_CYCLE[position % len(SELFTEST_ERROR_CYCLE)]
        taps.append((note.lane, note.time_ms + error))
    return taps


def calibration_taps(bias_ms: float = 18.0) -> list[tuple[int, float]]:
    """Taps for the metronome test, a little off the beat.

    A small constant bias is deliberate: the point of recording the calibration
    screen is to show an offset being measured, and an offset of zero would not
    do that.
    """
    from beatlanes.calibration import CalibrationRun

    run = CalibrationRun()
    return [(0, run.beat_time_ms(index) + bias_ms) for index in range(run.beats)]


def expected_counts(note_count: int) -> dict[str, int]:
    """What the session should produce, derived from the same window settings."""
    counts = {"perfect": 0, "good": 0, "miss": 0, "stray": 0}
    for position in range(note_count):
        error = abs(SELFTEST_ERROR_CYCLE[position % len(SELFTEST_ERROR_CYCLE)])
        if error <= config.PERFECT_MS:
            counts["perfect"] += 1
        elif error <= config.GOOD_MS:
            counts["good"] += 1
        else:
            # too far from the note: the press becomes a stray tap and the note
            # is missed when the song passes it
            counts["miss"] += 1
            counts["stray"] += 1
    return counts


def run_selftest(args) -> int:
    """Play a whole chart with prepared taps and check the outcome."""
    chart = load_chart(args.chart)
    taps = build_selftest_taps(chart)
    app = BeatLanesApp(
        chart_path=args.chart,
        song_path=args.song,
        latency_offset_ms=args.offset if args.offset is not None else 0.0,
        enable_audio=False,
        simulated_taps=taps,
        log_path=args.log,
    )
    app.debug = args.debug
    app.run()
    report = app.selftest_report()
    expected = expected_counts(chart.note_count)

    print(f"selftest  chart '{report['chart']}'  {report['notes']} notes  {report['taps_fed']} taps fed")
    if report["perfect"] is None:
        print("SELFTEST FAILED: the run never reached the results screen")
        return 1

    print(f"{'':10} {'expected':>9} {'actual':>9}")
    problems = []
    for key in ("perfect", "good", "miss", "stray"):
        wanted = expected[key]
        got = report[key]
        flag = "" if wanted == got else "   <-- differs"
        if wanted != got:
            problems.append(key)
        print(f"{key:10} {wanted:>9} {got:>9}{flag}")
    print(f"{'accuracy':10} {'':>9} {report['accuracy']:>8.1f}%")
    print(f"{'best combo':10} {'':>9} {report['best_combo']:>9}")
    print(f"log       {report['log']}")

    if problems:
        print(f"SELFTEST FAILED: {', '.join(problems)} did not match")
        return 1
    print("SELFTEST PASSED")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="beatlanes",
        description="A four lane keyboard rhythm prototype: D F J K.",
    )
    parser.add_argument("--chart", type=Path, default=None, help="chart JSON (default: charts/beatlanes_120.json)")
    parser.add_argument("--song", type=Path, default=None, help="song file (default: assets/beatlanes_120.ogg)")
    parser.add_argument("--offset", type=float, default=None, help="latency offset in ms (default: calibration.json)")
    parser.add_argument("--no-audio", action="store_true", help="run on the tick clock without opening the mixer")
    parser.add_argument("--log", type=Path, default=None, help="where to write the CSV tap log")
    parser.add_argument("--debug", action="store_true", help="start with the debug overlay visible")
    parser.add_argument("--selftest", action="store_true", help="play a prepared run headlessly and check it")
    parser.add_argument("--screenshot", type=Path, default=None, help="save one frame to this PNG and exit")
    parser.add_argument("--at", type=float, default=12_000.0, help="song time for --screenshot, in ms")
    parser.add_argument(
        "--shot-state",
        choices=("title", "play", "results", "calibrate"),
        default="play",
        help="which screen to capture or record",
    )
    parser.add_argument(
        "--shot-taps",
        action="store_true",
        help="feed the selftest taps while taking a screenshot, so the frame shows a real run",
    )
    parser.add_argument(
        "--autoplay",
        action="store_true",
        help="play the chart automatically: useful for a demo run, and for collecting a real tap log",
    )
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="keep a real window and audio device even for an automatic run",
    )
    parser.add_argument(
        "--record",
        type=Path,
        default=None,
        help="record the run to this mp4 (needs ffmpeg on the path)",
    )
    parser.add_argument("--record-fps", type=int, default=60, help="frame rate for --record")
    parser.add_argument(
        "--record-scale",
        type=int,
        default=2,
        help="pixel scale for --record; 2 gives 1920x1280 footage from the 960x640 window",
    )
    args = parser.parse_args(argv)

    if args.selftest:
        return run_selftest(args)

    auto_taps = None
    if args.shot_state == "calibrate":
        auto_taps = calibration_taps()
    else:
        needs_taps = args.autoplay or args.shot_taps or (
            args.screenshot is not None and args.shot_state == "results"
        ) or args.record is not None
        if needs_taps:
            auto_taps = build_selftest_taps(load_chart(args.chart))

    app = BeatLanesApp(
        chart_path=args.chart,
        song_path=args.song,
        latency_offset_ms=args.offset,
        enable_audio=not args.no_audio,
        simulated_taps=auto_taps,
        windowed=args.windowed,
        record_path=args.record,
        record_fps=args.record_fps,
        record_scale=args.record_scale,
        screenshot_path=args.screenshot,
        screenshot_at_ms=args.at,
        screenshot_state=args.shot_state,
        log_path=args.log,
    )
    app.debug = args.debug
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
