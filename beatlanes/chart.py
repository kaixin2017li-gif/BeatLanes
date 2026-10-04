# Load the chart. a chart will be in json format with a title, bpm and array of notes
# lanes and time (ms). verify everything here so we know our chart is valid

from __future__ import annotations

import json  # charts will be saved as json
from dataclasses import dataclass  # create attributes for the note and chart classes
from pathlib import Path

from . import config  # number of lanes and paths


class ChartError(ValueError):  # error to raise if chart is not valid
    pass


@dataclass(frozen=True)
class ChartNote:  # one note with what lane it's on and when it needs to hit the line
    index: int  # it's order in the song
    lane: int  # should be a value between 0-3. D F J K
    time_ms: int  # when it needs to be hit in song ms


@dataclass(frozen=True)
class Chart:  # contains all of the notes. should be in play order
    title: str  # used for title screen and hud
    bpm: float  # will be used for beat grid
    notes: tuple[ChartNote, ...]  # list of all notes. from earliest to latest

    @property
    def note_count(self) -> int:  # number of notes
        return len(self.notes)

    @property
    def length_ms(self) -> int:  # when the final note should be hit
        return max((note.time_ms for note in self.notes), default=0)

    @property
    def lane_counts(self) -> tuple[int, ...]:  # list of how many notes in each lane
        counts = [0] * config.LANE_COUNT
        for note in self.notes:  # add all notes to there lane
            counts[note.lane] += 1
        return tuple(counts)


def load_chart(path: Path | str | None = None) -> Chart:
    # open chart and verify all notes are valid and return chart
    path = Path(path) if path is not None else config.CHART_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))  # json load
    except FileNotFoundError as exc:  # file does not exist
        raise ChartError(f"chart file not found: {path}") from exc
    except json.JSONDecodeError as exc:  # malformed json
        raise ChartError(f"{path.name} is not valid JSON: {exc}") from exc

    entries = raw.get("notes")  # list of notes
    if not isinstance(entries, list) or not entries:  # needs to be a list and not empty
        raise ChartError(f"{path.name} contains no notes")

    collected: list[tuple[int, int]] = []  # (time, lane) pairs, sorted later
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):  # needs to be an object
            raise ChartError(f"note {position} is not an object")
        try:
            lane = int(entry["lane"])  # what lane it's on
            time_ms = int(entry["time"])  # when to be hit
        except (KeyError, TypeError, ValueError) as exc:
            raise ChartError(f"note {position} needs an int 'lane' and 'time'") from exc
        if not 0 <= lane < config.LANE_COUNT:  # lane must be valid
            raise ChartError(f"note {position}: lane {lane} is outside 0-{config.LANE_COUNT - 1}")
        if time_ms < 0:  # time cant be less than 0
            raise ChartError(f"note {position}: negative time {time_ms}")
        collected.append((time_ms, lane))

    # place notes in play order from earliest to latest. if a note is at the same ms place them by lane this will keep the order of our logs constant
    collected.sort()
    notes = tuple(
        ChartNote(index=index, lane=lane, time_ms=time_ms)
        for index, (time_ms, lane) in enumerate(collected)
    )
    return Chart(
        title=str(raw.get("title", path.stem)),  # default to the name of the file
        bpm=float(raw.get("bpm", 120)),  # beat grid
        notes=notes,
    )
