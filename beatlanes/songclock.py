"""Song time.

A rhythm game needs one answer to "where are we in the song?" and it needs it
on every frame and every key press. Two readings are available in Pygame and
BeatLanes uses both, but only one of them is trusted.

Primary clock - the tick clock
    pygame.time.get_ticks() sampled at the moment the key press is handled,
    minus the tick reading taken when the music started, minus a calibration
    offset measured with the metronome test. get_ticks() counts milliseconds
    since Pygame was initialised, so the subtraction is what turns it into song
    time.

Secondary reading - the mixer
    pygame.mixer.music.get_pos() reports how long the music has been playing.
    The Pygame documentation only promises that much, and it returns -1 when
    nothing is playing, so BeatLanes samples it to compare against the primary
    clock but never judges a tap with it.

The two providers are injected instead of imported so this class can be tested
without audio hardware.
"""

from __future__ import annotations

from typing import Callable, Optional

TickProvider = Callable[[], int]
MixerPosProvider = Callable[[], int]


def _pygame_ticks() -> int:
    import pygame

    return pygame.time.get_ticks()


def _pygame_mixer_pos() -> int:
    import pygame

    return pygame.mixer.music.get_pos()


class SongClock:
    """Converts wall-clock ticks into song time."""

    def __init__(
        self,
        latency_offset_ms: float = 0.0,
        ticks_provider: Optional[TickProvider] = None,
        mixer_pos_provider: Optional[MixerPosProvider] = None,
    ) -> None:
        self.latency_offset_ms = float(latency_offset_ms)
        self._ticks: TickProvider = ticks_provider or _pygame_ticks
        self._mixer_pos: MixerPosProvider = mixer_pos_provider or _pygame_mixer_pos
        self._start_ticks: Optional[int] = None
        # (song_ms, mixer_pos_ms) pairs, kept so a run can be checked afterwards
        self.samples: list[tuple[float, Optional[int]]] = []

    # --- start / stop ------------------------------------------------------
    def start(self, at_ticks: Optional[int] = None) -> None:
        """Mark the moment the music started."""
        self._start_ticks = self._ticks() if at_ticks is None else int(at_ticks)
        self.samples.clear()

    def stop(self) -> None:
        self._start_ticks = None

    @property
    def running(self) -> bool:
        return self._start_ticks is not None

    @property
    def latency_offset(self) -> float:
        return self.latency_offset_ms

    @latency_offset.setter
    def latency_offset(self, value: float) -> None:
        self.latency_offset_ms = float(value)

    # --- readings ----------------------------------------------------------
    def tick_reading_ms(self) -> int:
        """The raw tick reading, for the debug panel."""
        return int(self._ticks())

    def song_time_ms(self, at_ticks: Optional[int] = None) -> float:
        """Primary clock: milliseconds into the song."""
        if self._start_ticks is None:
            return 0.0
        now = self._ticks() if at_ticks is None else int(at_ticks)
        return (now - self._start_ticks) - self.latency_offset_ms

    def mixer_position_ms(self) -> Optional[int]:
        """What the mixer thinks, or None when the reading is unusable."""
        try:
            position = int(self._mixer_pos())
        except Exception:
            return None
        return None if position < 0 else position

    def drift_ms(self, at_ticks: Optional[int] = None) -> Optional[float]:
        """How far the mixer reading is from the tick clock."""
        position = self.mixer_position_ms()
        if position is None:
            return None
        return self.song_time_ms(at_ticks) - position

    def sample(self, at_ticks: Optional[int] = None) -> tuple[float, Optional[int]]:
        """Read both clocks at once and keep the pair for later comparison."""
        song_ms = self.song_time_ms(at_ticks)
        position = self.mixer_position_ms()
        self.samples.append((song_ms, position))
        return song_ms, position
