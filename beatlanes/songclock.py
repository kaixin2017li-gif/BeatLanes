# Song time for the game.
# Two readings exist in pygame and both are used, but only one is trusted:
# get_ticks() is the clock the judgement runs on, the mixer reading is only
# logged beside it so the two can be compared.
# The clock sources are passed in (not imported) so tests can fake the time.

from __future__ import annotations

from typing import Callable, Optional

TickProvider = Callable[[], int]  # a function that returns a tick count
MixerPosProvider = Callable[[], int]  # a function that returns a mixer position


def _pygame_ticks() -> int:  # the real tick clock
    import pygame

    return pygame.time.get_ticks()


def _pygame_mixer_pos() -> int:  # the mixer's own reading
    import pygame

    return pygame.mixer.music.get_pos()


class SongClock:  # converts tick readings into song time
    def __init__(
        self,
        latency_offset_ms: float = 0.0,  # the measured calibration offset
        ticks_provider: Optional[TickProvider] = None,  # injectable for tests
        mixer_pos_provider: Optional[MixerPosProvider] = None,  # injectable too
    ) -> None:
        self.latency_offset_ms = float(latency_offset_ms)  # subtracted from song time
        self._ticks: TickProvider = ticks_provider or _pygame_ticks  # default to the real clock
        self._mixer_pos: MixerPosProvider = mixer_pos_provider or _pygame_mixer_pos
        self._start_ticks: Optional[int] = None  # tick reading when the music started
        self.samples: list[tuple[float, Optional[int]]] = []  # (song_ms, mixer_ms) pairs kept for later checks

    def start(self, at_ticks: Optional[int] = None) -> None:  # mark the moment the music started
        self._start_ticks = self._ticks() if at_ticks is None else int(at_ticks)
        self.samples.clear()  # old run's samples belong to that run

    def stop(self) -> None:  # forget the start, the clock reads zero again
        self._start_ticks = None

    @property
    def running(self) -> bool:  # True once start() has been called
        return self._start_ticks is not None

    @property
    def latency_offset(self) -> float:  # read the offset
        return self.latency_offset_ms

    @latency_offset.setter
    def latency_offset(self, value: float) -> None:  # change it after a calibration run
        self.latency_offset_ms = float(value)

    def tick_reading_ms(self) -> int:  # the raw reading, for the debug panel
        return int(self._ticks())

    def song_time_ms(self, at_ticks: Optional[int] = None) -> float:
        # the primary clock: (now - start) - offset. This is what the judgement uses.
        if self._start_ticks is None:  # not started yet
            return 0.0
        now = self._ticks() if at_ticks is None else int(at_ticks)
        return (now - self._start_ticks) - self.latency_offset_ms

    def mixer_position_ms(self) -> Optional[int]:  # the mixer's opinion, or None
        try:
            position = int(self._mixer_pos())
        except Exception:  # a broken mixer must not crash the game
            return None
        return None if position < 0 else position  # -1 means nothing is playing

    def drift_ms(self, at_ticks: Optional[int] = None) -> Optional[float]:  # mixer vs tick clock
        position = self.mixer_position_ms()
        if position is None:  # no usable reading
            return None
        return self.song_time_ms(at_ticks) - position

    def sample(self, at_ticks: Optional[int] = None) -> tuple[float, Optional[int]]:
        # read both clocks at once and keep the pair for later comparison
        song_ms = self.song_time_ms(at_ticks)
        position = self.mixer_position_ms()
        self.samples.append((song_ms, position))
        return song_ms, position
