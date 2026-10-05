# Load the chart. a chart will be in json format with a title, bpm and array of notes
# lanes and time (ms). verify everything here so we know our chart is valid

from __future__ import annotations

import json  # charts will be saved as json
from dataclasses import dataclass  # create attributes for the note and chart classes
from pathlib import Path  # charts live on disk

from . import config  # number of lanes and paths


class ChartError(ValueError):  # error to raise if chart is not valid
    pass  # no extra behaviour, the name is the point


@dataclass(frozen=True)  # frozen so a loaded chart can't be mutated by accident
class ChartNote:  # one note with what lane it's on and when it needs to hit the line
    index: int  # it's order in the song
    lane: int  # should be a value between 0-3. D F J K
    time_ms: int  # when it needs to be hit in song ms


@dataclass(frozen=True)  # same freeze rule as ChartNote, charts are read only once loaded
class Chart:  # contains all of the notes. should be in play order
    title: str  # used for title screen and hud
    bpm: float  # will be used for beat grid
    notes: tuple[ChartNote, ...]  # list of all notes. from earliest to latest

    @property  # reads like a value
    def note_count(self) -> int:  # number of notes
        return len(self.notes)  # just the list length

    @property  # another read-only value
    def length_ms(self) -> int:  # when the final note should be hit
        return max((note.time_ms for note in self.notes), default=0)  # last note time, zero if the chart is empty

    @property  # and again, same reason as the last two
    def lane_counts(self) -> tuple[int, ...]:  # list of how many notes in each lane
        counts = [0] * config.LANE_COUNT  # one counter per lane, all starting at zero
        for note in self.notes:  # add all notes to there lane
            counts[note.lane] += 1  # bump this note's lane
        return tuple(counts)  # tuple so callers can't shuffle it


def load_chart(path: Path | str | None = None) -> Chart:  # the only way in, everything gets verified here
    # open chart and verify all notes are valid and return chart
    path = Path(path) if path is not None else config.CHART_PATH  # default chart comes from config
    try:  # the file might not exist or might not be json
        raw = json.loads(path.read_text(encoding="utf-8"))  # json load
    except FileNotFoundError as exc:  # file does not exist
        raise ChartError(f"chart file not found: {path}") from exc  # say which file
    except json.JSONDecodeError as exc:  # malformed json
        raise ChartError(f"{path.name} is not valid JSON: {exc}") from exc  # say what actually broke

    entries = raw.get("notes")  # list of notes
    if not isinstance(entries, list) or not entries:  # needs to be a list and not empty
        raise ChartError(f"{path.name} contains no notes")  # nothing to play, refuse early

    collected: list[tuple[int, int]] = []  # (time, lane) pairs, sorted later
    for position, entry in enumerate(entries):  # position only exists for the error messages
        if not isinstance(entry, dict):  # needs to be an object
            raise ChartError(f"note {position} is not an object")  # a string or number on its own is not a note
        try:  # lane and time both need to be ints
            lane = int(entry["lane"])  # what lane it's on
            time_ms = int(entry["time"])  # when to be hit
        except (KeyError, TypeError, ValueError) as exc:  # a missing key or a float value both land here
            raise ChartError(f"note {position} needs an int 'lane' and 'time'") from exc  # stop at the first bad note, say which one
        if not 0 <= lane < config.LANE_COUNT:  # lane must be valid
            raise ChartError(f"note {position}: lane {lane} is outside 0-{config.LANE_COUNT - 1}")  # a lane outside 0-3 would crash the renderer later
        if time_ms < 0:  # time cant be less than 0
            raise ChartError(f"note {position}: negative time {time_ms}")  # times only move forward
        collected.append((time_ms, lane))  # valid, keep it for the sort

    # place notes in play order from earliest to latest. if a note is at the same ms place them by lane this will keep the order of our logs constant
    collected.sort()
    notes = tuple(  # rebuild as frozen ChartNotes with fresh indexes
        ChartNote(index=index, lane=lane, time_ms=time_ms)  # index follows the sorted order
        for index, (time_ms, lane) in enumerate(collected)  # enumerate hands out the new indexes
    )  # done building
    return Chart(  # bundle it all up
        title=str(raw.get("title", path.stem)),  # default to the name of the file
        bpm=float(raw.get("bpm", 120)),  # beat grid
        notes=notes,  # the sorted tuple from above
    )  # the sorted tuple from above
