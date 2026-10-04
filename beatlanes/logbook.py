# the tap log, csv format, will write each note on one line as the run progresses

import csv  # this is what we will call the log
from datetime import datetime  # filename and what goes in the header
from pathlib import Path
from typing import Optional, Union

from . import config  # directory that logs will be stored in
from .judge import Verdict  # the name we give our verdicts

HEADER = (  # order they appear in
    "note_index",
    "lane",
    "target_ms",
    "tap_ms",
    "error_ms",
    "verdict",
    "mixer_pos_ms",
)

VerdictLike = Union[Verdict, str]  # will take an enum or string


class TapLog:  # takes the taps from one run and puts them in a csv
    def __init__(
        self,
        path: Optional[Path | str] = None,  # path to write to, defaults to logs directory
        song: str = "",  # name of song to put in the header
        calibration_ms: float = 0.0,  # what offset was used for the header
    ) -> None:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)  # will create logs dir if it does not exist
        if path is None:  # default name includes the time so runs never overwrite
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")  # datetime in the name so it never overrides a past log
            path = config.LOG_DIR / f"taps-{stamp}.csv"
        self.path = Path(path)
        self._file = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        # start with some hashes, these will just be strings in excel and you can ignore them with code
        self._writer.writerow(["# BeatLanes tap log"])
        self._writer.writerow([f"# written {datetime.now().isoformat(timespec='seconds')}"])
        if song:  # include the name of the song
            self._writer.writerow([f"# song {song}"])
        self._writer.writerow([f"# calibration_offset_ms {calibration_ms:.0f}"])
        self._writer.writerow(HEADER)  # these are the actual columns

    def write_tap(
        self,
        note_index: int,  # what note it was
        lane: int,  # what lane it was on
        target_ms: float,  # what time we wanted it hit
        tap_ms: Optional[float],  # when we actually hit it, blank if missed
        error_ms: Optional[float],  # how far off we were, blank if missed
        verdict: VerdictLike,  # PERFECT GOOD or MISS
        mixer_pos_ms: Optional[int] = None,  # clock on the 2nd tick when we tapped
    ) -> None:
        # one note judged, with tap info or nothing if missed
        verdict_text = verdict.value if isinstance(verdict, Verdict) else str(verdict)
        self._writer.writerow(
            [
                note_index,
                lane,
                f"{target_ms:.0f}",
                "" if tap_ms is None else f"{tap_ms:.0f}",  # blank if missed
                "" if error_ms is None else f"{error_ms:+.0f}",  # negative if early, positive if late
                verdict_text,
                "" if mixer_pos_ms is None else mixer_pos_ms,  # blank if no sound
            ]
        )

    def close(self) -> None:  # make sure everything is flushed and closed
        if not self._file.closed:
            self._file.flush()
            self._file.close()

    def __enter__(self) -> "TapLog":  # allows you to use with
        return self

    def __exit__(self, *exc_info) -> None:  # will always close the file
        self.close()


def read_log(path: Path | str) -> list[dict[str, str]]:
    # will take a log and return it as data to be used by tools and unit tests
    rows: list[dict[str, str]] = []
    with Path(path).open(encoding="utf-8") as handle:
        header: Optional[list[str]] = None
        for line in handle:
            if line.startswith("#"):  # ignore all comment lines
                continue
            cells = next(csv.reader([line]))
            if header is None:  # the first none comment line will be your columns
                header = cells
                continue
            rows.append(dict(zip(header, cells)))
    return rows
