"""BeatLanes - shared settings.

Everything the game and the tools both need to agree on lives here. The chart
generator, the tests and the renderer all read these values, so they cannot
drift apart.

Nothing in this module imports pygame, which keeps the pure logic modules
(judge, chart, scoring, session) importable in a plain Python shell.
"""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent

# --- files ------------------------------------------------------------------
ASSET_DIR = PROJECT_DIR / "assets"
CHART_DIR = PROJECT_DIR / "charts"
LOG_DIR = PROJECT_DIR / "logs"
SONG_PATH = ASSET_DIR / "beatlanes_120.ogg"
CHART_PATH = CHART_DIR / "beatlanes_120.json"
CALIBRATION_PATH = PROJECT_DIR / "calibration.json"

# --- window -----------------------------------------------------------------
WINDOW_WIDTH = 960
WINDOW_HEIGHT = 640
FPS = 60
CAPTION = "BeatLanes - 4 lane keyboard rhythm prototype"

# --- lanes ------------------------------------------------------------------
LANE_COUNT = 4
# lower case, matching pygame.key.name() so the event loop can look a lane up
LANE_KEY_TO_INDEX = {"d": 0, "f": 1, "j": 2, "k": 3}
LANE_LABELS = ("D", "F", "J", "K")

LANE_WIDTH = 120
LANE_GAP = 6
NOTE_WIDTH = LANE_WIDTH - 18
NOTE_HEIGHT = 20

# A note is on screen for this long before its target time, so a note is at the
# judgement line exactly when the song clock says its target time has arrived.
APPROACH_MS = 1500.0
NOTE_SPAWN_Y = 0.0
JUDGE_LINE_Y = 520.0

# --- judgement windows (milliseconds) --------------------------------------
PERFECT_MS = 50.0
GOOD_MS = 120.0

# --- scoring ----------------------------------------------------------------
POINTS_PERFECT = 100
POINTS_GOOD = 50
POINTS_MISS = 0

# --- calibration ------------------------------------------------------------
CALIBRATION_BEATS = 16
CALIBRATION_BEAT_MS = 500.0  # 120 BPM
# A tap further than this from the nearest click is treated as a misfire and
# left out of the average. It has to stay below half a beat (250 ms), otherwise
# it can never reject anything: every moment in time is within half a beat of
# some click. 180 ms leaves room for a sloppy human tap and still catches a
# double tap or a tap on the wrong click.
CALIBRATION_TOLERANCE_MS = 180.0

# --- colours (RGB) ----------------------------------------------------------
BACKGROUND = (11, 17, 28)
# The playfield background is a vertical gradient between these two stops,
# with a soft vignette drawn over it. BACKGROUND above stays as the flat
# fallback for anything that cannot take a gradient.
BACKGROUND_TOP = (16, 24, 40)
BACKGROUND_BOTTOM = (7, 10, 18)
LANE_FILL = (24, 34, 54)
LANE_FILL_ALT = (30, 42, 66)
LANE_EDGE = (38, 52, 78)
JUDGE_LINE = (47, 111, 237)
BEAT_GRID = (26, 36, 56)
NOTE_FILL = (126, 196, 255)
NOTE_EDGE = (198, 232, 255)
HIT_FLASH = (93, 214, 255)
# The key slots sitting on the judgement line.
RECEPTOR_EDGE = (86, 116, 158)
RECEPTOR_FILL = (15, 22, 36)
TEXT = (228, 236, 248)
TEXT_MUTED = (128, 144, 170)
PERFECT_COLOUR = (118, 230, 190)
GOOD_COLOUR = (240, 208, 118)
MISS_COLOUR = (236, 112, 112)
PANEL = (16, 24, 38)
