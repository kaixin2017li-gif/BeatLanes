"""Drawing.

This module knows about rectangles, colours and fonts, and nothing about timing
rules. Keeping it separate means the parts that decide the outcome of a run can
be tested without opening a window.

Anything that needs a song time is given one; nothing here reads a clock.
"""

from __future__ import annotations

from typing import Iterable, Optional

import pygame

from . import config
from .judge import Verdict
from .session import NoteState, PlaySession

# One tint per lane, so a note's lane is readable at a glance.
LANE_TINTS = (
    (126, 196, 255),
    (146, 222, 246),
    (176, 202, 255),
    (108, 226, 214),
)

VERDICT_COLOURS = {
    Verdict.PERFECT: config.PERFECT_COLOUR,
    Verdict.GOOD: config.GOOD_COLOUR,
    Verdict.MISS: config.MISS_COLOUR,
}

_FONTS: dict[tuple[int, bool, bool], pygame.font.Font] = {}

UI_FONT = ("avenirnext", "helvetica", "arial")
MONO_FONT = ("menlo", "consolas", "couriernew")


def font(size: int, bold: bool = False, mono: bool = False) -> pygame.font.Font:
    """Cached font lookup with a fallback to Pygame's built-in font."""
    key = (size, bold, mono)
    cached = _FONTS.get(key)
    if cached is not None:
        return cached
    family = ",".join(MONO_FONT if mono else UI_FONT)
    try:
        loaded = pygame.font.SysFont(family, size, bold=bold)
    except Exception:
        loaded = pygame.font.Font(None, size)
    _FONTS[key] = loaded
    return loaded


# --- geometry ---------------------------------------------------------------
def lanes_width() -> float:
    return config.LANE_COUNT * config.LANE_WIDTH + (config.LANE_COUNT - 1) * config.LANE_GAP


def lane_left() -> float:
    return (config.WINDOW_WIDTH - lanes_width()) / 2.0


def lane_rect(index: int) -> pygame.Rect:
    """Full-height rectangle for one lane."""
    x = lane_left() + index * (config.LANE_WIDTH + config.LANE_GAP)
    return pygame.Rect(int(x), 0, config.LANE_WIDTH, config.WINDOW_HEIGHT)


def lane_centre_x(index: int) -> float:
    return lane_left() + index * (config.LANE_WIDTH + config.LANE_GAP) + config.LANE_WIDTH / 2.0


def y_for_time(time_ms: float, song_ms: float) -> float:
    """Screen y of a moment in the song.

    The conversion is the same one LiveNote.screen_y uses, so the beat grid and
    the notes can never disagree about where the music is.
    """
    px_per_ms = (config.JUDGE_LINE_Y - config.NOTE_SPAWN_Y) / config.APPROACH_MS
    return config.JUDGE_LINE_Y - (time_ms - song_ms) * px_per_ms


# --- small helpers ----------------------------------------------------------
def text(
    surface: pygame.Surface,
    message: str,
    position: tuple[float, float],
    size: int = 18,
    colour: tuple[int, int, int] = config.TEXT,
    bold: bool = False,
    mono: bool = False,
    align: str = "left",
) -> pygame.Rect:
    """Draw one line of text and return the rectangle it occupied."""
    image = font(size, bold=bold, mono=mono).render(message, True, colour)
    rect = image.get_rect()
    if align == "center":
        rect.midtop = (int(position[0]), int(position[1]))
    elif align == "right":
        rect.topright = (int(position[0]), int(position[1]))
    else:
        rect.topleft = (int(position[0]), int(position[1]))
    surface.blit(image, rect)
    return rect


def panel(
    surface: pygame.Surface,
    rect: pygame.Rect,
    fill: tuple[int, int, int] = config.PANEL,
    edge: Optional[tuple[int, int, int]] = config.LANE_EDGE,
    radius: int = 10,
) -> None:
    pygame.draw.rect(surface, fill, rect, border_radius=radius)
    if edge is not None:
        pygame.draw.rect(surface, edge, rect, width=1, border_radius=radius)


# --- play screen ------------------------------------------------------------
def draw_background(surface: pygame.Surface) -> None:
    surface.fill(config.BACKGROUND)


def draw_beat_grid(
    surface: pygame.Surface,
    song_ms: float,
    bpm: float,
    beats_per_bar: int = 4,
) -> None:
    """Faint lines showing where the beats are.

    This is the visual proof that the notes follow the song clock: the lines and
    the notes are placed with the same function.
    """
    if bpm <= 0:
        return
    beat_ms = 60_000.0 / bpm
    # only draw the beats that can be on screen: from just below the judgement
    # line to a little above the top edge
    earliest = song_ms - (config.WINDOW_HEIGHT - config.JUDGE_LINE_Y) / (
        (config.JUDGE_LINE_Y - config.NOTE_SPAWN_Y) / config.APPROACH_MS
    )
    latest = song_ms + config.APPROACH_MS
    first_beat = int(earliest // beat_ms)
    last_beat = int(latest // beat_ms) + 1
    left = int(lane_left()) - 24
    right = int(lane_left() + lanes_width()) + 24
    for beat in range(first_beat, last_beat + 1):
        if beat < 0:
            continue
        y = int(y_for_time(beat * beat_ms, song_ms))
        if y < -2 or y > config.WINDOW_HEIGHT + 2:
            continue
        bar_line = beat % beats_per_bar == 0
        colour = config.JUDGE_LINE if bar_line else config.BEAT_GRID
        width = 2 if bar_line else 1
        pygame.draw.line(surface, colour, (left, y), (right, y), width)


def draw_lanes(
    surface: pygame.Surface,
    flashes: Optional[dict[int, float]] = None,
    song_ms: float = 0.0,
) -> None:
    """Lane strips, brightened for a moment after a key press."""
    for index in range(config.LANE_COUNT):
        rect = lane_rect(index)
        tint = config.LANE_FILL if index % 2 == 0 else config.LANE_FILL_ALT
        pygame.draw.rect(surface, tint, rect)

        age = None if not flashes else flashes.get(index)
        if age is not None:
            age_ms = song_ms - age
            if 0 <= age_ms < 220:
                strength = 1.0 - age_ms / 220.0
                glow = pygame.Surface((rect.width, 120), pygame.SRCALPHA)
                glow.fill((*config.HIT_FLASH, int(70 * strength)))
                surface.blit(glow, (rect.x, int(config.JUDGE_LINE_Y) - 90))

        pygame.draw.line(surface, config.LANE_EDGE, rect.topleft, rect.bottomleft, 1)
        pygame.draw.line(surface, config.LANE_EDGE, rect.topright, rect.bottomright, 1)


def draw_judge_line(surface: pygame.Surface, flashes: Optional[dict[int, float]] = None) -> None:
    y = int(config.JUDGE_LINE_Y)
    pygame.draw.line(
        surface,
        config.JUDGE_LINE,
        (int(lane_left()) - 16, y),
        (int(lane_left() + lanes_width()) + 16, y),
        3,
    )
    for index in range(config.LANE_COUNT):
        rect = lane_rect(index)
        colour = config.LANE_EDGE
        if flashes:
            age = flashes.get(index)
            if age is not None and 0 <= age < 220:
                colour = config.HIT_FLASH
        pygame.draw.line(surface, colour, (rect.x, y), (rect.right, y), 3)


def draw_notes(surface: pygame.Surface, session: PlaySession, song_ms: float) -> None:
    """Live notes, positioned from the song clock."""
    for note in session.notes:
        if note.state is not NoteState.PENDING:
            continue
        y = note.screen_y(song_ms)
        if y < -config.NOTE_HEIGHT or y > config.WINDOW_HEIGHT + config.NOTE_HEIGHT:
            continue
        rect = lane_rect(note.lane)
        note_rect = pygame.Rect(0, 0, config.NOTE_WIDTH, config.NOTE_HEIGHT)
        note_rect.center = (int(rect.centerx), int(y))
        tint = LANE_TINTS[note.lane]
        # notes that are very close to their moment get a brighter edge
        distance = abs(note.time_ms - song_ms)
        edge = config.NOTE_EDGE if distance <= config.GOOD_MS else tint
        pygame.draw.rect(surface, tint, note_rect, border_radius=6)
        pygame.draw.rect(surface, edge, note_rect, width=2, border_radius=6)


def draw_lane_labels(surface: pygame.Surface) -> None:
    for index, label in enumerate(config.LANE_LABELS):
        text(
            surface,
            label,
            (lane_centre_x(index), config.WINDOW_HEIGHT - 34),
            size=17,
            colour=config.TEXT_MUTED,
            bold=True,
            mono=True,
            align="center",
        )


def draw_judgement_popup(
    surface: pygame.Surface,
    verdict: Verdict,
    error_text: str,
    age_ms: float,
) -> None:
    """The word that flashes up after a press."""
    if not 0 <= age_ms < 500:
        return
    fade = 1.0 - age_ms / 500.0
    centre_x = config.WINDOW_WIDTH / 2.0
    y = config.JUDGE_LINE_Y - 132
    colour = VERDICT_COLOURS[verdict]
    dimmed = tuple(int(channel * (0.45 + 0.55 * fade)) for channel in colour)
    text(surface, verdict.value, (centre_x, y), size=30, colour=dimmed, bold=True, align="center")
    text(
        surface,
        error_text,
        (centre_x, y + 36),
        size=15,
        colour=config.TEXT_MUTED,
        mono=True,
        align="center",
    )


def draw_play_hud(
    surface: pygame.Surface,
    session: PlaySession,
    song_ms: float,
    fps: Optional[float],
    chart_title: str,
) -> None:
    score = session.score
    text(surface, chart_title, (24, 18), size=17, colour=config.TEXT_MUTED)
    text(surface, f"{song_ms / 1000.0:6.2f} s", (24, 42), size=22, colour=config.TEXT, mono=True)
    if fps is not None:
        # a headless run has no frame rate worth reporting, so it shows nothing
        text(surface, f"{fps:5.1f} fps", (24, 70), size=14, colour=config.TEXT_MUTED, mono=True)

    text(surface, f"{score.points:6d}", (config.WINDOW_WIDTH - 24, 18), size=30, colour=config.TEXT, bold=True, mono=True, align="right")
    text(
        surface,
        f"{score.judged} / {score.note_count} notes",
        (config.WINDOW_WIDTH - 24, 54),
        size=14,
        colour=config.TEXT_MUTED,
        mono=True,
        align="right",
    )
    if score.combo >= 2:
        text(
            surface,
            f"{score.combo} COMBO",
            (config.WINDOW_WIDTH / 2.0, config.JUDGE_LINE_Y + 26),
            size=20,
            colour=config.HIT_FLASH,
            bold=True,
            align="center",
        )


def draw_debug_panel(
    surface: pygame.Surface,
    song_ms: float,
    ticks_ms: Optional[int],
    mixer_pos_ms: Optional[int],
    drift_ms: Optional[float],
    latency_offset_ms: float,
    fps: Optional[float],
) -> None:
    """Second reading and calibration state.

    The mixer reading is shown next to the tick clock so the two can be
    compared live. This is the panel that made it obvious the mixer could not be
    the primary clock.
    """
    lines = [
        "DEBUG  TAB to hide",
        f"tick clock   song {song_ms:8.1f} ms",
        f"             raw  {'' if ticks_ms is None else ticks_ms} ms",
        f"mixer get_pos {'' if mixer_pos_ms is None else mixer_pos_ms} ms",
        f"drift        {'' if drift_ms is None else f'{drift_ms:+.0f}'} ms",
        f"latency offset {latency_offset_ms:+.0f} ms",
        "fps          " + ("-" if fps is None else f"{fps:5.1f}"),
    ]
    width, height = 330, 14 + 20 * len(lines)
    rect = pygame.Rect(24, config.WINDOW_HEIGHT - height - 24, width, height)
    panel(surface, rect)
    for row, line in enumerate(lines):
        colour = config.TEXT if row == 0 else config.TEXT_MUTED
        text(surface, line, (rect.x + 14, rect.y + 10 + row * 20), size=14, colour=colour, mono=True)


# --- other screens ----------------------------------------------------------
def draw_title(
    surface: pygame.Surface,
    chart_title: str,
    note_count: int,
    calibration_ms: float,
    best_accuracy: Optional[float] = None,
) -> None:
    draw_background(surface)
    draw_beat_grid(surface, 0.0, 120.0)
    centre_x = config.WINDOW_WIDTH / 2.0
    text(surface, "BEATLANES", (centre_x, 128), size=64, colour=config.TEXT, bold=True, align="center")
    text(
        surface,
        "a four lane keyboard rhythm prototype",
        (centre_x, 202),
        size=19,
        colour=config.HIT_FLASH,
        align="center",
    )

    box = pygame.Rect(int(centre_x) - 350, 262, 700, 176)
    panel(surface, box)
    rows = [
        ("Chart", f"{chart_title}  ({note_count} notes)"),
        ("Keys", "D   F   J   K   - one key per lane"),
        ("Play", "press the lane key as the note meets the line"),
        ("Windows", f"PERFECT +-{config.PERFECT_MS:.0f} ms   GOOD +-{config.GOOD_MS:.0f} ms"),
        ("Calibration", f"{calibration_ms:+.0f} ms"),
    ]
    for row, (label, value) in enumerate(rows):
        y = box.y + 20 + row * 29
        text(surface, label, (box.x + 22, y), size=15, colour=config.TEXT_MUTED, bold=True)
        text(surface, value, (box.x + 172, y), size=15, colour=config.TEXT, mono=True)

    if best_accuracy is not None:
        text(
            surface,
            f"last run accuracy {best_accuracy:.1f}%",
            (centre_x, box.bottom + 18),
            size=15,
            colour=config.TEXT_MUTED,
            mono=True,
            align="center",
        )
    text(
        surface,
        "SPACE  start      C  calibrate      ESC  quit",
        (centre_x, config.WINDOW_HEIGHT - 92),
        size=19,
        colour=config.TEXT,
        bold=True,
        align="center",
    )
    text(
        surface,
        "TAB  debug overlay while playing",
        (centre_x, config.WINDOW_HEIGHT - 62),
        size=15,
        colour=config.TEXT_MUTED,
        align="center",
    )


def draw_calibration(
    surface: pygame.Surface,
    beat_index: int,
    total_beats: int,
    offsets: Iterable[float],
    current_offset_ms: Optional[float],
    beat_phase: float,
) -> None:
    """Tap-to-metronome screen.

    beat_phase is 0..1 through the current beat, used to pulse the circle so the
    player has something to aim at.
    """
    draw_background(surface)
    centre_x = config.WINDOW_WIDTH / 2.0
    text(surface, "CALIBRATION", (centre_x, 70), size=34, colour=config.TEXT, bold=True, align="center")
    text(
        surface,
        "tap D on every click - the offset is measured from your taps",
        (centre_x, 116),
        size=17,
        colour=config.TEXT_MUTED,
        align="center",
    )

    radius = 60 + int(26 * (1.0 - beat_phase))
    pygame.draw.circle(surface, config.LANE_FILL_ALT, (int(centre_x), 300), 78)
    pygame.draw.circle(surface, config.HIT_FLASH, (int(centre_x), 300), radius, width=4)
    pygame.draw.circle(surface, config.JUDGE_LINE, (int(centre_x), 300), 8)

    text(
        surface,
        f"{min(beat_index, total_beats)} / {total_beats}",
        (centre_x, 400),
        size=26,
        colour=config.TEXT,
        mono=True,
        align="center",
    )

    collected = list(offsets)
    if collected:
        mean = sum(collected) / len(collected)
        text(
            surface,
            f"taps {len(collected)}   running average {mean:+.0f} ms",
            (centre_x, 442),
            size=17,
            colour=config.TEXT_MUTED,
            mono=True,
            align="center",
        )
        # one tick per tap, 1 px per ms, so the spread is visible
        base_y = 486
        pygame.draw.line(surface, config.LANE_EDGE, (int(centre_x) - 200, base_y), (int(centre_x) + 200, base_y), 1)
        for value in collected:
            x = centre_x + max(-190, min(190, value))
            colour = config.PERFECT_COLOUR if abs(value) <= config.PERFECT_MS else config.GOOD_COLOUR
            pygame.draw.line(surface, colour, (int(x), base_y - 10), (int(x), base_y + 10), 2)

    if current_offset_ms is not None:
        text(
            surface,
            f"last tap {current_offset_ms:+.0f} ms",
            (centre_x, 512),
            size=15,
            colour=config.TEXT_MUTED,
            mono=True,
            align="center",
        )
    text(
        surface,
        "ESC  cancel",
        (centre_x, config.WINDOW_HEIGHT - 60),
        size=16,
        colour=config.TEXT_MUTED,
        align="center",
    )


def draw_results(
    surface: pygame.Surface,
    session: PlaySession,
    log_name: str,
    chart_title: str,
) -> None:
    draw_background(surface)
    draw_beat_grid(surface, session.chart.length_ms, session.chart.bpm)
    centre_x = config.WINDOW_WIDTH / 2.0

    score = session.score
    text(surface, "RESULTS", (centre_x, 54), size=38, colour=config.TEXT, bold=True, align="center")
    text(surface, chart_title, (centre_x, 100), size=16, colour=config.TEXT_MUTED, align="center")

    box = pygame.Rect(int(centre_x) - 250, 138, 500, 330)
    panel(surface, box)
    text(
        surface,
        score.rank,
        (box.x + 70, box.y + 42),
        size=96,
        colour=config.HIT_FLASH,
        bold=True,
        align="center",
    )
    text(
        surface,
        f"{score.accuracy:.1f}%",
        (box.x + 70, box.y + 148),
        size=22,
        colour=config.TEXT,
        mono=True,
        align="center",
    )
    text(
        surface,
        f"{score.points} / {score.max_points}",
        (box.x + 70, box.y + 176),
        size=15,
        colour=config.TEXT_MUTED,
        mono=True,
        align="center",
    )

    rows = [
        ("PERFECT", score.perfect, config.PERFECT_COLOUR),
        ("GOOD", score.good, config.GOOD_COLOUR),
        ("MISS", score.miss, config.MISS_COLOUR),
    ]
    for row, (label, value, colour) in enumerate(rows):
        y = box.y + 48 + row * 54
        text(surface, label, (box.x + 190, y), size=19, colour=colour, bold=True, mono=True)
        text(surface, str(value), (box.right - 30, y), size=19, colour=colour, mono=True, align="right")

    text(
        surface,
        f"best combo {score.best_combo}",
        (box.x + 190, box.y + 214),
        size=15,
        colour=config.TEXT_MUTED,
        mono=True,
    )
    text(
        surface,
        f"early / late {score.early_taps} / {score.late_taps}",
        (box.x + 190, box.y + 238),
        size=15,
        colour=config.TEXT_MUTED,
        mono=True,
    )
    text(
        surface,
        f"stray taps {score.stray_taps}",
        (box.x + 190, box.y + 262),
        size=15,
        colour=config.TEXT_MUTED,
        mono=True,
    )

    text(
        surface,
        f"tap log  {log_name}",
        (centre_x, box.bottom + 18),
        size=15,
        colour=config.TEXT_MUTED,
        mono=True,
        align="center",
    )
    text(
        surface,
        "R  play again        T  title        ESC  quit",
        (centre_x, config.WINDOW_HEIGHT - 62),
        size=18,
        colour=config.TEXT,
        bold=True,
        align="center",
    )
