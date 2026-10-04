# we need sound. a mixer, click and song
# report any errors that happen, dont raise. can play with out sound

import numpy as np  # used when creating the click sample
import pygame
from pathlib import Path  # what kind of path to use for the song

from . import config  # path to the song

MIXER_SETTINGS = {"frequency": 44100, "size": -16, "channels": 2, "buffer": 512}  # use default settings


def init_mixer(**overrides) -> bool:
    # open sound device, false will allow you to run with no sound
    settings = dict(MIXER_SETTINGS)
    settings.update(overrides)  # used so tests can override
    try:
        pygame.mixer.init(**settings)
    except pygame.error:  # no sound card on pc or a server
        return False
    return pygame.mixer.get_init() is not None


def mixer_ready() -> bool:  # returns true if mixer was able to open
    return pygame.mixer.get_init() is not None


def make_click(frequency: float = 1320.0, duration_ms: float = 26.0, volume: float = 0.45):
    # a short sine blip for the calibration metronome
    if not mixer_ready():  # no mixer, no click
        return None
    rate, _, channels = pygame.mixer.get_init()  # make it the same format as our mixer
    frames = int(rate * duration_ms / 1000.0)  # amount of samples in our click
    if frames <= 0:
        return None
    t = np.arange(frames) / rate  # this will be in seconds
    envelope = np.exp(-t / (duration_ms / 3000.0))  # we want our click to die off fast
    wave = np.sin(2.0 * np.pi * frequency * t) * envelope * volume
    samples = np.int16(np.clip(wave, -1.0, 1.0) * 32767)  # since our mixer uses 16 bit
    if channels == 2:  # copy over to make it stereo
        samples = np.repeat(samples[:, None], 2, axis=1)
    try:
        return pygame.sndarray.make_sound(np.ascontiguousarray(samples))
    except (pygame.error, ValueError):  # if your mixer format is weird
        return None


def start_song(path: Path | str | None = None, volume: float = 0.75) -> bool:
    # loads song and starts playing it. false means no music just a clock
    target = Path(path) if path is not None else config.SONG_PATH
    if not mixer_ready() or not target.exists():  # couldnt find device or file
        return False
    try:
        pygame.mixer.music.load(str(target))
        pygame.mixer.music.set_volume(volume)
        pygame.mixer.music.play()
    except pygame.error:  # file could not be read
        return False
    return True


def stop_song() -> None:  # if the music is playing stop it
    if mixer_ready():
        try:
            pygame.mixer.music.stop()
        except pygame.error:  # already stopped
            pass


def music_position_ms() -> int:  # will return mixers position or -1
    if not mixer_ready():
        return -1
    try:
        return pygame.mixer.music.get_pos()
    except pygame.error:  # mixer died while playing
        return -1
