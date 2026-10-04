# Chart loading. A chart is a JSON file: title, bpm, and a list of notes
# (lane + time in ms). Everything is checked here so the game can trust it.

from __future__ import annotations

import json  # charts are stored as JSON
from dataclasses import dataclass  # gives the note/chart classes their fields
from pathlib import Path

from . import config  # lane count and default paths


class ChartError(ValueError):  # raised when a chart file cannot be trusted
    pass


@dataclass(frozen=True)
class ChartNote:  # one note: which lane, and when it should reach the line
    index: int  # position in play order
    lane: int  # 0..3, i.e. D F J K
    time_ms: int  # target time in song milliseconds


@dataclass(frozen=True)
class Chart:  # a whole chart, notes already in play order
    title: str  # shown on the title screen and in the HUD
    bpm: float  # used for the beat grid
    notes: tuple[ChartNote, ...]  # the notes, earliest first

    @property
    def note_count(self) -> int:  # how many notes the chart holds
        return len(self.notes)

    @property
    def length_ms(self) -> int:  # target time of the last note
        return max((note.time_ms for note in self.notes), default=0)

    @property
    def lane_counts(self) -> tuple[int, ...]:  # notes per lane, in lane order
        counts = [0] * config.LANE_COUNT
        for note in self.notes:  # tally each note into its lane
            counts[note.lane] += 1
        return tuple(counts)


def load_chart(path: Path | str | None = None) -> Chart:
    # read a chart file, check every note, and return it
    path = Path(path) if path is not None else config.CHART_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))  # parse the JSON
    except FileNotFoundError as exc:  # no such file
        raise ChartError(f"chart file not found: {path}") from exc
    except json.JSONDecodeError as exc:  # broken JSON
        raise ChartError(f"{path.name} is not valid JSON: {exc}") from exc

    entries = raw.get("notes")  # the note list
    if not isinstance(entries, list) or not entries:  # must be a non-empty list
        raise ChartError(f"{path.name} contains no notes")

    collected: list[tuple[int, int]] = []  # (time, lane) pairs, sorted later
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):  # each note must be an object
            raise ChartError(f"note {position} is not an object")
        try:
            lane = int(entry["lane"])  # which lane
            time_ms = int(entry["time"])  # when it should be hit
        except (KeyError, TypeError, ValueError) as exc:
            raise ChartError(f"note {position} needs an int 'lane' and 'time'") from exc
        if not 0 <= lane < config.LANE_COUNT:  # lane must exist
            raise ChartError(f"note {position}: lane {lane} is outside 0-{config.LANE_COUNT - 1}")
        if time_ms < 0:  # times cannot be negative
            raise ChartError(f"note {position}: negative time {time_ms}")
        collected.append((time_ms, lane))

    # Play order: earliest first. Same-moment notes order by lane, so the log
    # always lists them the same way.
    collected.sort()
    notes = tuple(
        ChartNote(index=index, lane=lane, time_ms=time_ms)
        for index, (time_ms, lane) in enumerate(collected)
    )
    return Chart(
        title=str(raw.get("title", path.stem)),  # fall back to the file name
        bpm=float(raw.get("bpm", 120)),  # for the beat grid
        notes=notes,
    )
