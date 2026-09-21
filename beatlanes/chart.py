"""Loading and checking hand-made charts.

A chart is a small JSON file: a title, the tempo, and a list of notes with a
lane and a target time in milliseconds. The times are measured from the start
of the song, which is the same clock the game uses while playing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import config


class ChartError(ValueError):
    """Raised when a chart file cannot be trusted."""


@dataclass(frozen=True)
class ChartNote:
    """One note: which lane, and when it should reach the judgement line."""

    index: int
    lane: int
    time_ms: int


@dataclass(frozen=True)
class Chart:
    """A whole chart, with its notes in play order."""

    title: str
    bpm: float
    notes: tuple[ChartNote, ...]

    @property
    def note_count(self) -> int:
        return len(self.notes)

    @property
    def length_ms(self) -> int:
        """Target time of the last note."""
        return max((note.time_ms for note in self.notes), default=0)

    @property
    def lane_counts(self) -> tuple[int, ...]:
        """How many notes each lane holds, in lane order."""
        counts = [0] * config.LANE_COUNT
        for note in self.notes:
            counts[note.lane] += 1
        return tuple(counts)


def load_chart(path: Path | str | None = None) -> Chart:
    """Read a chart file and return it, or raise ChartError."""
    path = Path(path) if path is not None else config.CHART_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ChartError(f"chart file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ChartError(f"{path.name} is not valid JSON: {exc}") from exc

    entries = raw.get("notes")
    if not isinstance(entries, list) or not entries:
        raise ChartError(f"{path.name} contains no notes")

    collected: list[tuple[int, int]] = []
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ChartError(f"note {position} is not an object")
        try:
            lane = int(entry["lane"])
            time_ms = int(entry["time"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ChartError(f"note {position} needs an int 'lane' and 'time'") from exc
        if not 0 <= lane < config.LANE_COUNT:
            raise ChartError(f"note {position}: lane {lane} is outside 0-{config.LANE_COUNT - 1}")
        if time_ms < 0:
            raise ChartError(f"note {position}: negative time {time_ms}")
        collected.append((time_ms, lane))

    # Play order: earliest first. Two notes at the same moment are ordered by
    # lane, so the CSV log always lists them the same way.
    collected.sort()
    notes = tuple(
        ChartNote(index=index, lane=lane, time_ms=time_ms)
        for index, (time_ms, lane) in enumerate(collected)
    )
    return Chart(
        title=str(raw.get("title", path.stem)),
        bpm=float(raw.get("bpm", 120)),
        notes=notes,
    )
