# Settings shared by the game and the tools.
# Both sides read this file so numbers like the judgement windows only exist once.

from pathlib import Path

# folder of this file, and the project folder above it
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent

# --- files ------------------------------------------------------------------
ASSET_DIR = PROJECT_DIR / "assets"  # where the generated song lives
CHART_DIR = PROJECT_DIR / "charts"  # where the note charts live
LOG_DIR = PROJECT_DIR / "logs"  # tap logs get written here during a run
SONG_PATH = ASSET_DIR / "beatlanes_120.ogg"  # the backing track
CHART_PATH = CHART_DIR / "beatlanes_120.json"  # the generated chart
CHART_2_PATH = CHART_DIR / "hand_120.json"  # a second chart, written by hand
CHARTS = (CHART_PATH, CHART_2_PATH)  # picked with LEFT/RIGHT on the title screen
CALIBRATION_PATH = PROJECT_DIR / "calibration.json"  # saved latency offset

# --- window -----------------------------------------------------------------
WINDOW_WIDTH = 960  # window width in pixels
WINDOW_HEIGHT = 640  # window height in pixels
FPS = 60  # frame rate cap
CAPTION = "BeatLanes - 4 lane keyboard rhythm prototype"  # window title

# --- lanes ------------------------------------------------------------------
LANE_COUNT = 4  # four lanes, one per key
# lower case keys, so pygame.key.name() can look a lane up directly
LANE_KEY_TO_INDEX = {"d": 0, "f": 1, "j": 2, "k": 3}
LANE_LABELS = ("D", "F", "J", "K")  # what is printed under each lane

LANE_WIDTH = 120  # lane width in pixels
LANE_GAP = 6  # gap between lanes
NOTE_WIDTH = LANE_WIDTH - 18  # notes are slightly narrower than their lane
NOTE_HEIGHT = 20  # note height in pixels

# A note is on screen for this long before its target time, so a note is at the
# judgement line exactly when the song clock says its target time has arrived.
APPROACH_MS = 1500.0
NOTE_SPAWN_Y = 0.0  # notes appear at the top edge
JUDGE_LINE_Y = 520.0  # the line the player aims at

# --- judgement windows (milliseconds) --------------------------------------
PERFECT_MS = 50.0  # abs(error) at most this -> PERFECT
GOOD_MS = 120.0  # abs(error) at most this -> GOOD, further -> not counted

# --- scoring ----------------------------------------------------------------
POINTS_PERFECT = 100  # points for a PERFECT
POINTS_GOOD = 50  # points for a GOOD
POINTS_MISS = 0  # a miss scores nothing

# --- calibration ------------------------------------------------------------
CALIBRATION_BEATS = 16  # clicks in the metronome test
CALIBRATION_BEAT_MS = 500.0  # one click every 500 ms, i.e. 120 BPM
# taps further than this from the nearest click are ignored. Must stay below
# half a beat (250 ms), otherwise it could never reject anything.
CALIBRATION_TOLERANCE_MS = 180.0

# --- colours (RGB) ----------------------------------------------------------
BACKGROUND = (11, 17, 28)  # flat fallback colour
BACKGROUND_TOP = (16, 24, 40)  # gradient top behind the playfield
BACKGROUND_BOTTOM = (7, 10, 18)  # gradient bottom
LANE_FILL = (24, 34, 54)  # even lanes
LANE_FILL_ALT = (30, 42, 66)  # odd lanes, slightly lighter
LANE_EDGE = (38, 52, 78)  # thin edge lines between lanes
JUDGE_LINE = (47, 111, 237)  # the judgement line
BEAT_GRID = (26, 36, 56)  # faint lines showing the beats
NOTE_FILL = (126, 196, 255)  # default note colour
NOTE_EDGE = (198, 232, 255)  # bright edge for notes near their moment
HIT_FLASH = (93, 214, 255)  # lane flash / combo colour
RECEPTOR_EDGE = (86, 116, 158)  # key slot outline at rest
RECEPTOR_FILL = (15, 22, 36)  # key slot fill at rest
TEXT = (228, 236, 248)  # main text
TEXT_MUTED = (128, 144, 170)  # dimmer text
PERFECT_COLOUR = (118, 230, 190)  # PERFECT word
GOOD_COLOUR = (240, 208, 118)  # GOOD word
MISS_COLOUR = (236, 112, 112)  # MISS word
PANEL = (16, 24, 38)  # overlay panels
