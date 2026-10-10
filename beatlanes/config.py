# Used between the game and some tools.
# Will be used on both ends so there is only one copy of things like judgement windows.

from pathlib import Path

# the directory this file is in and the directory above it which will be our project folder
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent  # repo root, one level above the package

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
CAPTION = "BeatLanes - four lane rhythm prototype"  # name of window

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
# week 11 palette: a deeper indigo night with cyan / violet / pink accents.
# the verdict colours did not change, they are what the player learned.
BACKGROUND = (9, 11, 24)  # used as a general colour when nothing else fits
BACKGROUND_TOP = (22, 19, 52)  # the top of the gradient, a violet night
BACKGROUND_BOTTOM = (5, 6, 15)  # the bottom, almost black
HIGHWAY = (10, 13, 30)  # the strip the four lanes sit on
LANE_FILL = (15, 19, 40)  # colour of even lanes
LANE_FILL_ALT = (19, 24, 48)  # colour of odd lanes
LANE_EDGE = (46, 56, 96)  # border around each lane and panel
JUDGE_LINE = (66, 132, 255)  # the deeper blue, used for halos
BEAT_GRID = (30, 38, 72)  # beat markers
NOTE_FILL = (126, 196, 255)  # standard note colour
NOTE_EDGE = (226, 244, 255)  # edge will change to this colour close to target time
HIT_FLASH = (93, 214, 255)  # the main cyan accent
ACCENT_VIOLET = (170, 128, 255)  # second accent, the middle of the logo gradient
ACCENT_PINK = (255, 128, 200)  # third accent, the end of the logo gradient
RECEPTOR_EDGE = (78, 96, 150)  # default outline colour for your keys
RECEPTOR_FILL = (17, 21, 44)  # default inner colour of your keys
TEXT = (236, 242, 255)  # text
TEXT_MUTED = (132, 144, 186)  # darker text
TEXT_DIM = (84, 94, 136)  # the quietest text, footnotes and version tags
PERFECT_COLOUR = (118, 230, 190)  # text for PERFECT
GOOD_COLOUR = (240, 208, 118)  # text for GOOD
MISS_COLOUR = (236, 112, 112)  # text for MISS
PANEL = (14, 18, 38)  # text boxes
