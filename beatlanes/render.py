"""Drawing.

This module knows about rectangles, colours and fonts, and nothing about timing
rules. Keeping it separate means the parts that decide the outcome of a run can
be tested without opening a window.

Anything that needs a song time is given one; nothing here reads a clock. The
few animations on the title screen are driven by an ambient time handed in by
the caller, so a headless screenshot still produces the same frame every time.

The heavier looks - gradient notes, glows, hit bursts - are precomputed sprites
stamped with an alpha, not per-frame pixel work. pygame has no blur, so every
glow here is a stack of soft stamped layers built once and cached.
"""

from __future__ import annotations

import math
import random
from typing import Iterable, Optional

import pygame

from . import config
from .judge import Verdict
from .session import NoteState, PlaySession

# One tint per lane, so a note's lane is readable at a glance. The four are
# picked to stay distinct from each other and from the verdict colours.
LANE_TINTS = (
    (126, 196, 255),  # ice blue
    (178, 156, 255),  # violet
    (255, 150, 205),  # pink
    (108, 226, 214),  # mint
)

VERDICT_COLOURS = {
    Verdict.PERFECT: config.PERFECT_COLOUR,
    Verdict.GOOD: config.GOOD_COLOUR,
    Verdict.MISS: config.MISS_COLOUR,
}

# Rank grades on the results screen, coolest to warmest as the run gets worse.
RANK_COLOURS = {
    "S": (255, 214, 102),
    "A": config.PERFECT_COLOUR,
    "B": config.HIT_FLASH,
    "C": config.GOOD_COLOUR,
    "D": config.MISS_COLOUR,
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


def receptor_rect(index: int) -> pygame.Rect:
    """The key slot on the judgement line for one lane."""
    rect = pygame.Rect(0, 0, config.NOTE_WIDTH + 8, 36)
    rect.center = (int(lane_centre_x(index)), int(config.JUDGE_LINE_Y))
    return rect


# --- colour helpers ---------------------------------------------------------
def _lerp_colour(
    a: tuple[int, int, int], b: tuple[int, int, int], t: float
) -> tuple[int, int, int]:
    """Linear blend between two colours; t = 0 gives a, t = 1 gives b."""
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def _lighten(colour: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    """Blend a colour towards white."""
    return _lerp_colour(colour, (255, 255, 255), amount)


# --- cached sprites ---------------------------------------------------------
# Everything in this section is built once and reused. The caches are keyed by
# the values that shape the sprite, so nothing here holds mutable state.

_BACKGROUNDS: dict[tuple[int, int], pygame.Surface] = {}
_PANELS: dict[tuple[int, int, int, int], pygame.Surface] = {}
_NOTE_SPRITES: dict[tuple[int, int, int], pygame.Surface] = {}
_NOTE_GLOWS: dict[tuple[int, int, int], pygame.Surface] = {}
_SPARK_SPRITES: dict[tuple[int, int, int], pygame.Surface] = {}
_RING_SPRITES: dict[tuple[int, int, int], pygame.Surface] = {}


def _background_sprite() -> pygame.Surface:
    """Vertical gradient plus a vignette, the size of the window."""
    key = (config.WINDOW_WIDTH, config.WINDOW_HEIGHT)
    cached = _BACKGROUNDS.get(key)
    if cached is not None:
        return cached

    width, height = key
    surface = pygame.Surface(key)
    for y in range(height):
        t = y / max(1, height - 1)
        pygame.draw.line(
            surface,
            _lerp_colour(config.BACKGROUND_TOP, config.BACKGROUND_BOTTOM, t),
            (0, y),
            (width, y),
        )

    # The vignette is four soft edge gradients. Corners are stamped by two of
    # them, which is exactly the extra darkening a vignette wants there.
    overlay = pygame.Surface(key, pygame.SRCALPHA)
    edge = 150
    for i in range(edge):
        alpha = int(64 * (1.0 - i / edge) ** 2)
        pygame.draw.line(overlay, (0, 0, 0, alpha), (0, i), (width, i))
        pygame.draw.line(
            overlay, (0, 0, 0, alpha), (0, height - 1 - i), (width, height - 1 - i)
        )
    side = 240
    for i in range(side):
        alpha = int(52 * (1.0 - i / side) ** 2)
        pygame.draw.line(overlay, (0, 0, 0, alpha), (i, 0), (i, height))
        pygame.draw.line(
            overlay, (0, 0, 0, alpha), (width - 1 - i, 0), (width - 1 - i, height)
        )
    surface.blit(overlay, (0, 0))

    _BACKGROUNDS[key] = surface
    return surface


def _note_sprite(tint: tuple[int, int, int]) -> pygame.Surface:
    """A rounded, vertically shaded note with a glossy top cap."""
    key = (config.NOTE_WIDTH, config.NOTE_HEIGHT, *tint)
    cached = _NOTE_SPRITES.get(key)
    if cached is not None:
        return cached

    width, height = config.NOTE_WIDTH, config.NOTE_HEIGHT
    gradient = pygame.Surface((width, height))
    top = _lighten(tint, 0.38)
    bottom = _lerp_colour(tint, (10, 14, 24), 0.35)
    for y in range(height):
        pygame.draw.line(gradient, _lerp_colour(top, bottom, y / max(1, height - 1)), (0, y), (width, y))

    # Round the corners by multiplying against a rounded mask.
    mask = pygame.Surface((width, height), pygame.SRCALPHA)
    mask.fill((0, 0, 0, 0))
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=6)
    gradient = gradient.convert_alpha()
    gradient.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

    # A bright cap along the top edge reads as the note's leading face.
    pygame.draw.line(gradient, (*_lighten(tint, 0.75), 220), (5, 1), (width - 5, 1), 2)

    _NOTE_SPRITES[key] = gradient
    return gradient


def _note_glow(tint: tuple[int, int, int]) -> pygame.Surface:
    """A soft halo a little larger than the note, stamped underneath it."""
    pad = 14
    key = (config.NOTE_WIDTH + pad * 2, config.NOTE_HEIGHT + pad * 2, *tint)
    cached = _NOTE_GLOWS.get(key)
    if cached is not None:
        return cached

    width, height = key[0], key[1]
    glow = pygame.Surface((width, height), pygame.SRCALPHA)
    # No blur in pygame: stacked translucent rounded rects, widest faintest.
    for step in range(4, 0, -1):
        alpha = int(26 * (5 - step) / 4)
        inset = pad - step * 3
        rect = pygame.Rect(inset, inset, width - inset * 2, height - inset * 2)
        pygame.draw.rect(glow, (*tint, alpha), rect, border_radius=8)
    _NOTE_GLOWS[key] = glow
    return glow


def _spark_sprite(tint: tuple[int, int, int]) -> pygame.Surface:
    """A small soft dot, one particle of a hit burst."""
    key = (12, 12, *tint)
    cached = _SPARK_SPRITES.get(key)
    if cached is not None:
        return cached
    spark = pygame.Surface((12, 12), pygame.SRCALPHA)
    pygame.draw.circle(spark, (*tint, 70), (6, 6), 5)
    pygame.draw.circle(spark, (*_lighten(tint, 0.6), 230), (6, 6), 2)
    _SPARK_SPRITES[key] = spark
    return spark


def _ring_sprite(tint: tuple[int, int, int]) -> pygame.Surface:
    """A glowing ring, scaled per frame for the hit burst."""
    key = (128, 128, *tint)
    cached = _RING_SPRITES.get(key)
    if cached is not None:
        return cached
    ring = pygame.Surface((128, 128), pygame.SRCALPHA)
    pygame.draw.circle(ring, (*tint, 46), (64, 64), 54, width=10)
    pygame.draw.circle(ring, (*_lighten(tint, 0.4), 220), (64, 64), 54, width=3)
    _RING_SPRITES[key] = ring
    return ring


def _panel_sprite(width: int, height: int, radius: int, alpha: int) -> pygame.Surface:
    """A translucent rounded panel, so screens can sit over a live background."""
    key = (width, height, radius, alpha)
    cached = _PANELS.get(key)
    if cached is not None:
        return cached
    panel_image = pygame.Surface((width, height), pygame.SRCALPHA)
    rect = panel_image.get_rect()
    pygame.draw.rect(panel_image, (*config.PANEL, alpha), rect, border_radius=radius)
    pygame.draw.rect(
        panel_image, (*config.LANE_EDGE, min(255, alpha + 40)), rect, width=1, border_radius=radius
    )
    _PANELS[key] = panel_image
    return panel_image


# Sparks of a hit burst. The angles and speeds are fixed per lane from a seeded
# generator, so a burst is a pure function of its age: same age, same frame,
# which keeps headless screenshots deterministic.
_SPARK_COUNT = 12
_SPARKS: dict[int, list[tuple[float, float, float, float]]] = {}


def _sparks_for_lane(lane: int) -> list[tuple[float, float, float, float]]:
    cached = _SPARKS.get(lane)
    if cached is not None:
        return cached
    rng = random.Random(1000 + lane)
    sparks = []
    for _ in range(_SPARK_COUNT):
        angle = rng.uniform(-math.pi, 0.0)  # upwards fan
        angle += rng.uniform(-0.5, 0.5)
        speed = rng.uniform(34.0, 96.0)
        delay = rng.uniform(0.0, 0.25)
        sparks.append((math.cos(angle), math.sin(angle), speed, delay))
    _SPARKS[lane] = sparks
    return sparks


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


def glow_text(
    surface: pygame.Surface,
    message: str,
    position: tuple[float, float],
    size: int,
    colour: tuple[int, int, int],
    glow: tuple[int, int, int] = config.HIT_FLASH,
    bold: bool = True,
    align: str = "center",
    scale: float = 1.0,
    alpha: int = 255,
) -> pygame.Rect:
    """Text with a soft halo: the same glyphs stamped around themselves.

    scale and alpha are applied to the composed stamp, which is what the
    judgement popup and combo counter animate with.
    """
    face = font(size, bold=bold).render(message, True, colour)
    halo = font(size, bold=bold).render(message, True, glow)
    pad = 6
    composed = pygame.Surface((face.get_width() + pad * 2, face.get_height() + pad * 2), pygame.SRCALPHA)
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (-1, 1), (1, -1)):
        stamp = halo.copy()
        stamp.set_alpha(46)
        composed.blit(stamp, (pad + dx, pad + dy))
    composed.blit(face, (pad, pad))
    if scale != 1.0:
        composed = pygame.transform.smoothscale(
            composed,
            (max(1, int(composed.get_width() * scale)), max(1, int(composed.get_height() * scale))),
        )
    if alpha < 255:
        composed = composed.copy()
        composed.set_alpha(alpha)
    rect = composed.get_rect()
    if align == "center":
        rect.midtop = (int(position[0]), int(position[1]))
    elif align == "midbottom":
        rect.midbottom = (int(position[0]), int(position[1]))
    elif align == "right":
        rect.topright = (int(position[0]), int(position[1]))
    else:
        rect.topleft = (int(position[0]), int(position[1]))
    surface.blit(composed, rect)
    return rect


def panel(
    surface: pygame.Surface,
    rect: pygame.Rect,
    fill: tuple[int, int, int] = config.PANEL,
    edge: Optional[tuple[int, int, int]] = config.LANE_EDGE,
    radius: int = 10,
    alpha: Optional[int] = None,
) -> None:
    """A rounded box. With alpha it is a translucent cached sprite instead."""
    if alpha is not None:
        surface.blit(_panel_sprite(rect.width, rect.height, radius, alpha), rect.topleft)
        return
    pygame.draw.rect(surface, fill, rect, border_radius=radius)
    if edge is not None:
        pygame.draw.rect(surface, edge, rect, width=1, border_radius=radius)


# --- play screen ------------------------------------------------------------
def draw_background(surface: pygame.Surface) -> None:
    surface.blit(_background_sprite(), (0, 0))


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
    """Lane strips, lit from the judgement line for a moment after a key press."""
    for index in range(config.LANE_COUNT):
        rect = lane_rect(index)
        tint = config.LANE_FILL if index % 2 == 0 else config.LANE_FILL_ALT
        pygame.draw.rect(surface, tint, rect)

        age = None if not flashes else flashes.get(index)
        if age is not None:
            age_ms = song_ms - age
            if 0 <= age_ms < 260:
                strength = 1.0 - age_ms / 260.0
                # the flash is brightest at the line and thins as it climbs
                glow = pygame.Surface((rect.width, 160), pygame.SRCALPHA)
                for row in range(160):
                    alpha = int(96 * strength * (row / 160.0))
                    pygame.draw.line(
                        glow, (*config.HIT_FLASH, alpha), (0, row), (rect.width, row)
                    )
                surface.blit(glow, (rect.x, int(config.JUDGE_LINE_Y) - 120))

        pygame.draw.line(surface, config.LANE_EDGE, rect.topleft, rect.bottomleft, 1)
        pygame.draw.line(surface, config.LANE_EDGE, rect.topright, rect.bottomright, 1)


def _draw_hit_burst(surface: pygame.Surface, lane: int, age_ms: float) -> None:
    """Ring and sparks out of the receptor, a pure function of the flash's age."""
    if not 0 <= age_ms < 420:
        return
    progress = age_ms / 420.0
    ease = 1.0 - (1.0 - progress) ** 3
    tint = LANE_TINTS[lane]
    centre = receptor_rect(lane).center

    ring = _ring_sprite(tint)
    radius = 20 + int(58 * ease)
    scaled = pygame.transform.scale(ring, (radius * 2, radius * 2))
    scaled.set_alpha(int(230 * (1.0 - progress)))
    surface.blit(scaled, scaled.get_rect(center=centre))

    spark = _spark_sprite(tint)
    for dx, dy, speed, delay in _sparks_for_lane(lane):
        local = progress - delay
        if local <= 0:
            continue
        distance = speed * (1.0 - (1.0 - min(1.0, local / (1.0 - delay))) ** 3)
        # sparks fall back a little as they fade, like embers
        drop = 26.0 * progress * progress
        x = centre[0] + dx * distance
        y = centre[1] + dy * distance + drop
        alpha = int(255 * (1.0 - progress))
        stamp = spark.copy()
        stamp.set_alpha(alpha)
        surface.blit(stamp, stamp.get_rect(center=(int(x), int(y))))


def draw_judge_line(
    surface: pygame.Surface,
    flashes: Optional[dict[int, float]] = None,
    song_ms: Optional[float] = None,
) -> None:
    """The judgement line, its glow, and the four key receptors on it.

    song_ms turns a flash timestamp into an age; without it the receptors draw
    in their resting state.
    """
    y = int(config.JUDGE_LINE_Y)
    left = int(lane_left()) - 16
    right = int(lane_left() + lanes_width()) + 16
    # layered strokes read as a glow without any blur
    overlay = pygame.Surface((right - left + 2, 14), pygame.SRCALPHA)
    pygame.draw.line(overlay, (*config.HIT_FLASH, 34), (0, 7), (right - left, 7), 12)
    pygame.draw.line(overlay, (*config.HIT_FLASH, 60), (0, 7), (right - left, 7), 6)
    surface.blit(overlay, (left, y - 7))
    pygame.draw.line(surface, config.JUDGE_LINE, (left, y), (right, y), 3)

    for index in range(config.LANE_COUNT):
        slot = receptor_rect(index)
        tint = LANE_TINTS[index]
        lit = 0.0
        if flashes and song_ms is not None:
            at = flashes.get(index)
            if at is not None:
                age_ms = song_ms - at
                if 0 <= age_ms < 240:
                    lit = 1.0 - age_ms / 240.0
                _draw_hit_burst(surface, index, age_ms)

        pygame.draw.rect(surface, config.RECEPTOR_FILL, slot, border_radius=9)
        if lit > 0.0:
            flash_overlay = pygame.Surface((slot.width, slot.height), pygame.SRCALPHA)
            pygame.draw.rect(
                flash_overlay,
                (*tint, int(110 * lit)),
                flash_overlay.get_rect(),
                border_radius=9,
            )
            surface.blit(flash_overlay, slot.topleft)
        edge = _lerp_colour(config.RECEPTOR_EDGE, tint, lit)
        pygame.draw.rect(surface, edge, slot, width=2, border_radius=9)


def draw_notes(surface: pygame.Surface, session: PlaySession, song_ms: float) -> None:
    """Live notes, positioned from the song clock."""
    for note in session.notes:
        if note.state is not NoteState.PENDING:
            continue
        y = note.screen_y(song_ms)
        if y < -config.NOTE_HEIGHT or y > config.WINDOW_HEIGHT + config.NOTE_HEIGHT:
            continue
        tint = LANE_TINTS[note.lane]
        sprite = _note_sprite(tint)
        note_rect = sprite.get_rect(center=(int(lane_centre_x(note.lane)), int(y)))

        glow = _note_glow(tint)
        glow_rect = glow.get_rect(center=note_rect.center)

        # notes fade in over their first 80 px instead of popping at the edge
        fade = min(1.0, max(0.0, y / 80.0))
        if fade < 1.0:
            alpha = int(255 * fade)
            glow = glow.copy()
            glow.set_alpha(alpha)
            sprite = sprite.copy()
            sprite.set_alpha(alpha)
        surface.blit(glow, glow_rect)
        surface.blit(sprite, note_rect)

        # notes that are very close to their moment get a brighter edge
        distance = abs(note.time_ms - song_ms)
        if distance <= config.GOOD_MS:
            edge = _lerp_colour(config.NOTE_EDGE, tint, distance / config.GOOD_MS)
            pygame.draw.rect(surface, edge, note_rect, width=2, border_radius=6)


def draw_lane_labels(surface: pygame.Surface) -> None:
    """The key name inside each receptor."""
    for index, label in enumerate(config.LANE_LABELS):
        slot = receptor_rect(index)
        image = font(17, bold=True, mono=True).render(label, True, config.TEXT_MUTED)
        surface.blit(image, image.get_rect(center=slot.center))


def draw_judgement_popup(
    surface: pygame.Surface,
    verdict: Verdict,
    error_text: str,
    age_ms: float,
) -> None:
    """The word that flashes up after a press.

    It opens slightly overscaled, settles, rises a touch, then fades - the pop
    is what makes a PERFECT feel different from reading the same word flat.
    """
    if not 0 <= age_ms < 600:
        return
    fade = 1.0 - age_ms / 600.0
    pop = 1.0 + 0.24 * max(0.0, 1.0 - age_ms / 150.0)
    rise = 10.0 * min(1.0, age_ms / 180.0)
    centre_x = config.WINDOW_WIDTH / 2.0
    colour = VERDICT_COLOURS[verdict]
    alpha = int(255 * min(1.0, fade * 1.6))
    # anchored by its bottom edge, so the opening pop grows upwards and never
    # covers the error reading underneath
    glow_text(
        surface,
        verdict.value,
        (centre_x, config.JUDGE_LINE_Y - 96 - rise),
        size=32,
        colour=colour,
        glow=colour,
        align="midbottom",
        scale=pop,
        alpha=alpha,
    )
    text(
        surface,
        error_text,
        (centre_x, config.JUDGE_LINE_Y - 86),
        size=15,
        colour=_lerp_colour(config.TEXT_MUTED, config.BACKGROUND_BOTTOM, 1.0 - fade),
        mono=True,
        align="center",
    )


def draw_countdown(surface: pygame.Surface, remaining_ms: float) -> None:
    """The 3, 2, 1 before the first note.

    remaining_ms counts down to the first note. Each number swaps in as its
    second starts and pops open like the judgement popup.
    """
    number = max(1, min(3, int(remaining_ms // 1000) + 1))
    # each number pops open for its first 160 ms, like the judgement popup
    age_in_second = 1000.0 - (remaining_ms % 1000.0)
    pop = 1.0 + 0.30 * max(0.0, 1.0 - age_in_second / 160.0)
    fade = min(1.0, remaining_ms / 350.0)
    centre_x = config.WINDOW_WIDTH / 2.0
    glow_text(
        surface,
        str(number),
        (centre_x, 196),
        size=104,
        colour=config.HIT_FLASH,
        glow=config.JUDGE_LINE,
        scale=pop,
        alpha=int(255 * fade),
    )


def draw_go(surface: pygame.Surface, remaining_ms: float) -> None:
    """GO, drawn over the same spot once the countdown has run out."""
    if remaining_ms <= 0:
        return
    fade = min(1.0, remaining_ms / 320.0)
    pop = 1.0 + 0.20 * max(0.0, 1.0 - (800.0 - remaining_ms) / 160.0)
    centre_x = config.WINDOW_WIDTH / 2.0
    glow_text(
        surface,
        "GO",
        (centre_x, 200),
        size=112,
        colour=config.PERFECT_COLOUR,
        glow=config.PERFECT_COLOUR,
        scale=pop,
        alpha=int(255 * fade),
    )


def draw_play_hud(
    surface: pygame.Surface,
    session: PlaySession,
    song_ms: float,
    fps: Optional[float],
    chart_title: str,
) -> None:
    score = session.score

    # song progress along the very top edge of the playfield
    length = max(1.0, float(session.chart.length_ms))
    fraction = min(1.0, max(0.0, song_ms / length))
    bar_left = int(lane_left())
    bar_right = int(lane_left() + lanes_width())
    pygame.draw.line(surface, config.LANE_EDGE, (bar_left, 5), (bar_right, 5), 3)
    if fraction > 0.0:
        fill_x = bar_left + int((bar_right - bar_left) * fraction)
        pygame.draw.line(surface, config.HIT_FLASH, (bar_left, 5), (fill_x, 5), 3)
        pygame.draw.circle(surface, config.HIT_FLASH, (fill_x, 5), 3)

    text(surface, chart_title, (24, 18), size=17, colour=config.TEXT_MUTED)
    text(surface, f"{song_ms / 1000.0:6.2f} s", (24, 42), size=22, colour=config.TEXT, mono=True)
    if fps is not None:
        # a headless run has no frame rate worth reporting, so it shows nothing
        text(surface, f"{fps:5.1f} fps", (24, 70), size=14, colour=config.TEXT_MUTED, mono=True)

    glow_text(
        surface,
        f"{score.points:6d}",
        (config.WINDOW_WIDTH - 24, 18),
        size=30,
        colour=config.TEXT,
        glow=config.JUDGE_LINE,
        align="right",
    )
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
        # the counter pops on each judged note, using the same age as the popup
        age = song_ms - session.last_judged_song_ms
        pop = 1.0 + 0.35 * max(0.0, 1.0 - age / 160.0)
        if score.combo >= 30:
            colour = config.PERFECT_COLOUR
        elif score.combo >= 10:
            colour = config.HIT_FLASH
        else:
            colour = config.TEXT
        glow_text(
            surface,
            f"{score.combo} COMBO",
            (config.WINDOW_WIDTH / 2.0, config.JUDGE_LINE_Y + 30),
            size=20,
            colour=colour,
            glow=colour,
            align="center",
            scale=pop,
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
    panel(surface, rect, alpha=225)
    for row, line in enumerate(lines):
        colour = config.TEXT if row == 0 else config.TEXT_MUTED
        text(surface, line, (rect.x + 14, rect.y + 10 + row * 20), size=14, colour=colour, mono=True)


# --- other screens ----------------------------------------------------------
def _draw_ambient_notes(surface: pygame.Surface, anim_ms: float) -> None:
    """Demo notes drifting down the lanes behind the title content."""
    span = config.WINDOW_HEIGHT + 120
    for i in range(12):
        lane = i % config.LANE_COUNT
        y = (anim_ms * 0.085 + i * 157.0) % span - 60.0
        sprite = _note_sprite(LANE_TINTS[lane]).copy()
        sprite.set_alpha(38)
        surface.blit(sprite, sprite.get_rect(center=(int(lane_centre_x(lane)), int(y))))


def draw_title(
    surface: pygame.Surface,
    chart_title: str,
    note_count: int,
    calibration_ms: float,
    best_accuracy: Optional[float] = None,
    anim_ms: Optional[float] = None,
) -> None:
    """The waiting screen.

    anim_ms is an ambient clock from the caller, used only to drift the
    background notes and pulse the footer. Headless captures pass None and get
    the same still frame every time.
    """
    draw_background(surface)
    if anim_ms is not None:
        _draw_ambient_notes(surface, anim_ms)
    draw_beat_grid(surface, 0.0, 120.0)
    centre_x = config.WINDOW_WIDTH / 2.0

    glow_text(
        surface, "BEATLANES", (centre_x, 118), size=66, colour=config.TEXT, glow=config.HIT_FLASH
    )
    text(
        surface,
        "a four lane keyboard rhythm prototype",
        (centre_x, 200),
        size=19,
        colour=config.HIT_FLASH,
        align="center",
    )

    box = pygame.Rect(int(centre_x) - 350, 258, 700, 176)
    panel(surface, box, alpha=232)
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

    footer = font(19, bold=True).render(
        "SPACE  start      C  calibrate      ESC  quit", True, config.TEXT
    )
    if anim_ms is not None:
        footer.set_alpha(int(200 + 55 * math.sin(anim_ms / 420.0)))
    surface.blit(footer, footer.get_rect(midtop=(int(centre_x), config.WINDOW_HEIGHT - 92)))
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
    glow_text(
        surface, "CALIBRATION", (centre_x, 66), size=36, colour=config.TEXT, glow=config.JUDGE_LINE
    )
    text(
        surface,
        "tap D on every click - the offset is measured from your taps",
        (centre_x, 118),
        size=17,
        colour=config.TEXT_MUTED,
        align="center",
    )

    # the ring snaps back to wide on each click and closes in through the beat
    pulse = 1.0 - beat_phase
    radius = 60 + int(26 * pulse)
    ring_overlay = pygame.Surface((220, 220), pygame.SRCALPHA)
    pygame.draw.circle(ring_overlay, (*config.HIT_FLASH, int(30 + 50 * pulse)), (110, 110), radius, width=8)
    surface.blit(ring_overlay, (int(centre_x) - 110, 300 - 110))
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
    rank_colour = RANK_COLOURS.get(score.rank, config.HIT_FLASH)
    glow_text(surface, "RESULTS", (centre_x, 48), size=40, colour=config.TEXT, glow=config.JUDGE_LINE)
    text(surface, chart_title, (centre_x, 102), size=16, colour=config.TEXT_MUTED, align="center")

    box = pygame.Rect(int(centre_x) - 250, 138, 500, 330)
    panel(surface, box, alpha=235)

    # rank badge: a glowing ring with an accuracy arc around the letter
    badge_centre = (box.x + 70, box.y + 96)
    badge_overlay = pygame.Surface((160, 160), pygame.SRCALPHA)
    pygame.draw.circle(badge_overlay, (*rank_colour, 34), (80, 80), 56, width=10)
    surface.blit(badge_overlay, (badge_centre[0] - 80, badge_centre[1] - 80))
    pygame.draw.circle(surface, config.LANE_EDGE, badge_centre, 54, width=4)
    arc_rect = pygame.Rect(0, 0, 108, 108)
    arc_rect.center = badge_centre
    pygame.draw.arc(
        surface,
        rank_colour,
        arc_rect,
        -math.pi / 2,
        -math.pi / 2 + 2 * math.pi * (score.accuracy / 100.0),
        width=4,
    )
    letter = font(72, bold=True).render(score.rank, True, rank_colour)
    surface.blit(letter, letter.get_rect(center=badge_centre))

    text(
        surface,
        f"{score.accuracy:.1f}%",
        (badge_centre[0], badge_centre[1] + 66),
        size=22,
        colour=config.TEXT,
        mono=True,
        align="center",
    )
    text(
        surface,
        f"{score.points} / {score.max_points}",
        (badge_centre[0], badge_centre[1] + 94),
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
        y = box.y + 44 + row * 50
        text(surface, label, (box.x + 190, y), size=19, colour=colour, bold=True, mono=True)
        text(surface, str(value), (box.right - 30, y), size=19, colour=colour, mono=True, align="right")

    text(
        surface,
        f"best combo {score.best_combo}",
        (box.x + 190, box.y + 200),
        size=15,
        colour=config.TEXT_MUTED,
        mono=True,
    )
    text(
        surface,
        f"early / late {score.early_taps} / {score.late_taps}",
        (box.x + 190, box.y + 224),
        size=15,
        colour=config.TEXT_MUTED,
        mono=True,
    )
    text(
        surface,
        f"stray taps {score.stray_taps}",
        (box.x + 190, box.y + 248),
        size=15,
        colour=config.TEXT_MUTED,
        mono=True,
    )

    # verdict distribution strip: the shape of the run at a glance
    judged = max(1, score.judged)
    bar = pygame.Rect(box.x + 190, box.y + 288, box.right - 30 - (box.x + 190), 8)
    pygame.draw.rect(surface, config.LANE_EDGE, bar, border_radius=4)
    x = bar.x
    for count, colour in (
        (score.perfect, config.PERFECT_COLOUR),
        (score.good, config.GOOD_COLOUR),
        (score.miss, config.MISS_COLOUR),
    ):
        width = int(bar.width * count / judged)
        if width > 0:
            pygame.draw.rect(surface, colour, pygame.Rect(x, bar.y, width, bar.height), border_radius=4)
        x += width

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
