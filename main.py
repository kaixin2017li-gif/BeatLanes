#!/usr/bin/env python3
# Entry point of the BeatLanes prototype.

# This shows the normal way to run the program:
#   python main.py
# These are used while building and testing:
#   python main.py --selftest
#   python main.py --screenshot docs/shots/play.png --at 14000

from __future__ import annotations

import argparse  # the command line flags
import sys  # so the package can be found when run from the repo root
from pathlib import Path

# Allow "python main.py" from the repository root without installing anything.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from beatlanes import config  # the window constants
from beatlanes.app import BeatLanesApp  # the game itself
from beatlanes.chart import load_chart  # to read the chart file

# Timing errors, in ms, applied to each note in turn by --selftest. The list
# lands inside PERFECT, inside GOOD, and outside GOOD, covering all windows.
SELFTEST_ERROR_CYCLE = (0, 5, -5, 30, -40, 15, 60, -70, 0, 110, -115, 130, -125, 0, 10, -20)


def build_selftest_taps(chart) -> list[tuple[int, float]]:
    # one tap per note, shifted by the error cycle
    taps: list[tuple[int, float]] = []
    for position, note in enumerate(chart.notes):  # walk the notes in order
        error = SELFTEST_ERROR_CYCLE[position % len(SELFTEST_ERROR_CYCLE)]  # the error for this note
        taps.append((note.lane, note.time_ms + error))  # press its lane, offset in time
    return taps


def calibration_taps(bias_ms: float = 18.0) -> list[tuple[int, float]]:
    # taps for the metronome screen, slightly off the beat on purpose, so a
    # recorded calibration shows an offset actually being measured
    from beatlanes.calibration import CalibrationRun  # imported here to keep app startup light

    run = CalibrationRun()  # knows the click layout
    return [(0, run.beat_time_ms(index) + bias_ms) for index in range(run.beats)]  # one tap per click


def expected_counts(note_count: int) -> dict[str, int]:
    # what the session should produce, derived from the same window settings
    counts = {"perfect": 0, "good": 0, "miss": 0, "stray": 0}
    for position in range(note_count):  # walk every note
        error = abs(SELFTEST_ERROR_CYCLE[position % len(SELFTEST_ERROR_CYCLE)])  # its planned error
        if error <= config.PERFECT_MS:  # inside PERFECT
            counts["perfect"] += 1
        elif error <= config.GOOD_MS:  # inside GOOD
            counts["good"] += 1
        else:
            # too far from the note: the press becomes a stray tap and the note
            # is missed when the song passes it
            counts["miss"] += 1
            counts["stray"] += 1
    return counts


def run_selftest(args) -> int:
    # play a whole chart with prepared taps and check the outcome
    chart = load_chart(args.chart)  # the chart to play
    taps = build_selftest_taps(chart)  # the prepared presses
    app = BeatLanesApp(
        chart_path=args.chart,
        song_path=args.song,
        latency_offset_ms=args.offset if args.offset is not None else 0.0,  # tests run with offset 0
        enable_audio=False,  # headless, no sound
        simulated_taps=taps,  # the prepared presses
        log_path=args.log,  # where the CSV goes
    )
    app.debug = args.debug
    app.run()  # play the chart
    report = app.selftest_report()  # what actually happened
    expected = expected_counts(chart.note_count)  # what should have happened

    print(f"selftest  chart '{report['chart']}'  {report['notes']} notes  {report['taps_fed']} taps fed")
    if report["perfect"] is None:  # never reached the results screen
        print("SELFTEST FAILED: the run never reached the results screen")
        return 1

    print(f"{'':10} {'expected':>9} {'actual':>9}")
    problems = []
    for key in ("perfect", "good", "miss", "stray"):  # compare each count
        wanted = expected[key]
        got = report[key]
        flag = "" if wanted == got else "   <-- differs"
        if wanted != got:
            problems.append(key)
        print(f"{key:10} {wanted:>9} {got:>9}{flag}")
    print(f"{'accuracy':10} {'':>9} {report['accuracy']:>8.1f}%")
    print(f"{'best combo':10} {'':>9} {report['best_combo']:>9}")
    print(f"log       {report['log']}")

    if problems:  # any mismatch fails the run
        print(f"SELFTEST FAILED: {', '.join(problems)} did not match")
        return 1
    print("SELFTEST PASSED")
    return 0


def main(argv: list[str] | None = None) -> int:
    # the command line flags
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
        "--shot-state",  # which screen --screenshot should capture
        choices=("title", "play", "results", "calibrate"),
        default="play",
        help="which screen to capture or record",
    )
    parser.add_argument(
        "--shot-taps",  # so the frame shows a real run, not an empty board
        action="store_true",
        help="feed the selftest taps while taking a screenshot",
    )
    parser.add_argument(
        "--autoplay",  # the game plays itself, for demos and logs
        action="store_true",
        help="play the chart automatically",
    )
    parser.add_argument(
        "--windowed",  # keep the real window even for an automatic run
        action="store_true",
        help="keep a real window and audio device even for an automatic run",
    )
    parser.add_argument(
        "--record",  # write the run to an mp4
        type=Path,
        default=None,
        help="record the run to this mp4 (needs ffmpeg on the path)",
    )
    parser.add_argument("--record-fps", type=int, default=60, help="frame rate for --record")
    parser.add_argument(
        "--record-scale",  # 2 gives 1920x1280 footage from the 960x640 window
        type=int,
        default=2,
        help="pixel scale for --record",
    )
    args = parser.parse_args(argv)

    if args.selftest:  # the headless test run
        return run_selftest(args)

    # some modes need the prepared taps: autoplay shows a real run, results and
    # record need notes actually scored
    auto_taps = None
    if args.shot_state == "calibrate":  # the calibration screen uses its own taps
        auto_taps = calibration_taps()
    else:
        needs_taps = args.autoplay or args.shot_taps or (
            args.screenshot is not None and args.shot_state == "results"
        ) or args.record is not None
        if needs_taps:
            auto_taps = build_selftest_taps(load_chart(args.chart))

    app = BeatLanesApp(  # the game, wired to the flags
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


if __name__ == "__main__":  # run the game when called directly
    raise SystemExit(main())
