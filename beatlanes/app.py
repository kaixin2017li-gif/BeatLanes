"""The game: states, event handling and the frame loop.

Four states:

    TITLE      waiting for the player
    CALIBRATE  the tap-to-metronome test
    PLAY       the song is running and taps are being judged
    RESULTS    the run is over and the tap log has been written

The loop is deliberately plain: cap the frame rate, read the clock, handle
events, update the session, draw. Nothing moves a note by a per-frame step -
the note positions come from the song clock every frame - so a slow frame
changes how smooth the game looks without changing when a note is judged.

Two extra modes reuse the same loop instead of duplicating it:

    --selftest    fake ticks and a prepared list of taps, so a whole run can be
                  played and checked without a keyboard or a sound card
    --screenshot  fake ticks, run to a chosen song time, save the frame
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional, Sequence

import pygame

from . import audio, config, render
from .calibration import CalibrationRun, load_calibration, save_calibration
from .chart import Chart, load_chart
from .judge import Verdict
from .logbook import TapLog
from .session import PlaySession
from .songclock import SongClock

STATE_TITLE = "title"
STATE_CALIBRATE = "calibrate"
STATE_COUNTDOWN = "countdown"
STATE_PLAY = "play"
STATE_RESULTS = "results"

# A short 3, 2, 1, GO before the music starts. The beat plan puts the first
# note at the start of bar 5, so the countdown overlaps the four intro bars:
# the player hears the drums and sees the numbers before a key is needed.
COUNTDOWN_LEAD_IN_MS = 4000.0


class FakeTicks:
    """A tick source that advances by a fixed step per frame.

    Song time comes from ticks, so replacing the tick source with this makes a
    whole run deterministic and independent of the machine's speed.
    """

    def __init__(self, step_ms: float) -> None:
        self.value = 0.0
        self.step_ms = float(step_ms)

    def __call__(self) -> int:
        return int(self.value)

    def advance(self) -> None:
        self.value += self.step_ms


class SimulatedTaps:
    """Feeds a prepared list of taps in at the right song times."""

    def __init__(self, taps: Sequence[tuple[int, float]]) -> None:
        self.taps = sorted(taps, key=lambda item: item[1])
        self.next_index = 0

    def due(self, song_ms: float) -> list[tuple[int, float]]:
        ready: list[tuple[int, float]] = []
        while self.next_index < len(self.taps) and self.taps[self.next_index][1] <= song_ms:
            ready.append(self.taps[self.next_index])
            self.next_index += 1
        return ready


class BeatLanesApp:
    """The whole game, wired together."""

    def __init__(
        self,
        chart_path: Optional[Path | str] = None,
        song_path: Optional[Path | str] = None,
        latency_offset_ms: Optional[float] = None,
        ticks_provider: Optional[Callable[[], int]] = None,
        mixer_pos_provider: Optional[Callable[[], int]] = None,
        enable_audio: bool = True,
        simulated_taps: Optional[Sequence[tuple[int, float]]] = None,
        screenshot_path: Optional[Path | str] = None,
        screenshot_at_ms: float = 12_000.0,
        screenshot_state: str = STATE_PLAY,
        windowed: bool = False,
        record_path: Optional[Path | str] = None,
        record_fps: int = config.FPS,
        record_scale: int = 1,
        log_path: Optional[Path | str] = None,
    ) -> None:
        self.chart: Chart = load_chart(chart_path)
        self.song_path = song_path
        self.enable_audio = enable_audio
        self.log_path = log_path

        # An automatic run is one nobody is sitting in front of: it has taps
        # supplied for it, or it is only there to capture a frame. Automatic
        # runs normally go headless; --windowed keeps a real window and a real
        # audio device, which is how the tap log gets real mixer readings.
        self.automatic = bool(simulated_taps) or screenshot_path is not None or record_path is not None
        self.headless = self.automatic and not windowed
        self.screenshot_path = Path(screenshot_path) if screenshot_path else None
        self.record_path = Path(record_path) if record_path else None
        self.record_fps = int(record_fps)
        # The game lays itself out for a 960x640 window. Recording at scale 2
        # gives 1920x1280 footage, which is what an HD submission wants.
        self.record_scale = max(1, int(record_scale))
        self._recorder = None
        self.screenshot_at_ms = float(screenshot_at_ms)
        self.screenshot_state = screenshot_state
        self._screenshot_written = False

        # Headless runs must not open a window or a speaker. Setting the driver
        # names before Pygame initialises those subsystems is what keeps them
        # quiet on a machine with no display attached.
        if self.headless:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

        self.fake_ticks = FakeTicks(1000.0 / config.FPS) if self.headless else None
        if ticks_provider is not None:
            ticks = ticks_provider
        elif self.fake_ticks is not None:
            ticks = self.fake_ticks
        else:
            ticks = None
        if mixer_pos_provider is not None:
            mixer_pos = mixer_pos_provider
        elif self.headless:
            mixer_pos = lambda: -1  # no audio device in these runs
        else:
            mixer_pos = None

        if latency_offset_ms is None:
            latency_offset_ms = load_calibration()
        self.latency_offset = float(latency_offset_ms)
        self.clock = SongClock(
            latency_offset_ms=self.latency_offset,
            ticks_provider=ticks,
            mixer_pos_provider=mixer_pos,
        )

        # run-time state
        self.state = STATE_TITLE
        self.running = True
        self.exit_code = 0
        # Song time when a countdown starts; the first note of the chart lands
        # when the countdown's lead-in has elapsed.
        self.countdown_start_ms: Optional[float] = None
        # A headless run has no player to close the window, so it gets a frame
        # budget. Reaching it means the run stalled, which is worth failing on
        # rather than spinning quietly.
        self.frame_budget: Optional[int] = 200_000 if self.automatic else None
        self.debug = False
        self.session: Optional[PlaySession] = None
        self.log: Optional[TapLog] = None
        self.last_log_path: Optional[Path] = None
        self.auto_taps: Optional[SimulatedTaps] = (
            SimulatedTaps(simulated_taps) if simulated_taps else None
        )
        self.simulated_taps = list(simulated_taps) if simulated_taps else []
        self.best_accuracy: Optional[float] = None
        self.status_message = ""
        self.flashes: dict[int, float] = {}

        # calibration state
        self.calibration_run: Optional[CalibrationRun] = None
        self.calibration_last_beat = -1
        self.calibration_last_offset: Optional[float] = None

        # pygame objects, created in _setup
        self.screen: Optional[pygame.Surface] = None
        # Everything is drawn onto this offscreen surface first, then blitted
        # to the window, so captures and the recorder read a surface this code
        # controls rather than the window's.
        #
        # Depth 24 matters. Under the cocoa driver a plain Surface((w, h))
        # inherits the display format, and that format carries an alpha mask
        # (masks end 4278190080). pygame.image.save then writes an RGBA PNG
        # that is transparent wherever nothing was drawn, so a windowed capture
        # came out with white blocks where the HUD should be. The dummy driver
        # used by headless runs has no alpha mask, which is why only windowed
        # captures were affected. A 24-bit surface has no alpha mask on either
        # driver, so the frames are opaque by construction.
        self.frame: Optional[pygame.Surface] = None
        self.frame_clock = pygame.time.Clock()
        self.click = None
        self.audio_playing = False
        self.mixer_ok = False

    # --- lifecycle --------------------------------------------------------
    def _setup(self) -> None:
        pygame.init()
        pygame.display.set_caption(config.CAPTION)
        self.screen = pygame.display.set_mode((config.WINDOW_WIDTH, config.WINDOW_HEIGHT))
        self.frame = pygame.Surface(
            (config.WINDOW_WIDTH, config.WINDOW_HEIGHT), 0, 24
        )
        if self.enable_audio and not self.headless:
            self.mixer_ok = audio.init_mixer()
            if self.mixer_ok:
                self.click = audio.make_click()
        if not self.mixer_ok:
            self.status_message = self.status_message or "no audio device: running on the tick clock only"

    def _teardown(self) -> None:
        self._stop_recording()
        if self.log is not None:
            self.log.close()
            self.log = None
        audio.stop_song()
        pygame.quit()

    def run(self) -> int:
        """Run until the player quits (or a headless mode finishes)."""
        self._setup()
        if self.record_path is not None:
            self._start_recording()
        if self.automatic and self.screenshot_state == STATE_CALIBRATE:
            self._start_calibration()
        elif self.automatic and self.screenshot_state != STATE_TITLE:
            # Nobody is here to press SPACE, so an automatic run goes straight
            # into the state it was asked to capture.
            self._start_play()
        try:
            while self.running:
                if self.frame_budget is not None:
                    if self.frame_budget <= 0:
                        print("automatic run hit its frame budget without finishing")
                        self.exit_code = 1
                        break
                    self.frame_budget -= 1
                self._cap_frame_rate()
                self._handle_events()
                self._update()
                self._draw()
                pygame.display.flip()
                if self.fake_ticks is not None:
                    self.fake_ticks.advance()
                self._write_frame()
                if self._screenshot_written:
                    break
        finally:
            self._teardown()
        return self.exit_code

    def _cap_frame_rate(self) -> None:
        # tick(0) means "do not wait", which is what a headless run wants
        self.frame_clock.tick(0 if self.headless else config.FPS)

    # --- events -----------------------------------------------------------
    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                self._handle_key(pygame.key.name(event.key).lower())

    def _handle_key(self, name: str) -> None:
        lane = config.LANE_KEY_TO_INDEX.get(name)

        if self.state == STATE_TITLE:
            if name == "escape":
                self.running = False
            elif name == "space":
                self._start_play()
            elif name == "c":
                self._start_calibration()

        elif self.state == STATE_CALIBRATE:
            if name == "escape":
                self.state = STATE_TITLE
            elif lane is not None:
                self._calibration_tap()

        elif self.state == STATE_COUNTDOWN:
            if name == "escape":
                self._finish_play()

        elif self.state == STATE_PLAY:
            if name == "escape":
                self._finish_play()
            elif name == "tab":
                self.debug = not self.debug
            elif lane is not None:
                # Sample the mixer on the same press, so the log always has both
                # readings for the same moment.
                judgement = self.session.register_tap(
                    lane, mixer_pos_ms=self.clock.mixer_position_ms()
                )
                if judgement is not None:
                    self.flashes[lane] = self.clock.song_time_ms()

        elif self.state == STATE_RESULTS:
            if name == "escape":
                self.running = False
            elif name == "r":
                self._start_play()
            elif name == "t":
                self.state = STATE_TITLE

    # --- state changes ----------------------------------------------------
    def _start_play(self) -> None:
        self.session = PlaySession(
            self.chart,
            self.clock,
            logger=None,
            calibration_offset_ms=self.latency_offset,
        )
        self.log = TapLog(path=self.log_path, song=self.chart.title, calibration_ms=self.latency_offset)
        self.session.logger = self.log
        self.auto_taps = SimulatedTaps(self.simulated_taps) if self.simulated_taps else None
        self.flashes.clear()
        self.audio_playing = bool(self.enable_audio and not self.headless and audio.start_song(self.song_path))
        # The clock starts now. The offset measured by the metronome test is what
        # absorbs the audio buffer and the input path, so the clock does not try
        # to guess either of them.
        self.clock.start()
        # The countdown shows in a real run and in a recorded demo, but not in a
        # headless test run - a test should not have to wait for the numbers.
        show_countdown = not self.headless or self.record_path is not None
        if not show_countdown:
            self.countdown_start_ms = None
            self.state = STATE_PLAY
        else:
            # the countdown is anchored to the first note: 3, 2, 1 land on the
            # three seconds before it, GO when it reaches the judgement line
            first_note_ms = self.chart.notes[0].time_ms if self.chart.notes else 0
            self.countdown_start_ms = max(0.0, first_note_ms - 3000.0)
            self.state = STATE_COUNTDOWN

    def _finish_play(self) -> None:
        if self.session is not None:
            self.best_accuracy = self.session.score.accuracy
        if self.log is not None:
            self.last_log_path = self.log.path
            self.log.close()
            self.log = None
        audio.stop_song()
        self.audio_playing = False
        self.state = STATE_RESULTS
        if self.automatic:
            # Nobody is here to press R or ESC, so the run is over as soon as
            # the play-through is.
            self.running = False

    def _start_calibration(self) -> None:
        self.calibration_run = CalibrationRun()
        self.calibration_last_beat = -1
        self.calibration_last_offset = None
        self.clock.start()
        self.state = STATE_CALIBRATE

    def _calibration_tap(self) -> None:
        if self.calibration_run is None:
            return
        offset = self.calibration_run.register_tap(self.clock.song_time_ms())
        if offset is not None:
            self.calibration_last_offset = offset

    def _finish_calibration(self) -> None:
        run = self.calibration_run
        if run is not None and run.offset_ms is not None and run.finished:
            self.latency_offset = float(run.offset_ms)
            self.clock.latency_offset = self.latency_offset
            save_calibration(self.latency_offset, taps=run.tap_count)
            self.status_message = f"calibration saved - {run.summary()}"
        elif run is not None:
            self.status_message = f"calibration skipped - {run.summary()}"
        self.calibration_run = None
        self.state = STATE_TITLE

    # --- update -----------------------------------------------------------
    def _update(self) -> None:
        if self.state == STATE_COUNTDOWN and self.session is not None:
            song_ms = self.clock.song_time_ms()
            # the countdown ends at the first note, which is when keys start to matter
            first_note_ms = self.chart.notes[0].time_ms if self.chart.notes else 0
            if song_ms >= first_note_ms:
                self.state = STATE_PLAY

        elif self.state == STATE_PLAY and self.session is not None:
            song_ms = self.clock.song_time_ms()
            if self.auto_taps is not None:
                # A prepared run: judgement uses the tap's own time, so the
                # result does not depend on the frame the tap lands on. The
                # mixer is read on the frame the tap is released, which is how
                # an automatic log gets second-clock readings at all; for a real
                # keyboard tap the reading comes from the key event itself.
                for lane, tap_ms in self.auto_taps.due(song_ms):
                    judgement = self.session.register_tap(
                        lane, tap_ms=tap_ms, mixer_pos_ms=self.clock.mixer_position_ms()
                    )
                    if judgement is not None:
                        self.flashes[lane] = tap_ms
            self.session.update(song_ms)
            if song_ms > self.chart.length_ms + 1200 and self.session.finished:
                self._finish_play()
            elif song_ms > self.chart.length_ms + 5000:
                self._finish_play()

        elif self.state == STATE_CALIBRATE and self.calibration_run is not None:
            run = self.calibration_run
            song_ms = self.clock.song_time_ms()
            if self.auto_taps is not None:
                # the prepared taps stand in for a player tapping the metronome
                for _lane, tap_ms in self.auto_taps.due(song_ms):
                    offset = run.register_tap(tap_ms)
                    if offset is not None:
                        self.calibration_last_offset = offset
            beat = int(song_ms // run.beat_ms)
            if beat != self.calibration_last_beat and 0 <= beat < run.beats:
                self.calibration_last_beat = beat
                if self.click is not None:
                    self.click.play()
            if song_ms > run.duration_ms + 400:
                self._finish_calibration()
                if self.automatic:
                    self.running = False

        # drop flashes that have finished so the dictionary cannot grow forever
        if self.flashes:
            song_ms = self.clock.song_time_ms()
            for lane in [lane for lane, at in self.flashes.items() if song_ms - at > 400]:
                self.flashes.pop(lane, None)

    # --- draw -------------------------------------------------------------
    def _draw(self) -> None:
        surface = self.frame
        if surface is None:
            return

        if self.state == STATE_TITLE:
            render.draw_title(
                surface,
                self.chart.title,
                self.chart.note_count,
                self.latency_offset,
                self.best_accuracy,
                # An ambient clock for the drifting background notes. Headless
                # captures pass None so a screenshot is the same frame every time.
                anim_ms=None if self.headless else pygame.time.get_ticks(),
            )
            if self.status_message:
                render.text(
                    surface,
                    self.status_message,
                    (config.WINDOW_WIDTH / 2.0, 486),
                    size=15,
                    colour=config.TEXT_MUTED,
                    mono=True,
                    align="center",
                )

        elif self.state == STATE_CALIBRATE and self.calibration_run is not None:
            run = self.calibration_run
            song_ms = self.clock.song_time_ms()
            render.draw_calibration(
                surface,
                max(0, self.calibration_last_beat),
                run.beats,
                run.offsets,
                self.calibration_last_offset,
                run.beat_phase(song_ms),
            )

        elif self.state in (STATE_COUNTDOWN, STATE_PLAY) and self.session is not None:
            song_ms = self.clock.song_time_ms()
            render.draw_background(surface)
            render.draw_beat_grid(surface, song_ms, self.chart.bpm)
            render.draw_lanes(surface, self.flashes, song_ms)
            # The judge line needs the song time to age the receptor flashes and
            # hit bursts; before this it compared raw timestamps against 220 ms,
            # so the flash highlight never actually fired past the first frame.
            render.draw_judge_line(surface, self.flashes, song_ms)
            render.draw_notes(surface, self.session, song_ms)
            render.draw_lane_labels(surface)
            render.draw_play_hud(
                surface, self.session, song_ms, self.reported_fps(), self.chart.title
            )

            judgement = self.session.last_judgement
            if judgement is not None:
                age = song_ms - self.session.last_judged_song_ms
                render.draw_judgement_popup(
                    surface, judgement.verdict, judgement.offset_text, age
                )

            if self.debug:
                render.draw_debug_panel(
                    surface,
                    song_ms,
                    self.clock.tick_reading_ms(),
                    self.clock.mixer_position_ms(),
                    self.clock.drift_ms(),
                    self.latency_offset,
                    self.reported_fps(),
                )

            # the countdown shows over the play screen until the first note,
            # then GO over the beat it lands on
            if self.countdown_start_ms is not None:
                first_note_ms = self.chart.notes[0].time_ms if self.chart.notes else 0
                remaining = first_note_ms - song_ms
                if remaining > 0:
                    render.draw_countdown(surface, remaining)
                elif remaining > -800:
                    render.draw_go(surface, 800 + remaining)

        elif self.state == STATE_RESULTS and self.session is not None:
            log_name = self.last_log_path.name if self.last_log_path else "not written"
            render.draw_results(surface, self.session, log_name, self.chart.title)

        if self.screen is not None:
            self.screen.blit(surface, (0, 0))

        if self.screenshot_path is not None and not self._screenshot_written:
            if self._screenshot_ready():
                self.screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                # the frame surface is opaque, so the PNG is always solid
                pygame.image.save(surface, str(self.screenshot_path))
                self._screenshot_written = True
                self.exit_code = 0

    # --- recording -------------------------------------------------------
    def _start_recording(self) -> None:
        """Pipe raw frames straight into ffmpeg.

        pygame has no video writer, and writing thousands of PNGs first just to
        hand them to ffmpeg afterwards wastes a lot of disk for no reason.
        """
        import shutil
        import subprocess

        if self.record_path is None:
            return
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            print("ffmpeg not found, so no video was recorded")
            self.record_path = None
            return
        self.record_path.parent.mkdir(parents=True, exist_ok=True)
        self._recorder = subprocess.Popen(
            [
                ffmpeg, "-y", "-loglevel", "error",
                "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", f"{config.WINDOW_WIDTH * self.record_scale}x{config.WINDOW_HEIGHT * self.record_scale}",
                "-r", str(self.record_fps),
                "-i", "-",
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                str(self.record_path),
            ],
            stdin=subprocess.PIPE,
        )

    def _write_frame(self) -> None:
        if self._recorder is None or self.frame is None:
            return
        frame = self.frame
        if self.record_scale != 1:
            frame = pygame.transform.smoothscale(
                frame,
                (config.WINDOW_WIDTH * self.record_scale, config.WINDOW_HEIGHT * self.record_scale),
            )
        try:
            self._recorder.stdin.write(pygame.image.tobytes(frame, "RGB"))
        except (BrokenPipeError, AttributeError):
            self._recorder = None

    def _stop_recording(self) -> None:
        if self._recorder is None:
            return
        self._recorder.stdin.close()
        self._recorder.wait()
        print(f"wrote {self.record_path}")
        self._recorder = None

    def reported_fps(self) -> Optional[float]:
        """Frame rate for the HUD. A headless run has none worth showing."""
        if self.headless:
            return None
        return self.frame_clock.get_fps()

    def _screenshot_ready(self) -> bool:
        """Whether the screen asked for by --shot-state is on show."""
        if self.state != self.screenshot_state:
            return False
        if self.state in (STATE_PLAY, STATE_CALIBRATE):
            # wait for the requested moment of the clock, so a calibration
            # capture also shows taps already collected
            return self.clock.song_time_ms() >= self.screenshot_at_ms
        return True

    # --- headless reporting ----------------------------------------------
    def selftest_report(self) -> dict:
        """Numbers a --selftest run produced, so main.py can print and check them."""
        score = self.session.score if self.session is not None else None
        return {
            "chart": self.chart.title,
            "notes": self.chart.note_count,
            "taps_fed": len(self.simulated_taps),
            "perfect": None if score is None else score.perfect,
            "good": None if score is None else score.good,
            "miss": None if score is None else score.miss,
            "stray": None if score is None else score.stray_taps,
            "accuracy": None if score is None else round(score.accuracy, 1),
            "best_combo": None if score is None else score.best_combo,
            "log": str(self.last_log_path) if self.last_log_path else None,
        }
