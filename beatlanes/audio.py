"""Sound.

Two sounds are needed: the song, streamed from an OGG file, and a short
metronome click for the calibration test. The click is generated here with
numpy rather than shipped as a file, because a click is a sine wave with a
decay on it and there is no reason to carry a WAV around for that.

If the mixer cannot be opened at all (no sound card, or a headless machine) the
failure is reported instead of raised: the game still runs on the tick clock
alone, which is the fallback the plan allows for.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pygame

from . import config

MIXER_SETTINGS = {"frequency": 44100, "size": -16, "channels": 2, "buffer": 512}


def init_mixer(**overrides) -> bool:
    """Open the audio device. False means 'run without sound'."""
    settings = dict(MIXER_SETTINGS)
    settings.update(overrides)
    try:
        pygame.mixer.init(**settings)
    except pygame.error:
        return False
    return pygame.mixer.get_init() is not None


def mixer_ready() -> bool:
    return pygame.mixer.get_init() is not None


def make_click(frequency: float = 1320.0, duration_ms: float = 26.0, volume: float = 0.45):
    """A short sine blip for the calibration metronome."""
    if not mixer_ready():
        return None
    rate, _, channels = pygame.mixer.get_init()
    frames = int(rate * duration_ms / 1000.0)
    if frames <= 0:
        return None
    t = np.arange(frames) / rate
    envelope = np.exp(-t / (duration_ms / 3000.0))
    wave = np.sin(2.0 * np.pi * frequency * t) * envelope * volume
    samples = np.int16(np.clip(wave, -1.0, 1.0) * 32767)
    if channels == 2:
        samples = np.repeat(samples[:, None], 2, axis=1)
    try:
        return pygame.sndarray.make_sound(np.ascontiguousarray(samples))
    except (pygame.error, ValueError):
        return None


def start_song(path: Optional[Path | str] = None, volume: float = 0.75) -> bool:
    """Load and start the chart's song. False means 'no music, clock only'."""
    target = Path(path) if path is not None else config.SONG_PATH
    if not mixer_ready() or not target.exists():
        return False
    try:
        pygame.mixer.music.load(str(target))
        pygame.mixer.music.set_volume(volume)
        pygame.mixer.music.play()
    except pygame.error:
        return False
    return True


def stop_song() -> None:
    if mixer_ready():
        try:
            pygame.mixer.music.stop()
        except pygame.error:
            pass


def music_position_ms() -> int:
    """The mixer's own song position, or -1 when nothing is playing."""
    if not mixer_ready():
        return -1
    try:
        return pygame.mixer.music.get_pos()
    except pygame.error:
        return -1
