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

import math  # only for the burst maths and the results arc
import random  # seeds the burst angles
from typing import Iterable, Optional  # type hints

import pygame

from . import config  # the shared settings
from .judge import Verdict  # verdict names
from .session import NoteState, PlaySession  # what a run looks like while playing

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
    key = (size, bold, mono)  # fonts are cached by size/weight
    cached = _FONTS.get(key)  # reuse it if we have it
    if cached is not None:  # cache hit
        return cached  # done
    family = ",".join(MONO_FONT if mono else UI_FONT)  # pick the family list
    try:  # fall back to pygame's built-in font if sys fonts fail
        loaded = pygame.font.SysFont(family, size, bold=bold)  # try the system font first
    except Exception:
        loaded = pygame.font.Font(None, size)  # the built-in fallback
    _FONTS[key] = loaded  # remember it
    return loaded


# --- geometry ---------------------------------------------------------------
def lanes_width() -> float:  # total width of the four lanes and their gaps
    return config.LANE_COUNT * config.LANE_WIDTH + (config.LANE_COUNT - 1) * config.LANE_GAP  # lanes plus the gaps between them


def lane_left() -> float:  # x of the first lane, so the block sits centred
    return (config.WINDOW_WIDTH - lanes_width()) / 2.0  # centre the lane block


def lane_rect(index: int) -> pygame.Rect:  # full-height rectangle for one lane
    """Full-height rectangle for one lane."""
    x = lane_left() + index * (config.LANE_WIDTH + config.LANE_GAP)  # lane's left edge
    return pygame.Rect(int(x), 0, config.LANE_WIDTH, config.WINDOW_HEIGHT)  # full height strip


def lane_centre_x(index: int) -> float:  # centre x of one lane
    return lane_left() + index * (config.LANE_WIDTH + config.LANE_GAP) + config.LANE_WIDTH / 2.0  # left edge + half width


def y_for_time(time_ms: float, song_ms: float) -> float:  # screen y of a moment in the song
    """Screen y of a moment in the song.

    The conversion is the same one LiveNote.screen_y uses, so the beat grid and
    the notes can never disagree about where the music is.
    """
    px_per_ms = (config.JUDGE_LINE_Y - config.NOTE_SPAWN_Y) / config.APPROACH_MS  # scroll speed
    return config.JUDGE_LINE_Y - (time_ms - song_ms) * px_per_ms  # on the line exactly at its target time


def receptor_rect(index: int) -> pygame.Rect:  # the key slot drawn on the line
    """The key slot on the judgement line for one lane."""
    rect = pygame.Rect(0, 0, config.NOTE_WIDTH + 8, 36)  # slightly wider than a note
    rect.center = (int(lane_centre_x(index)), int(config.JUDGE_LINE_Y))  # centred on the line
    return rect  # caller may need the area


# --- colour helpers ---------------------------------------------------------
def _lerp_colour(  # blend two colours, t=0 gives a, t=1 gives b
    a: tuple[int, int, int], b: tuple[int, int, int], t: float
) -> tuple[int, int, int]:
    """Linear blend between two colours; t = 0 gives a, t = 1 gives b."""
    return (  # blend each channel
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def _lighten(colour: tuple[int, int, int], amount: float) -> tuple[int, int, int]:  # blend towards white
    """Blend a colour towards white."""
    return _lerp_colour(colour, (255, 255, 255), amount)  # amount 0..1


# --- cached sprites ---------------------------------------------------------
# Everything in this section is built once and reused. The caches are keyed by
# the values that shape the sprite, so nothing here holds mutable state.

_BACKGROUNDS: dict[tuple[int, int], pygame.Surface] = {}  # cached backgrounds, keyed by size
_PANELS: dict[tuple[int, int, int, int], pygame.Surface] = {}  # cached panels, keyed by size/radius/alpha
_NOTE_SPRITES: dict[tuple[int, int, int], pygame.Surface] = {}  # cached note images per lane tint
_NOTE_GLOWS: dict[tuple[int, int, int], pygame.Surface] = {}  # cached note halos
_SPARK_SPRITES: dict[tuple[int, int, int], pygame.Surface] = {}  # cached burst particles
_RING_SPRITES: dict[tuple[int, int, int], pygame.Surface] = {}  # cached burst rings


def _background_sprite() -> pygame.Surface:  # vertical gradient + vignette, built once
    """Vertical gradient plus a vignette, the size of the window."""
    key = (config.WINDOW_WIDTH, config.WINDOW_HEIGHT)  # window-sized
    cached = _BACKGROUNDS.get(key)  # already built?
    if cached is not None:  # use the cached one
        return cached

    width, height = key  # unpack
    surface = pygame.Surface(key)  # opaque, like the frame it lands on
    for y in range(height):  # one line per pixel row
        t = y / max(1, height - 1)  # 0 at the top, 1 at the bottom
        pygame.draw.line(
            surface,
            _lerp_colour(config.BACKGROUND_TOP, config.BACKGROUND_BOTTOM, t),  # blend top->bottom
            (0, y),
            (width, y),
        )

    # The vignette is four soft edge gradients. Corners are stamped by two of  # four soft edge gradients make the vignette
    # them, which is exactly the extra darkening a vignette wants there.
    overlay = pygame.Surface(key, pygame.SRCALPHA)  # drawn on top of the gradient
    edge = 150  # how many rows the top/bottom fade covers
    for i in range(edge):  # top and bottom edges
        alpha = int(64 * (1.0 - i / edge) ** 2)  # fades with distance from the edge
        pygame.draw.line(overlay, (0, 0, 0, alpha), (0, i), (width, i))  # top rows
        pygame.draw.line(
            overlay, (0, 0, 0, alpha), (0, height - 1 - i), (width, height - 1 - i)
        )
    side = 240  # how many columns the left/right fade covers
    for i in range(side):  # left and right edges
        alpha = int(52 * (1.0 - i / side) ** 2)  # same idea, slightly weaker
        pygame.draw.line(overlay, (0, 0, 0, alpha), (i, 0), (i, height))  # left columns
        pygame.draw.line(
            overlay, (0, 0, 0, alpha), (width - 1 - i, 0), (width - 1 - i, height)
        )
    surface.blit(overlay, (0, 0))  # stamp the vignette over the gradient

    _BACKGROUNDS[key] = surface  # cache it
    return surface


def _note_sprite(tint: tuple[int, int, int]) -> pygame.Surface:  # one note image per lane tint
    """A rounded, vertically shaded note with a glossy top cap."""
    key = (config.NOTE_WIDTH, config.NOTE_HEIGHT, *tint)  # cache key
    cached = _NOTE_SPRITES.get(key)  # built before?
    if cached is not None:
        return cached

    width, height = config.NOTE_WIDTH, config.NOTE_HEIGHT  # note size
    gradient = pygame.Surface((width, height))  # painted row by row
    top = _lighten(tint, 0.38)  # top of the shade
    bottom = _lerp_colour(tint, (10, 14, 24), 0.35)  # bottom of the shade
    for y in range(height):  # shade row by row
        pygame.draw.line(gradient, _lerp_colour(top, bottom, y / max(1, height - 1)), (0, y), (width, y))  # this row's shade

    # Round the corners by multiplying against a rounded mask.
    mask = pygame.Surface((width, height), pygame.SRCALPHA)  # a rounded mask
    mask.fill((0, 0, 0, 0))  # start fully transparent
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=6)  # rounded shape
    gradient = gradient.convert_alpha()  # needs per-pixel alpha to be masked
    gradient.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)  # multiply keeps only the rounded part

    # A bright cap along the top edge reads as the note's leading face.
    pygame.draw.line(gradient, (*_lighten(tint, 0.75), 220), (5, 1), (width - 5, 1), 2)  # glossy top cap

    _NOTE_SPRITES[key] = gradient  # cache it
    return gradient


def _note_glow(tint: tuple[int, int, int]) -> pygame.Surface:  # the halo under a note
    """A soft halo a little larger than the note, stamped underneath it."""
    pad = 14  # how far the halo sticks out
    key = (config.NOTE_WIDTH + pad * 2, config.NOTE_HEIGHT + pad * 2, *tint)  # halo is bigger than the note
    cached = _NOTE_GLOWS.get(key)  # built before?
    if cached is not None:
        return cached

    width, height = key[0], key[1]  # halo size
    glow = pygame.Surface((width, height), pygame.SRCALPHA)  # translucent
    # No blur in pygame: stacked translucent rounded rects, widest faintest.
    for step in range(4, 0, -1):  # stacked rects fake a blur
        alpha = int(26 * (5 - step) / 4)  # widest is faintest
        inset = pad - step * 3  # each layer a little tighter
        rect = pygame.Rect(inset, inset, width - inset * 2, height - inset * 2)  # the layer's rect
        pygame.draw.rect(glow, (*tint, alpha), rect, border_radius=8)  # stamp the layer
    _NOTE_GLOWS[key] = glow  # cache it
    return glow


def _spark_sprite(tint: tuple[int, int, int]) -> pygame.Surface:  # one particle of a hit burst
    """A small soft dot, one particle of a hit burst."""
    key = (12, 12, *tint)  # 12 px dot per tint
    cached = _SPARK_SPRITES.get(key)  # built before?
    if cached is not None:
        return cached
    spark = pygame.Surface((12, 12), pygame.SRCALPHA)  # small translucent dot
    pygame.draw.circle(spark, (*tint, 70), (6, 6), 5)  # soft outer
    pygame.draw.circle(spark, (*_lighten(tint, 0.6), 230), (6, 6), 2)  # bright centre
    _SPARK_SPRITES[key] = spark  # cache it
    return spark


def _ring_sprite(tint: tuple[int, int, int]) -> pygame.Surface:  # the ring of a hit burst
    """A glowing ring, scaled per frame for the hit burst."""
    key = (128, 128, *tint)  # big enough to scale down from
    cached = _RING_SPRITES.get(key)  # built before?
    if cached is not None:
        return cached
    ring = pygame.Surface((128, 128), pygame.SRCALPHA)  # translucent
    pygame.draw.circle(ring, (*tint, 46), (64, 64), 54, width=10)  # soft outer ring
    pygame.draw.circle(ring, (*_lighten(tint, 0.4), 220), (64, 64), 54, width=3)  # crisp inner ring
    _RING_SPRITES[key] = ring  # cache it
    return ring


def _panel_sprite(width: int, height: int, radius: int, alpha: int) -> pygame.Surface:  # translucent rounded panel
    """A translucent rounded panel, so screens can sit over a live background."""
    key = (width, height, radius, alpha)  # cache key
    cached = _PANELS.get(key)  # built before?
    if cached is not None:
        return cached
    panel_image = pygame.Surface((width, height), pygame.SRCALPHA)  # translucent
    rect = panel_image.get_rect()  # the whole sprite
    pygame.draw.rect(panel_image, (*config.PANEL, alpha), rect, border_radius=radius)  # tinted fill
    pygame.draw.rect(
        panel_image, (*config.LANE_EDGE, min(255, alpha + 40)), rect, width=1, border_radius=radius
    )
    _PANELS[key] = panel_image  # cache it
    return panel_image


# Sparks of a hit burst. The angles and speeds are fixed per lane from a seeded
# generator, so a burst is a pure function of its age: same age, same frame,
# which keeps headless screenshots deterministic.
_SPARK_COUNT = 12  # particles per burst
_SPARKS: dict[int, list[tuple[float, float, float, float]]] = {}  # per-lane burst layouts


def _sparks_for_lane(lane: int) -> list[tuple[float, float, float, float]]:  # burst angles fixed per lane, so the same age draws the same frame
    cached = _SPARKS.get(lane)  # laid out before?
    if cached is not None:
        return cached
    rng = random.Random(1000 + lane)  # seeded, so every run is identical
    sparks = []  # the layout being built
    for _ in range(_SPARK_COUNT):  # one entry per particle
        angle = rng.uniform(-math.pi, 0.0)  # upwards fan
        angle += rng.uniform(-0.5, 0.5)  # with some spread
        speed = rng.uniform(34.0, 96.0)  # px per second
        delay = rng.uniform(0.0, 0.25)  # staggered starts
        sparks.append((math.cos(angle), math.sin(angle), speed, delay))  # direction + speed + delay
    _SPARKS[lane] = sparks  # cache it
    return sparks


# --- small helpers ----------------------------------------------------------
def text(  # draw one line of plain text
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
    image = font(size, bold=bold, mono=mono).render(message, True, colour)  # render the string
    rect = image.get_rect()  # where it will land
    if align == "center":  # three alignment options
        rect.midtop = (int(position[0]), int(position[1]))  # centred horizontally
    elif align == "right":  # right edge at x
        rect.topright = (int(position[0]), int(position[1]))  # anchored right
    else:  # default: left edge at x
        rect.topleft = (int(position[0]), int(position[1]))  # anchored left
    surface.blit(image, rect)  # put it on screen
    return rect  # done


def glow_text(  # text with a soft halo (stamped copies of itself)
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
    face = font(size, bold=bold).render(message, True, colour)  # the text itself
    halo = font(size, bold=bold).render(message, True, glow)  # the same text in the glow colour
    pad = 6  # room for the halo
    composed = pygame.Surface((face.get_width() + pad * 2, face.get_height() + pad * 2), pygame.SRCALPHA)  # build the stamped image once
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (-1, 1), (1, -1)):  # 8 stamps around the text
        stamp = halo.copy()  # one halo copy
        stamp.set_alpha(46)  # faint
        composed.blit(stamp, (pad + dx, pad + dy))  # offset stamp
    composed.blit(face, (pad, pad))  # the text on top
    if scale != 1.0:  # pop animation resizes it
        composed = pygame.transform.smoothscale(  # smooth resize
            composed,
            (max(1, int(composed.get_width() * scale)), max(1, int(composed.get_height() * scale))),
        )
    if alpha < 255:  # fade via alpha
        composed = composed.copy()  # copy so set_alpha only hits this one
        composed.set_alpha(alpha)  # apply the fade
    rect = composed.get_rect()  # position it
    if align == "center":
        rect.midtop = (int(position[0]), int(position[1]))
    elif align == "midbottom":  # bottom edge anchored
        rect.midbottom = (int(position[0]), int(position[1]))  # grows upwards
    elif align == "right":
        rect.topright = (int(position[0]), int(position[1]))
    else:  # small combo stays white
        rect.topleft = (int(position[0]), int(position[1]))
    surface.blit(composed, rect)
    return rect


def panel(  # a rounded box; with alpha it uses the cached sprite
    surface: pygame.Surface,
    rect: pygame.Rect,
    fill: tuple[int, int, int] = config.PANEL,
    edge: Optional[tuple[int, int, int]] = config.LANE_EDGE,
    radius: int = 10,
    alpha: Optional[int] = None,
) -> None:
    """A rounded box. With alpha it is a translucent cached sprite instead."""
    if alpha is not None:  # translucent version
        surface.blit(_panel_sprite(rect.width, rect.height, radius, alpha), rect.topleft)  # stamped from cache
        return
    pygame.draw.rect(surface, fill, rect, border_radius=radius)  # opaque fill
    if edge is not None:  # optional outline
        pygame.draw.rect(surface, edge, rect, width=1, border_radius=radius)  # 1 px outline


# --- play screen ------------------------------------------------------------
def draw_background(surface: pygame.Surface) -> None:  # blit the cached gradient+vignette
    surface.blit(_background_sprite(), (0, 0))  # covers the whole window


def draw_beat_grid(  # faint lines showing where the beats are
    surface: pygame.Surface,
    song_ms: float,
    bpm: float,
    beats_per_bar: int = 4,
) -> None:
    """Faint lines showing where the beats are.

    This is the visual proof that the notes follow the song clock: the lines and
    the notes are placed with the same function.
    """
    if bpm <= 0:  # no bpm, no grid
        return
    beat_ms = 60_000.0 / bpm  # ms per beat
    # only draw the beats that can be on screen: from just below the judgement
    # line to a little above the top edge
    earliest = song_ms - (config.WINDOW_HEIGHT - config.JUDGE_LINE_Y) / (  # first beat that could be visible
        (config.JUDGE_LINE_Y - config.NOTE_SPAWN_Y) / config.APPROACH_MS
    )
    latest = song_ms + config.APPROACH_MS  # last beat that could be visible
    first_beat = int(earliest // beat_ms)  # beat index range
    last_beat = int(latest // beat_ms) + 1  # inclusive end
    left = int(lane_left()) - 24  # grid sticks out a little
    right = int(lane_left() + lanes_width()) + 24  # past the lanes
    for beat in range(first_beat, last_beat + 1):  # each beat in range
        if beat < 0:  # song has not started
            continue  # skip it
        y = int(y_for_time(beat * beat_ms, song_ms))  # same placement as the notes
        if y < -2 or y > config.WINDOW_HEIGHT + 2:  # off screen
            continue  # skip
        bar_line = beat % beats_per_bar == 0  # start of a bar?
        colour = config.JUDGE_LINE if bar_line else config.BEAT_GRID  # bar lines stronger
        width = 2 if bar_line else 1  # and thicker
        pygame.draw.line(surface, colour, (left, y), (right, y), width)  # the grid line


def draw_lanes(  # the four lane strips
    surface: pygame.Surface,
    flashes: Optional[dict[int, float]] = None,
    song_ms: float = 0.0,
) -> None:
    """Lane strips, lit from the judgement line for a moment after a key press."""
    for index in range(config.LANE_COUNT):  # one per lane
        rect = lane_rect(index)  # the strip
        tint = config.LANE_FILL if index % 2 == 0 else config.LANE_FILL_ALT  # alternate the shade
        pygame.draw.rect(surface, tint, rect)  # fill it

        age = None if not flashes else flashes.get(index)  # when this lane was last pressed
        if age is not None:  # pressed at some point
            age_ms = song_ms - age  # how long ago
            if 0 <= age_ms < 260:  # flash lasts 260 ms
                strength = 1.0 - age_ms / 260.0  # fades out
                # the flash is brightest at the line and thins as it climbs
                glow = pygame.Surface((rect.width, 160), pygame.SRCALPHA)  # the glow column
                for row in range(160):  # brightest at the line, thinning upwards
                    alpha = int(96 * strength * (row / 160.0))  # fade with height
                    pygame.draw.line(
                        glow, (*config.HIT_FLASH, alpha), (0, row), (rect.width, row)
                    )
                surface.blit(glow, (rect.x, int(config.JUDGE_LINE_Y) - 120))  # above the line

        pygame.draw.line(surface, config.LANE_EDGE, rect.topleft, rect.bottomleft, 1)  # left edge
        pygame.draw.line(surface, config.LANE_EDGE, rect.topright, rect.bottomright, 1)  # right edge


def _draw_hit_burst(surface: pygame.Surface, lane: int, age_ms: float) -> None:  # ring + sparks out of the receptor
    """Ring and sparks out of the receptor, a pure function of the flash's age."""
    if not 0 <= age_ms < 420:  # burst lasts 420 ms
        return
    progress = age_ms / 420.0  # 0..1 through the burst
    ease = 1.0 - (1.0 - progress) ** 3  # ease-out
    tint = LANE_TINTS[lane]  # the lane's colour
    centre = receptor_rect(lane).center  # burst origin

    ring = _ring_sprite(tint)  # the ring sprite
    radius = 20 + int(58 * ease)  # expands out
    scaled = pygame.transform.scale(ring, (radius * 2, radius * 2))  # scaled to the radius
    scaled.set_alpha(int(230 * (1.0 - progress)))  # fades as it expands
    surface.blit(scaled, scaled.get_rect(center=centre))  # centred on the receptor

    spark = _spark_sprite(tint)  # the particle sprite
    for dx, dy, speed, delay in _sparks_for_lane(lane):  # each particle
        local = progress - delay  # staggered starts
        if local <= 0:  # not launched yet
            continue  # not drawn
        distance = speed * (1.0 - (1.0 - min(1.0, local / (1.0 - delay))) ** 3)  # eased travel
        # sparks fall back a little as they fade, like embers
        drop = 26.0 * progress * progress  # sparks fall like embers
        x = centre[0] + dx * distance  # x from the burst angle
        y = centre[1] + dy * distance + drop  # y, plus the drop
        alpha = int(255 * (1.0 - progress))  # fade out
        stamp = spark.copy()  # copy, so alpha is per particle
        stamp.set_alpha(alpha)  # apply
        surface.blit(stamp, stamp.get_rect(center=(int(x), int(y))))  # draw it


def draw_judge_line(  # the line, its glow, and the four key slots
    surface: pygame.Surface,
    flashes: Optional[dict[int, float]] = None,
    song_ms: Optional[float] = None,  # needed to age the flashes
) -> None:
    """The judgement line, its glow, and the four key receptors on it.

    song_ms turns a flash timestamp into an age; without it the receptors draw
    in their resting state.
    """
    y = int(config.JUDGE_LINE_Y)  # the line's height
    left = int(lane_left()) - 16  # line sticks out a little
    right = int(lane_left() + lanes_width()) + 16  # both sides
    # layered strokes read as a glow without any blur
    overlay = pygame.Surface((right - left + 2, 14), pygame.SRCALPHA)  # the glow layer
    pygame.draw.line(overlay, (*config.HIT_FLASH, 34), (0, 7), (right - left, 7), 12)  # wide faint stroke
    pygame.draw.line(overlay, (*config.HIT_FLASH, 60), (0, 7), (right - left, 7), 6)  # tighter stronger stroke
    surface.blit(overlay, (left, y - 7))  # behind the line
    pygame.draw.line(surface, config.JUDGE_LINE, (left, y), (right, y), 3)  # the line itself

    for index in range(config.LANE_COUNT):  # the four receptors
        slot = receptor_rect(index)  # the key slot
        tint = LANE_TINTS[index]  # the lane's colour
        lit = 0.0  # 0 = resting, 1 = just pressed
        if flashes and song_ms is not None:  # can only age with a clock
            at = flashes.get(index)  # when it was pressed
            if at is not None:  # it was pressed
                age_ms = song_ms - at  # how long ago
                if 0 <= age_ms < 240:  # still lit
                    lit = 1.0 - age_ms / 240.0  # fades over 240 ms
                _draw_hit_burst(surface, index, age_ms)  # ring + sparks

        pygame.draw.rect(surface, config.RECEPTOR_FILL, slot, border_radius=9)  # slot fill
        if lit > 0.0:  # pressed recently
            flash_overlay = pygame.Surface((slot.width, slot.height), pygame.SRCALPHA)  # the lit overlay
            pygame.draw.rect(
                flash_overlay,  # lane colour at the lit strength
                (*tint, int(110 * lit)),
                flash_overlay.get_rect(),
                border_radius=9,
            )
            surface.blit(flash_overlay, slot.topleft)  # over the slot
        edge = _lerp_colour(config.RECEPTOR_EDGE, tint, lit)  # outline blends to the lane colour
        pygame.draw.rect(surface, edge, slot, width=2, border_radius=9)  # the outline


def draw_notes(surface: pygame.Surface, session: PlaySession, song_ms: float) -> None:  # the falling notes
    """Live notes, positioned from the song clock."""
    for note in session.notes:  # every note in the chart
        if note.state is not NoteState.PENDING:  # hit or missed already
            continue
        y = note.screen_y(song_ms)  # where it is now
        if y < -config.NOTE_HEIGHT or y > config.WINDOW_HEIGHT + config.NOTE_HEIGHT:  # off screen
            continue
        tint = LANE_TINTS[note.lane]  # lane colour
        sprite = _note_sprite(tint)  # the cached note image
        note_rect = sprite.get_rect(center=(int(lane_centre_x(note.lane)), int(y)))  # centred in its lane

        glow = _note_glow(tint)  # its halo
        glow_rect = glow.get_rect(center=note_rect.center)  # same centre

        # notes fade in over their first 80 px instead of popping at the edge
        fade = min(1.0, max(0.0, y / 80.0))  # fade in over the first 80 px
        if fade < 1.0:  # still fading in
            alpha = int(255 * fade)  # the fade amount
            glow = glow.copy()  # copies, so alpha is per note
            glow.set_alpha(alpha)  # halo fade
            sprite = sprite.copy()  # same for the note
            sprite.set_alpha(alpha)  # note fade
        surface.blit(glow, glow_rect)  # halo first
        surface.blit(sprite, note_rect)  # note on top

        # notes that are very close to their moment get a brighter edge
        distance = abs(note.time_ms - song_ms)  # how close to its moment
        if distance <= config.GOOD_MS:  # inside GOOD: highlight it
            edge = _lerp_colour(config.NOTE_EDGE, tint, distance / config.GOOD_MS)  # brighter as it nears
            pygame.draw.rect(surface, edge, note_rect, width=2, border_radius=6)  # the highlight edge


def draw_lane_labels(surface: pygame.Surface) -> None:  # D F J K inside the receptors
    """The key name inside each receptor."""
    for index, label in enumerate(config.LANE_LABELS):  # one label per lane
        slot = receptor_rect(index)  # its slot
        image = font(17, bold=True, mono=True).render(label, True, config.TEXT_MUTED)  # the letter
        surface.blit(image, image.get_rect(center=slot.center))  # centred in the slot


def draw_judgement_popup(  # PERFECT / GOOD / MISS word
    surface: pygame.Surface,
    verdict: Verdict,
    error_text: str,
    age_ms: float,
) -> None:
    """The word that flashes up after a press.

    It opens slightly overscaled, settles, rises a touch, then fades - the pop
    is what makes a PERFECT feel different from reading the same word flat.
    """
    if not 0 <= age_ms < 600:  # popup lasts 600 ms
        return
    fade = 1.0 - age_ms / 600.0  # fades over its life
    pop = 1.0 + 0.24 * max(0.0, 1.0 - age_ms / 150.0)  # opens big, settles
    rise = 10.0 * min(1.0, age_ms / 180.0)  # drifts up a little
    centre_x = config.WINDOW_WIDTH / 2.0  # centred
    colour = VERDICT_COLOURS[verdict]  # its colour
    alpha = int(255 * min(1.0, fade * 1.6))  # fade, but stay readable longer
    # anchored by its bottom edge, so the opening pop grows upwards and never
    # covers the error reading underneath
    glow_text(
        surface,
        verdict.value,  # the word, above the line
        (centre_x, config.JUDGE_LINE_Y - 96 - rise),
        size=32,  # popup size
        colour=colour,  # halo matches the word
        glow=colour,
        align="midbottom",  # anchored at the bottom
        scale=pop,  # the opening pop
        alpha=alpha,  # the fade
    )
    text(
        surface,
        error_text,  # the ms reading under the word
        (centre_x, config.JUDGE_LINE_Y - 86),  # just under the word
        size=15,  # smaller than the word
        colour=_lerp_colour(config.TEXT_MUTED, config.BACKGROUND_BOTTOM, 1.0 - fade),  # fades into the background
        mono=True,  # tabular numbers
        align="center",
    )


def draw_countdown(surface: pygame.Surface, remaining_ms: float) -> None:  # the 3, 2, 1 before the first note
    """The 3, 2, 1 before the first note.

    remaining_ms counts down to the first note. Each number swaps in as its
    second starts and pops open like the judgement popup.
    """
    number = max(1, min(3, int(remaining_ms // 1000) + 1))  # which number is showing
    # each number pops open for its first 160 ms, like the judgement popup
    age_in_second = 1000.0 - (remaining_ms % 1000.0)  # how long this number has been up
    pop = 1.0 + 0.30 * max(0.0, 1.0 - age_in_second / 160.0)  # pops on arrival
    fade = min(1.0, remaining_ms / 350.0)  # fades near the end
    centre_x = config.WINDOW_WIDTH / 2.0  # centred
    glow_text(
        surface,
        str(number),  # the digit, above the lanes
        (centre_x, 196),
        size=104,  # big
        colour=config.HIT_FLASH,  # same blue as the line
        glow=config.JUDGE_LINE,  # bluer halo
        scale=pop,  # the pop
        alpha=int(255 * fade),  # fade at the end
    )


def draw_go(surface: pygame.Surface, remaining_ms: float) -> None:  # GO, as the first note lands
    """GO, drawn over the same spot once the countdown has run out."""
    if remaining_ms <= 0:  # time is up
        return
    fade = min(1.0, remaining_ms / 320.0)
    pop = 1.0 + 0.20 * max(0.0, 1.0 - (800.0 - remaining_ms) / 160.0)  # same pop idea
    centre_x = config.WINDOW_WIDTH / 2.0  # centred
    glow_text(
        surface,
        "GO",  # the word, same spot
        (centre_x, 200),  # under the logo
        size=112,  # bigger than the numbers
        colour=config.PERFECT_COLOUR,  # green, like a PERFECT
        glow=config.PERFECT_COLOUR,  # matching halo
        scale=pop,  # pops each note
        alpha=int(255 * fade),
    )


def draw_play_hud(  # score, time, combo
    surface: pygame.Surface,
    session: PlaySession,
    song_ms: float,
    fps: Optional[float],
    chart_title: str,
) -> None:
    score = session.score  # the totals

    # song progress along the very top edge of the playfield
    length = max(1.0, float(session.chart.length_ms))  # song length, never zero
    fraction = min(1.0, max(0.0, song_ms / length))  # 0..1 through the song
    bar_left = int(lane_left())  # progress bar spans the lanes
    bar_right = int(lane_left() + lanes_width())  # right end
    pygame.draw.line(surface, config.LANE_EDGE, (bar_left, 5), (bar_right, 5), 3)  # the track
    if fraction > 0.0:  # nothing played yet
        fill_x = bar_left + int((bar_right - bar_left) * fraction)  # where we are
        pygame.draw.line(surface, config.HIT_FLASH, (bar_left, 5), (fill_x, 5), 3)  # the filled part
        pygame.draw.circle(surface, config.HIT_FLASH, (fill_x, 5), 3)  # the playhead dot

    text(surface, chart_title, (24, 18), size=17, colour=config.TEXT_MUTED)  # chart name
    text(surface, f"{song_ms / 1000.0:6.2f} s", (24, 42), size=22, colour=config.TEXT, mono=True)  # song clock
    if fps is not None:  # headless runs show no fps
        # a headless run has no frame rate worth reporting, so it shows nothing
        text(surface, f"{fps:5.1f} fps", (24, 70), size=14, colour=config.TEXT_MUTED, mono=True)  # fps under the clock

    glow_text(
        surface,
        f"{score.points:6d}",  # the score, top right
        (config.WINDOW_WIDTH - 24, 18),  # top right
        size=30,  # big
        colour=config.TEXT,  # plain white
        glow=config.JUDGE_LINE,  # blue halo
        align="right",  # right aligned
    )
    text(
        surface,
        f"{score.judged} / {score.note_count} notes",  # note progress under it
        (config.WINDOW_WIDTH - 24, 54),  # under the score
        size=14,  # small
        colour=config.TEXT_MUTED,
        mono=True,
        align="right",
    )
    if score.combo >= 2:  # combo only shows from 2 up
        # the counter pops on each judged note, using the same age as the popup
        age = song_ms - session.last_judged_song_ms  # pops with each judged note
        pop = 1.0 + 0.35 * max(0.0, 1.0 - age / 160.0)  # the pop
        if score.combo >= 30:  # big combo goes green
            colour = config.PERFECT_COLOUR  # like a PERFECT
        elif score.combo >= 10:  # medium combo goes blue
            colour = config.HIT_FLASH  # the flash blue
        else:
            colour = config.TEXT  # plain
        glow_text(
            surface,
            f"{score.combo} COMBO",  # under the judgement line
            (config.WINDOW_WIDTH / 2.0, config.JUDGE_LINE_Y + 30),  # under the line
            size=20,  # size
            colour=colour,
            glow=colour,
            align="center",
            scale=pop,
        )


def draw_debug_panel(  # the two clocks side by side
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
    lines = [  # the panel's rows
        "DEBUG  TAB to hide",
        f"tick clock   song {song_ms:8.1f} ms",
        f"             raw  {'' if ticks_ms is None else ticks_ms} ms",
        f"mixer get_pos {'' if mixer_pos_ms is None else mixer_pos_ms} ms",
        f"drift        {'' if drift_ms is None else f'{drift_ms:+.0f}'} ms",
        f"latency offset {latency_offset_ms:+.0f} ms",
        "fps          " + ("-" if fps is None else f"{fps:5.1f}"),
    ]
    width, height = 330, 14 + 20 * len(lines)  # panel size from the row count
    rect = pygame.Rect(24, config.WINDOW_HEIGHT - height - 24, width, height)  # bottom left
    panel(surface, rect, alpha=225)  # translucent so the lanes show through
    for row, line in enumerate(lines):  # each row
        colour = config.TEXT if row == 0 else config.TEXT_MUTED  # title row brighter
        text(surface, line, (rect.x + 14, rect.y + 10 + row * 20), size=14, colour=colour, mono=True)  # one row


# --- other screens ----------------------------------------------------------
def _draw_ambient_notes(surface: pygame.Surface, anim_ms: float) -> None:  # demo notes drifting behind the title
    """Demo notes drifting down the lanes behind the title content."""
    span = config.WINDOW_HEIGHT + 120  # travel range, a little past both edges
    for i in range(12):  # twelve drifting notes
        lane = i % config.LANE_COUNT  # spread across the lanes
        y = (anim_ms * 0.085 + i * 157.0) % span - 60.0  # steady fall, staggered start
        sprite = _note_sprite(LANE_TINTS[lane]).copy()  # copy, so the alpha is per note
        sprite.set_alpha(38)  # very faint
        surface.blit(sprite, sprite.get_rect(center=(int(lane_centre_x(lane)), int(y))))  # in its lane


def draw_title(  # the waiting screen
    surface: pygame.Surface,
    chart_title: str,
    note_count: int,
    calibration_ms: float,
    best_accuracy: Optional[float] = None,
    anim_ms: Optional[float] = None,
    chart_picker: tuple[bool, int, int] | None = None,  # (shown, index, count) when there is a choice
) -> None:
    """The waiting screen.

    anim_ms is an ambient clock from the caller, used only to drift the
    background notes and pulse the footer. Headless captures pass None and get
    the same still frame every time.
    """
    draw_background(surface)  # the gradient
    if anim_ms is not None:  # headless passes None
        _draw_ambient_notes(surface, anim_ms)  # the drifting notes
    draw_beat_grid(surface, 0.0, 120.0)  # a static grid for flavour
    centre_x = config.WINDOW_WIDTH / 2.0  # used a lot here

    glow_text(
        surface, "BEATLANES", (centre_x, 118), size=66, colour=config.TEXT, glow=config.HIT_FLASH  # big
    )
    text(
        surface,
        "a four lane keyboard rhythm prototype",  # the tagline
        (centre_x, 200),
        size=19,  # small
        colour=config.HIT_FLASH,
        align="center",
    )

    box = pygame.Rect(int(centre_x) - 350, 258, 700, 176)  # the info panel
    panel(surface, box, alpha=232)  # translucent, so the notes show
    rows = [  # the info rows
        ("Chart", f"{chart_title}  ({note_count} notes)"),
        ("Keys", "D   F   J   K   - one key per lane"),
        ("Play", "press the lane key as the note meets the line"),
        ("Windows", f"PERFECT +-{config.PERFECT_MS:.0f} ms   GOOD +-{config.GOOD_MS:.0f} ms"),
        ("Calibration", f"{calibration_ms:+.0f} ms"),
    ]
    for row, (label, value) in enumerate(rows):  # label + value per row
        y = box.y + 20 + row * 29  # one row per 29 px
        text(surface, label, (box.x + 22, y), size=15, colour=config.TEXT_MUTED, bold=True)  # the label
        text(surface, value, (box.x + 172, y), size=15, colour=config.TEXT, mono=True)  # the value

    if chart_picker is not None and chart_picker[0]:  # more than one chart installed
        _, index, count = chart_picker
        text(
            surface,
            f"< LEFT   chart {index + 1} of {count}   RIGHT >",
            (centre_x, box.bottom + 14),
            size=15,
            colour=config.HIT_FLASH,
            mono=True,
            align="center",
        )

    if best_accuracy is not None:  # only after a run
        text(
            surface,
            f"last run accuracy {best_accuracy:.1f}%",  # last run, if any
            (centre_x, box.bottom + 18),
            size=15,
            colour=config.TEXT_MUTED,
            mono=True,
            align="center",
        )

    footer = font(19, bold=True).render(  # the key hints
        "SPACE  start      C  calibrate      ESC  quit", True, config.TEXT
    )
    if anim_ms is not None:  # pulse only with a clock
        footer.set_alpha(int(200 + 55 * math.sin(anim_ms / 420.0)))  # gentle pulse
    surface.blit(footer, footer.get_rect(midtop=(int(centre_x), config.WINDOW_HEIGHT - 92)))  # near the bottom
    text(
        surface,
        "TAB  debug overlay while playing",  # the extra hint
        (centre_x, config.WINDOW_HEIGHT - 62),
        size=15,
        colour=config.TEXT_MUTED,
        align="center",
    )


def draw_calibration(  # the metronome screen
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
    centre_x = config.WINDOW_WIDTH / 2.0  # used a lot
    glow_text(
        surface, "CALIBRATION", (centre_x, 66), size=36, colour=config.TEXT, glow=config.JUDGE_LINE  # the heading
    )
    text(
        surface,
        "tap D on every click - the offset is measured from your taps",  # the instruction
        (centre_x, 118),
        size=17,
        colour=config.TEXT_MUTED,
        align="center",
    )

    # the ring snaps back to wide on each click and closes in through the beat
    pulse = 1.0 - beat_phase  # 1 at the click, 0 at the next
    radius = 60 + int(26 * pulse)  # the ring closes in
    ring_overlay = pygame.Surface((220, 220), pygame.SRCALPHA)  # a soft ring behind
    pygame.draw.circle(ring_overlay, (*config.HIT_FLASH, int(30 + 50 * pulse)), (110, 110), radius, width=8)  # brightest at the click
    surface.blit(ring_overlay, (int(centre_x) - 110, 300 - 110))  # around the circle
    pygame.draw.circle(surface, config.LANE_FILL_ALT, (int(centre_x), 300), 78)  # the dark disc
    pygame.draw.circle(surface, config.HIT_FLASH, (int(centre_x), 300), radius, width=4)  # the moving ring
    pygame.draw.circle(surface, config.JUDGE_LINE, (int(centre_x), 300), 8)  # the centre dot

    text(
        surface,
        f"{min(beat_index, total_beats)} / {total_beats}",  # clicks done
        (centre_x, 400),  # under the circle
        size=26,  # medium
        colour=config.TEXT,
        mono=True,
        align="center",
    )

    collected = list(offsets)  # the taps so far
    if collected:  # nothing until the first tap
        mean = sum(collected) / len(collected)  # running average
        text(
            surface,
            f"taps {len(collected)}   running average {mean:+.0f} ms",  # live stats
            (centre_x, 442),
            size=17,
            colour=config.TEXT_MUTED,
            mono=True,
            align="center",
        )
        # one tick per tap, 1 px per ms, so the spread is visible
        base_y = 486  # the tick line
        pygame.draw.line(surface, config.LANE_EDGE, (int(centre_x) - 200, base_y), (int(centre_x) + 200, base_y), 1)  # the axis
        for value in collected:  # one tick per tap
            x = centre_x + max(-190, min(190, value))  # 1 px per ms, clamped
            colour = config.PERFECT_COLOUR if abs(value) <= config.PERFECT_MS else config.GOOD_COLOUR  # colour by window
            pygame.draw.line(surface, colour, (int(x), base_y - 10), (int(x), base_y + 10), 2)  # the tick

    if current_offset_ms is not None:  # after the first tap
        text(
            surface,
            f"last tap {current_offset_ms:+.0f} ms",  # the last tap
            (centre_x, 512),
            size=15,
            colour=config.TEXT_MUTED,
            mono=True,
            align="center",
        )
    text(
        surface,
        "ESC  cancel",  # how to leave
        (centre_x, config.WINDOW_HEIGHT - 60),
        size=16,
        colour=config.TEXT_MUTED,
        align="center",
    )


def draw_results(  # the results screen
    surface: pygame.Surface,
    session: PlaySession,
    log_name: str,
    chart_title: str,
) -> None:
    draw_background(surface)
    draw_beat_grid(surface, session.chart.length_ms, session.chart.bpm)  # grid at the end position
    centre_x = config.WINDOW_WIDTH / 2.0

    score = session.score  # the run's totals
    rank_colour = RANK_COLOURS.get(score.rank, config.HIT_FLASH)  # colour for this rank
    glow_text(surface, "RESULTS", (centre_x, 48), size=40, colour=config.TEXT, glow=config.JUDGE_LINE)  # the heading
    text(surface, chart_title, (centre_x, 102), size=16, colour=config.TEXT_MUTED, align="center")  # which chart

    box = pygame.Rect(int(centre_x) - 250, 138, 500, 330)  # the results panel
    panel(surface, box, alpha=235)  # translucent

    # rank badge: a glowing ring with an accuracy arc around the letter
    badge_centre = (box.x + 70, box.y + 96)  # the rank badge
    badge_overlay = pygame.Surface((160, 160), pygame.SRCALPHA)  # the badge's soft halo
    pygame.draw.circle(badge_overlay, (*rank_colour, 34), (80, 80), 56, width=10)  # faint ring
    surface.blit(badge_overlay, (badge_centre[0] - 80, badge_centre[1] - 80))  # behind the badge
    pygame.draw.circle(surface, config.LANE_EDGE, badge_centre, 54, width=4)  # the badge circle
    arc_rect = pygame.Rect(0, 0, 108, 108)  # the accuracy arc
    arc_rect.center = badge_centre  # around the badge
    pygame.draw.arc(  # the arc fills with accuracy
        surface,
        rank_colour,
        arc_rect,
        -math.pi / 2,
        -math.pi / 2 + 2 * math.pi * (score.accuracy / 100.0),
        width=4,
    )
    letter = font(72, bold=True).render(score.rank, True, rank_colour)  # the big letter
    surface.blit(letter, letter.get_rect(center=badge_centre))  # in the badge

    text(
        surface,
        f"{score.accuracy:.1f}%",  # accuracy under the badge
        (badge_centre[0], badge_centre[1] + 66),
        size=22,
        colour=config.TEXT,
        mono=True,
        align="center",
    )
    text(
        surface,
        f"{score.points} / {score.max_points}",  # points under that
        (badge_centre[0], badge_centre[1] + 94),
        size=15,
        colour=config.TEXT_MUTED,
        mono=True,
        align="center",
    )

    rows = [  # the three verdict counts
        ("PERFECT", score.perfect, config.PERFECT_COLOUR),
        ("GOOD", score.good, config.GOOD_COLOUR),
        ("MISS", score.miss, config.MISS_COLOUR),
    ]
    for row, (label, value, colour) in enumerate(rows):  # one row each
        y = box.y + 44 + row * 50  # spaced rows
        text(surface, label, (box.x + 190, y), size=19, colour=colour, bold=True, mono=True)  # the label
        text(surface, str(value), (box.right - 30, y), size=19, colour=colour, mono=True, align="right")  # the count

    text(
        surface,
        f"best combo {score.best_combo}",  # best combo
        (box.x + 190, box.y + 200),
        size=15,
        colour=config.TEXT_MUTED,
        mono=True,
    )
    text(
        surface,
        f"early / late {score.early_taps} / {score.late_taps}",  # early vs late
        (box.x + 190, box.y + 224),
        size=15,
        colour=config.TEXT_MUTED,
        mono=True,
    )
    text(
        surface,
        f"stray taps {score.stray_taps}",  # stray presses
        (box.x + 190, box.y + 248),
        size=15,
        colour=config.TEXT_MUTED,
        mono=True,
    )

    # verdict distribution strip: the shape of the run at a glance
    judged = max(1, score.judged)  # avoid dividing by zero
    bar = pygame.Rect(box.x + 190, box.y + 288, box.right - 30 - (box.x + 190), 8)  # the strip
    pygame.draw.rect(surface, config.LANE_EDGE, bar, border_radius=4)  # its background
    x = bar.x  # fill starts here
    for count, colour in (  # perfect then good then miss
        (score.perfect, config.PERFECT_COLOUR),
        (score.good, config.GOOD_COLOUR),
        (score.miss, config.MISS_COLOUR),
    ):
        width = int(bar.width * count / judged)  # this verdict's share
        if width > 0:  # skip empty shares
            pygame.draw.rect(surface, colour, pygame.Rect(x, bar.y, width, bar.height), border_radius=4)  # the segment
        x += width  # next segment follows

    text(
        surface,
        f"tap log  {log_name}",  # which log file
        (centre_x, box.bottom + 18),
        size=15,
        colour=config.TEXT_MUTED,
        mono=True,
        align="center",
    )
    text(
        surface,
        "R  play again        T  title        ESC  quit",  # the key hints
        (centre_x, config.WINDOW_HEIGHT - 62),
        size=18,
        colour=config.TEXT,
        bold=True,
        align="center",
    )
