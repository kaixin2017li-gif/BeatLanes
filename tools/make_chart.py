#!/usr/bin/env python3
"""Write the chart JSON from the beat plan.

The chart is hand-made in the sense that the lanes and the bar patterns were
chosen by hand in beatplan.py; this script only turns those choices into the
file the game reads, so the note times cannot disagree with the song.

    python tools/make_chart.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from beatlanes import config  # noqa: E402
from tools import beatplan  # noqa: E402


def build_chart() -> dict:
    notes = [
        {"time": int(round(time_ms)), "lane": int(lane)}
        for time_ms, lane in beatplan.note_times()
    ]
    return {
        "title": "BeatLanes 120 (generated from the beat plan)",
        "bpm": beatplan.BPM,
        "bars": beatplan.BARS,
        "intro_bars": beatplan.INTRO_BARS,
        "note_count": len(notes),
        "generated_by": "tools/make_chart.py",
        "notes": notes,
    }


def main() -> int:
    chart = build_chart()
    config.CHART_DIR.mkdir(parents=True, exist_ok=True)
    target = config.CHART_PATH
    target.write_text(json.dumps(chart, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target}  ({chart['note_count']} notes, {chart['bars']} bars at {chart['bpm']:.0f} BPM)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
