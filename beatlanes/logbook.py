# The CSV tap log: one row per note, written while the run happens.

import csv  # the log is a CSV file
from datetime import datetime  # for the file name and the header
from pathlib import Path
from typing import Optional, Union

from . import config  # where logs live
from .judge import Verdict  # the verdict names go in the log

HEADER = (  # the columns, in order
    "note_index",
    "lane",
    "target_ms",
    "tap_ms",
    "error_ms",
    "verdict",
    "mixer_pos_ms",
)

VerdictLike = Union[Verdict, str]  # accept the enum or its name


class TapLog:  # writes one run of taps to a CSV file
    def __init__(
        self,
        path: Optional[Path | str] = None,  # where to write; default is logs/
        song: str = "",  # song name for the header
        calibration_ms: float = 0.0,  # offset used, for the header
    ) -> None:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)  # make logs/ if needed
        if path is None:  # default name includes the time so runs never overwrite
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = config.LOG_DIR / f"taps-{stamp}.csv"
        self.path = Path(path)
        self._file = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        # leading # rows are metadata; a spreadsheet shows them as text and a
        # script can skip anything starting with '#'
        self._writer.writerow(["# BeatLanes tap log"])
        self._writer.writerow([f"# written {datetime.now().isoformat(timespec='seconds')}"])
        if song:  # song name, if given
            self._writer.writerow([f"# song {song}"])
        self._writer.writerow([f"# calibration_offset_ms {calibration_ms:.0f}"])
        self._writer.writerow(HEADER)  # then the real columns

    def write_tap(
        self,
        note_index: int,  # which note
        lane: int,  # which lane
        target_ms: float,  # when it should have been hit
        tap_ms: Optional[float],  # when it was hit, or None on a miss
        error_ms: Optional[float],  # tap - target, or None on a miss
        verdict: VerdictLike,  # PERFECT / GOOD / MISS
        mixer_pos_ms: Optional[int] = None,  # second clock reading at the tap
    ) -> None:
        # one judged note; empty tap columns mean it was missed
        verdict_text = verdict.value if isinstance(verdict, Verdict) else str(verdict)
        self._writer.writerow(
            [
                note_index,
                lane,
                f"{target_ms:.0f}",
                "" if tap_ms is None else f"{tap_ms:.0f}",  # blank on a miss
                "" if error_ms is None else f"{error_ms:+.0f}",  # signed, so early/late shows
                verdict_text,
                "" if mixer_pos_ms is None else mixer_pos_ms,  # blank without audio
            ]
        )

    def close(self) -> None:  # flush and close the file
        if not self._file.closed:
            self._file.flush()
            self._file.close()

    def __enter__(self) -> "TapLog":  # lets the log be used in a with block
        return self

    def __exit__(self, *exc_info) -> None:  # always closed, even on errors
        self.close()


def read_log(path: Path | str) -> list[dict[str, str]]:
    # read a log back, used by the tools and the tests
    rows: list[dict[str, str]] = []
    with Path(path).open(encoding="utf-8") as handle:
        header: Optional[list[str]] = None
        for line in handle:
            if line.startswith("#"):  # skip the metadata rows
                continue
            cells = next(csv.reader([line]))
            if header is None:  # first non-comment row is the columns
                header = cells
                continue
            rows.append(dict(zip(header, cells)))
    return rows
