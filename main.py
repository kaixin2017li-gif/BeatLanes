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
from pathlib import Path  # the flag types

# Allow "python main.py" from the repository root without installing anything.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from beatlanes import config  # the window constants
from beatlanes.app import BeatLanesApp  # the game itself
from beatlanes.chart import load_chart  # to read the chart file

# Timing errors, in ms, applied to each note in turn by --selftest. The list
# lands inside PERFECT, inside GOOD, and outside GOOD, covering all windows.
SELFTEST_ERROR_CYCLE = (0, 5, -5, 30, -40, 15, 60, -70, 0, 110, -115, 130, -125, 0, 10, -20)


def build_selftest_taps(chart) -> list[tuple[int, float]]:  # the prepared presses for --selftest
    # one tap per note, shifted by the error cycle
    taps: list[tuple[int, float]] = []  # built up here
    for position, note in enumerate(chart.notes):  # walk the notes in order
        error = SELFTEST_ERROR_CYCLE[position % len(SELFTEST_ERROR_CYCLE)]  # the error for this note
        taps.append((note.lane, note.time_ms + error))  # press its lane, offset in time
    return taps  # (lane, press time) pairs


def calibration_taps(bias_ms: float = 18.0) -> list[tuple[int, float]]:  # for the calibrate screenshot or recording
    # taps for the metronome screen, slightly off the beat on purpose, so a
    # recorded calibration shows an offset actually being measured
    from beatlanes.calibration import CalibrationRun  # imported here to keep app startup light

    run = CalibrationRun()  # knows the click layout
    return [(0, run.beat_time_ms(index) + bias_ms) for index in range(run.beats)]  # one tap per click


def expected_counts(note_count: int) -> dict[str, int]:  # the numbers --selftest compares against
    # what the session should produce, derived from the same window settings
    counts = {"perfect": 0, "good": 0, "miss": 0, "stray": 0}  # one bucket each
    for position in range(note_count):  # walk every note
        error = abs(SELFTEST_ERROR_CYCLE[position % len(SELFTEST_ERROR_CYCLE)])  # its planned error
        if error <= config.PERFECT_MS:  # inside PERFECT
            counts["perfect"] += 1  # count it
        elif error <= config.GOOD_MS:  # inside GOOD
            counts["good"] += 1  # count it
        else:  # outside both windows
            # too far from the note: the press becomes a stray tap and the note
            # is missed when the song passes it
            counts["miss"] += 1  # the note dies
            counts["stray"] += 1  # and the press counted as a stray
    return counts  # the expectation


def run_selftest(args) -> int:  # returns 0 on pass, 1 on fail
    # play a whole chart with prepared taps and check the outcome
    chart = load_chart(args.chart)  # the chart to play
    taps = build_selftest_taps(chart)  # the prepared presses
    app = BeatLanesApp(  # a silent headless app
        chart_path=args.chart,  # from the flags
        song_path=args.song,  # unused here, audio is off
        latency_offset_ms=args.offset if args.offset is not None else 0.0,  # tests run with offset 0
        enable_audio=False,  # headless, no sound
        simulated_taps=taps,  # the prepared presses  # the prepared presses
        log_path=args.log,  # where the CSV goes
    )  # app ready
    app.debug = args.debug  # overlay if asked
    app.run()  # play the chart
    report = app.selftest_report()  # what actually happened
    expected = expected_counts(chart.note_count)  # what should have happened

    print(f"selftest  chart '{report['chart']}'  {report['notes']} notes  {report['taps_fed']} taps fed")  # the header line
    if report["perfect"] is None:  # never reached the results screen
        print("SELFTEST FAILED: the run never reached the results screen")  # say why
        return 1  # failure

    print(f"{'':10} {'expected':>9} {'actual':>9}")  # the column headings
    problems = []  # collected while comparing
    for key in ("perfect", "good", "miss", "stray"):  # compare each count
        wanted = expected[key]  # from the window maths
        got = report[key]  # from the real run
        flag = "" if wanted == got else "   <-- differs"  # marks a mismatch in the printout
        if wanted != got:  # remember it
            problems.append(key)  # for the final verdict
        print(f"{key:10} {wanted:>9} {got:>9}{flag}")  # one row per count
    print(f"{'accuracy':10} {'':>9} {report['accuracy']:>8.1f}%")  # the accuracy row
    print(f"{'best combo':10} {'':>9} {report['best_combo']:>9}")  # the streak
    print(f"log       {report['log']}")  # where the csv went

    if problems:  # any mismatch fails the run
        print(f"SELFTEST FAILED: {', '.join(problems)} did not match")  # name the keys
        return 1  # failure
    print("SELFTEST PASSED")  # every count matched
    return 0  # success


def main(argv: list[str] | None = None) -> int:  # argv override for tests
    # the command line flags
    parser = argparse.ArgumentParser(  # the flag parser
        prog="beatlanes",  # the name in help text
        description="A four lane keyboard rhythm prototype: D F J K.",  # one line about the game
    )  # parser made
    parser.add_argument("--chart", type=Path, default=None, help="chart JSON (default: charts/beatlanes_120.json)")  # which chart file
    parser.add_argument("--song", type=Path, default=None, help="song file (default: assets/beatlanes_120.ogg)")  # which song file
    parser.add_argument("--offset", type=float, default=None, help="latency offset in ms (default: calibration.json)")  # overrides calibration.json
    parser.add_argument("--no-audio", action="store_true", help="run on the tick clock without opening the mixer")  # silent mode
    parser.add_argument("--log", type=Path, default=None, help="where to write the CSV tap log")  # where the csv goes
    parser.add_argument("--debug", action="store_true", help="start with the debug overlay visible")  # overlay on from the start
    parser.add_argument("--selftest", action="store_true", help="play a prepared run headlessly and check it")  # the headless check run
    parser.add_argument("--screenshot", type=Path, default=None, help="save one frame to this PNG and exit")  # capture one frame
    parser.add_argument("--at", type=float, default=12_000.0, help="song time for --screenshot, in ms")  # when to capture
    parser.add_argument(  # another flag
        "--shot-state",  # which screen --screenshot should capture
        choices=("title", "play", "results", "calibrate"),  # the four screens
        default="play",  # play is the usual shot
        help="which screen to capture or record",  # shown by --help
    )  # flag done
    parser.add_argument(  # another flag
        "--shot-taps",  # so the frame shows a real run, not an empty board
        action="store_true",  # a switch, no value
        help="feed the selftest taps while taking a screenshot",  # shown by --help
    )  # flag done
    parser.add_argument(  # another flag
        "--autoplay",  # the game plays itself, for demos and logs
        action="store_true",  # a switch, no value
        help="play the chart automatically",  # shown by --help
    )  # flag done
    parser.add_argument(  # another flag
        "--windowed",  # keep the real window even for an automatic run
        action="store_true",  # a switch, no value
        help="keep a real window and audio device even for an automatic run",  # shown by --help
    )  # flag done
    parser.add_argument(  # another flag
        "--record",  # write the run to an mp4
        type=Path,  # a path, not a string
        default=None,  # off by default
        help="record the run to this mp4 (needs ffmpeg on the path)",  # shown by --help
    )  # flag done
    parser.add_argument("--record-fps", type=int, default=60, help="frame rate for --record")  # footage frame rate
    parser.add_argument(  # another flag
        "--record-scale",  # 2 gives 1920x1280 footage from the 960x640 window
        type=int,  # whole number
        default=2,  # whole number
        help="pixel scale for --record",  # hd by default
    )  # shown by --help
    args = parser.parse_args(argv)  # flag done

    if args.selftest:  # the headless test run
        return run_selftest(args)  # the headless run, exit code decides

    # some modes need the prepared taps: autoplay shows a real run, results and
    # record need notes actually scored
    auto_taps = None  # the prepared presses, if this mode needs them
    if args.shot_state == "calibrate":  # the calibration screen uses its own taps
        auto_taps = calibration_taps()  # the metronome taps
    else:  # every other mode
        needs_taps = args.autoplay or args.shot_taps or (  # which modes want taps
            args.screenshot is not None and args.shot_state == "results"  # a results shot needs scored notes
        ) or args.record is not None  # recordings always do
        if needs_taps:  # build them once
            auto_taps = build_selftest_taps(load_chart(args.chart))  # the same error cycle as --selftest

    app = BeatLanesApp(  # the game, wired to the flags
        chart_path=args.chart,  # straight from the flags from here down
        song_path=args.song,  # same
        latency_offset_ms=args.offset,  # same
        enable_audio=not args.no_audio,  # flipped flag
        simulated_taps=auto_taps,  # may be None
        windowed=args.windowed,  # keep a window
        record_path=args.record,  # may be None
        record_fps=args.record_fps,  # footage rate
        record_scale=args.record_scale,  # hd factor
        screenshot_path=args.screenshot,  # may be None
        screenshot_at_ms=args.at,  # when to capture
        screenshot_state=args.shot_state,  # which screen
        log_path=args.log,  # may be None
    )  # app ready
    app.debug = args.debug  # overlay if asked
    return app.run()  # the game loop, its return is the exit code


if __name__ == "__main__":  # run the game when called directly
    raise SystemExit(main())  # the exit code reaches the shell
