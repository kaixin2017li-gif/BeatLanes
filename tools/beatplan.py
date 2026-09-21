"""The plan the song and the chart are both built from.

The audio generator and the chart generator read this one file, which is how
the notes and the drums stay together: they are placed on the same beat grid
rather than lined up by ear afterwards.

Tempo is 120 BPM, so one beat is 500 ms and one 4/4 bar is 2000 ms. The first
four bars are an intro with the drums only, which gives the player time to hear
the beat before the first note arrives.
"""

from __future__ import annotations

BPM = 120.0
BEAT_MS = 60_000.0 / BPM  # 500 ms
BEATS_PER_BAR = 4
BAR_MS = BEAT_MS * BEATS_PER_BAR  # 2000 ms
BARS = 16
SONG_MS = BARS * BAR_MS  # 32000 ms

INTRO_BARS = 4  # drums only, no notes

# Lane patterns, one per bar, read as "which lane on beat 1, beat 2, beat 3, beat 4".
# Lanes are 0..3 = D F J K. The cycle repeats down the chart.
BAR_PATTERNS = (
    (0, 1, 2, 3),
    (3, 2, 1, 0),
    (0, 2, 1, 3),
    (1, 3, 0, 2),
    (0, 1, 0, 3),
    (2, 3, 2, 1),
)


def note_times() -> list[tuple[float, int]]:
    """(time_ms, lane) for every note in the chart, in play order."""
    notes: list[tuple[float, int]] = []
    for bar in range(BARS):
        if bar < INTRO_BARS:
            continue
        pattern = BAR_PATTERNS[(bar - INTRO_BARS) % len(BAR_PATTERNS)]
        for beat, lane in enumerate(pattern):
            notes.append((bar * BAR_MS + beat * BEAT_MS, lane))
    return notes


def note_count() -> int:
    return len(note_times())
