# Used between the game and some tools.
# Will be used on both ends so there is only one copy of things like judgement windows.

from pathlib import Path

# the directory this file is in and the directory above it which will be our project folder
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent

# --- files ------------------------------------------------------------------
ASSET_DIR = PROJECT_DIR / "assets"  # the song that gets created goes here
CHART_DIR = PROJECT_DIR / "charts"  # where the chart files will be stored
LOG_DIR = PROJECT_DIR / "logs"  # taps are logged here when playing a song
SONG_PATH = ASSET_DIR / "beatlanes_120.ogg"  # background music
CHART_PATH = CHART_DIR / "beatlanes_120.json"  # chart that was generated
CHART_2_PATH = CHART_DIR / "hand_120.json"  # chart made manually
CHARTS = (CHART_PATH, CHART_2_PATH)  # changed using the LEFT RIGHT arrow keys on title screen
CALIBRATION_PATH = PROJECT_DIR / "calibration.json"  # stores your latency correction

# --- window -----------------------------------------------------------------
WINDOW_WIDTH = 960  # pixels wide the window is
WINDOW_HEIGHT = 640  # pixels tall the window is
FPS = 60  # caps fps
CAPTION = "BeatLanes - 4 lane keyboard rhythm prototype"  # name of window

# --- lanes ------------------------------------------------------------------
LANE_COUNT = 4  # we have 4 lanes corresponding to each key
# these are lowercase to allow pygame.key.name() to reference a lane
LANE_KEY_TO_INDEX = {"d": 0, "f": 1, "j": 2, "k": 3}
LANE_LABELS = ("D", "F", "J", "K")  # will be displayed below each lane

LANE_WIDTH = 120  # pixel width of each lane
LANE_GAP = 6  # space between each lane
NOTE_WIDTH = LANE_WIDTH - 18  # notes will not take up the full width of the lane
NOTE_HEIGHT = 20  # pixel height of each note

# A note is on screen for this long before its target time, so a note is at the
# judgement line exactly when the song clock says its target time has arrived.
APPROACH_MS = 1500.0  # amount of time on screen until target time of the note
NOTE_SPAWN_Y = 0.0  # spawned from the top of the screen
JUDGE_LINE_Y = 520.0  # player judgement line

# --- judgement windows (milliseconds) --------------------------------------
PERFECT_MS = 50.0  # if the absolute error is less than or equal to this you get a PERFECT
GOOD_MS = 120.0  # if the absolute error is less than or equal to this you get a GOOD any more will not be registered

# --- scoring ----------------------------------------------------------------
POINTS_PERFECT = 100  # value of a PERFECT hit
POINTS_GOOD = 50  # value of a GOOD hit
POINTS_MISS = 0  # you dont get any points for missing

# --- calibration ------------------------------------------------------------
CALIBRATION_BEATS = 16  # clicks in the metronome test
CALIBRATION_BEAT_MS = 500.0  # one click every 500 ms, i.e. 120 BPM
# taps further than this from the nearest click are ignored. Must stay below
# half a beat (250 ms), otherwise it could never reject anything.
CALIBRATION_TOLERANCE_MS = 180.0

# --- colours (RGB) ----------------------------------------------------------
BACKGROUND = (11, 17, 28)  # used as a general colour when nothing else fits
BACKGROUND_TOP = (16, 24, 40)  # the top half of our gradient behind the lanes
BACKGROUND_BOTTOM = (7, 10, 18)  # bottom half
LANE_FILL = (24, 34, 54)  # colour of even lanes
LANE_FILL_ALT = (30, 42, 66)  # colour of odd lanes
LANE_EDGE = (38, 52, 78)  # border around each lane
JUDGE_LINE = (47, 111, 237)  # judgement line colour
BEAT_GRID = (26, 36, 56)  # beat markers
NOTE_FILL = (126, 196, 255)  # standard note colour
NOTE_EDGE = (198, 232, 255)  # edge will change to this colour close to target time
HIT_FLASH = (93, 214, 255)  # used when flashing a lane and displaying your combo
RECEPTOR_EDGE = (86, 116, 158)  # default outline colour for your keys
RECEPTOR_FILL = (15, 22, 36)  # default inner colour of your keys
TEXT = (228, 236, 248)  # text
TEXT_MUTED = (128, 144, 170)  # darker text
PERFECT_COLOUR = (118, 230, 190)  # text for PERFECT
GOOD_COLOUR = (240, 208, 118)  # text for GOOD
MISS_COLOUR = (236, 112, 112)  # text for MISS
PANEL = (16, 24, 38)  # text boxes
