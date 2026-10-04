# Sound: mixer setup, the metronome click, and the song.
# Every failure here is reported, not raised - the game can run without sound.

import numpy as np  # only for building the click sample
import pygame
from pathlib import Path  # the song path type

from . import config  # the song path

MIXER_SETTINGS = {"frequency": 44100, "size": -16, "channels": 2, "buffer": 512}  # standard settings


def init_mixer(**overrides) -> bool:
    # open the audio device; False means 'run without sound'
    settings = dict(MIXER_SETTINGS)
    settings.update(overrides)  # tests can override the settings
    try:
        pygame.mixer.init(**settings)
    except pygame.error:  # no sound card, or a headless machine
        return False
    return pygame.mixer.get_init() is not None


def mixer_ready() -> bool:  # True when the mixer opened
    return pygame.mixer.get_init() is not None


def make_click(frequency: float = 1320.0, duration_ms: float = 26.0, volume: float = 0.45):
    # a short sine blip for the calibration metronome
    if not mixer_ready():  # no mixer, no click
        return None
    rate, _, channels = pygame.mixer.get_init()  # match the mixer's format
    frames = int(rate * duration_ms / 1000.0)  # sample count for the click
    if frames <= 0:
        return None
    t = np.arange(frames) / rate  # time axis in seconds
    envelope = np.exp(-t / (duration_ms / 3000.0))  # fast decay makes it a click
    wave = np.sin(2.0 * np.pi * frequency * t) * envelope * volume
    samples = np.int16(np.clip(wave, -1.0, 1.0) * 32767)  # 16-bit, as the mixer wants
    if channels == 2:  # duplicate to stereo
        samples = np.repeat(samples[:, None], 2, axis=1)
    try:
        return pygame.sndarray.make_sound(np.ascontiguousarray(samples))
    except (pygame.error, ValueError):  # odd mixer format
        return None


def start_song(path: Path | str | None = None, volume: float = 0.75) -> bool:
    # load and start the song; False means 'no music, clock only'
    target = Path(path) if path is not None else config.SONG_PATH
    if not mixer_ready() or not target.exists():  # no device or no file
        return False
    try:
        pygame.mixer.music.load(str(target))
        pygame.mixer.music.set_volume(volume)
        pygame.mixer.music.play()
    except pygame.error:  # unreadable file
        return False
    return True


def stop_song() -> None:  # stop the music if it is playing
    if mixer_ready():
        try:
            pygame.mixer.music.stop()
        except pygame.error:  # already gone
            pass


def music_position_ms() -> int:  # the mixer's own position, or -1
    if not mixer_ready():
        return -1
    try:
        return pygame.mixer.music.get_pos()
    except pygame.error:  # mixer went away mid-run
        return -1
