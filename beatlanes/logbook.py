"""The CSV tap log.

Every note that gets judged writes one row: when it should have been hit
(target_ms), when it actually was (tap_ms) and the difference between the two.
The mixer reading from the same instant goes in as well, so a finished run can
be used to compare the two clocks instead of arguing about them.

Rows are also written for missed notes, with empty tap and error columns, so
the log shows the shape of a run and not only its successes.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from . import config
from .judge import Verdict

HEADER = (
    "note_index",
    "lane",
    "target_ms",
    "tap_ms",
    "error_ms",
    "verdict",
    "mixer_pos_ms",
)

VerdictLike = Union[Verdict, str]


class TapLog:
    """Writes one run of taps to a CSV file."""

    def __init__(
        self,
        path: Optional[Path | str] = None,
        song: str = "",
        calibration_ms: float = 0.0,
    ) -> None:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        if path is None:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = config.LOG_DIR / f"taps-{stamp}.csv"
        self.path = Path(path)
        self._file = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        # Leading # rows are metadata; a spreadsheet will show them as text and
        # a script can skip anything starting with '#'.
        self._writer.writerow(["# BeatLanes tap log"])
        self._writer.writerow([f"# written {datetime.now().isoformat(timespec='seconds')}"])
        if song:
            self._writer.writerow([f"# song {song}"])
        self._writer.writerow([f"# calibration_offset_ms {calibration_ms:.0f}"])
        self._writer.writerow(HEADER)

    def write_tap(
        self,
        note_index: int,
        lane: int,
        target_ms: float,
        tap_ms: Optional[float],
        error_ms: Optional[float],
        verdict: VerdictLike,
        mixer_pos_ms: Optional[int] = None,
    ) -> None:
        """Append one judged note."""
        verdict_text = verdict.value if isinstance(verdict, Verdict) else str(verdict)
        self._writer.writerow(
            [
                note_index,
                lane,
                f"{target_ms:.0f}",
                "" if tap_ms is None else f"{tap_ms:.0f}",
                "" if error_ms is None else f"{error_ms:+.0f}",
                verdict_text,
                "" if mixer_pos_ms is None else mixer_pos_ms,
            ]
        )

    def close(self) -> None:
        if not self._file.closed:
            self._file.flush()
            self._file.close()

    def __enter__(self) -> "TapLog":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def read_log(path: Path | str) -> list[dict[str, str]]:
    """Read a tap log back. Used by the tests and by the analysis script."""
    rows: list[dict[str, str]] = []
    with Path(path).open(encoding="utf-8") as handle:
        header: Optional[list[str]] = None
        for line in handle:
            if line.startswith("#"):
                continue
            cells = next(csv.reader([line]))
            if header is None:
                header = cells
                continue
            rows.append(dict(zip(header, cells)))
    return rows
