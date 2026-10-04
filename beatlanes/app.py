# The game itself: states, events, the frame loop.
#
# States: TITLE (waiting) -> CALIBRATE (metronome test) -> COUNTDOWN (3,2,1,GO)
# -> PLAY (song running, taps judged) -> RESULTS (run over, log written).
#
# The loop is deliberately plain: cap the frame rate, read the clock, handle
# events, update the session, draw. Notes are never moved by a per-frame step -
# their positions come from the song clock - so a slow frame changes how smooth
# the game looks, never when a note is judged.

from __future__ import annotations

import os  # to set the SDL driver names for headless runs
from pathlib import Path
from typing import Callable, Optional, Sequence

import pygame  # window, input, clock

from . import audio, config, render  # sound, settings, drawing
from .calibration import CalibrationRun, load_calibration, save_calibration  # the metronome test
from .chart import Chart, load_chart  # the chart being played
from .judge import Verdict  # verdict names
from .logbook import TapLog  # the CSV log
from .session import PlaySession  # one play-through
from .songclock import SongClock  # the song clock

STATE_TITLE = "title"  # waiting for the player
STATE_CALIBRATE = "calibrate"  # the metronome test
STATE_COUNTDOWN = "countdown"  # 3, 2, 1 before the first note
STATE_PLAY = "play"  # the song is running
STATE_RESULTS = "results"  # the run is over

COUNTDOWN_LEAD_IN_MS = 4000.0  # the countdown sits inside the 4-bar intro


class FakeTicks:  # a tick source that advances by a fixed step per frame
    # song time comes from ticks, so faking the ticks makes a headless run
    # deterministic and independent of the machine's speed

    def __init__(self, step_ms: float) -> None:
        self.value = 0.0  # the fake time, in ms
        self.step_ms = float(step_ms)  # how far it moves per frame

    def __call__(self) -> int:  # the clock interface the rest of the code sees
        return int(self.value)

    def advance(self) -> None:  # called once per frame
        self.value += self.step_ms


class SimulatedTaps:  # feeds a prepared list of taps in at the right song times
    def __init__(self, taps: Sequence[tuple[int, float]]) -> None:
        self.taps = sorted(taps, key=lambda item: item[1])  # earliest first
        self.next_index = 0  # which tap is next

    def due(self, song_ms: float) -> list[tuple[int, float]]:
        # the taps whose time has arrived by now
        ready: list[tuple[int, float]] = []
        while self.next_index < len(self.taps) and self.taps[self.next_index][1] <= song_ms:
            ready.append(self.taps[self.next_index])
            self.next_index += 1
        return ready


class BeatLanesApp:  # the whole game, wired together
    def __init__(
        self,
        chart_path: Optional[Path | str] = None,  # chart file
        song_path: Optional[Path | str] = None,  # song file
        latency_offset_ms: Optional[float] = None,  # calibration offset
        ticks_provider: Optional[Callable[[], int]] = None,  # injectable clock
        mixer_pos_provider: Optional[Callable[[], int]] = None,  # injectable mixer
        enable_audio: bool = True,  # False for silent runs
        simulated_taps: Optional[Sequence[tuple[int, float]]] = None,  # automatic run
        screenshot_path: Optional[Path | str] = None,  # save one frame
        screenshot_at_ms: float = 12_000.0,  # when to take it
        screenshot_state: str = STATE_PLAY,  # which screen
        windowed: bool = False,  # keep a real window in an automatic run
        record_path: Optional[Path | str] = None,  # write an mp4
        record_fps: int = config.FPS,  # recording frame rate
        record_scale: int = 1,  # recording pixel scale
        log_path: Optional[Path | str] = None,  # where the CSV goes
    ) -> None:
        # chart selection: the title screen cycles config.CHARTS with LEFT/RIGHT
        self.chart_paths = list(config.CHARTS)  # the charts the player can pick
        if chart_path is not None:  # an explicit --chart overrides the menu
            self.chart_paths = [Path(chart_path)]
        self.chart_index = 0  # which entry of chart_paths is selected
        self.chart: Chart = load_chart(self.chart_paths[self.chart_index])  # read and check it
        self.song_path = song_path  # the backing track
        self.enable_audio = enable_audio  # False for silent runs
        self.log_path = log_path  # where the tap log goes

        # An automatic run is one nobody sits in front of: taps are supplied, or
        # it only exists to capture a frame. Automatic runs go headless unless
        # --windowed keeps a real window (and real mixer readings) alive.
        self.automatic = bool(simulated_taps) or screenshot_path is not None or record_path is not None
        self.headless = self.automatic and not windowed
        self.screenshot_path = Path(screenshot_path) if screenshot_path else None
        self.record_path = Path(record_path) if record_path else None
        self.record_fps = int(record_fps)
        self.record_scale = max(1, int(record_scale))  # 2 gives 1920x1280 footage
        self._recorder = None  # the ffmpeg process, when recording
        self.screenshot_at_ms = float(screenshot_at_ms)  # when to capture
        self.screenshot_state = screenshot_state  # which screen to capture
        self._screenshot_written = False  # so only one frame is saved

        # headless runs must not open a window or a speaker; setting the driver
        # names before pygame starts is what keeps them quiet
        if self.headless:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

        self.fake_ticks = FakeTicks(1000.0 / config.FPS) if self.headless else None  # the fake clock
        if ticks_provider is not None:  # an injected clock wins
            ticks = ticks_provider
        elif self.fake_ticks is not None:  # headless uses the fake one
            ticks = self.fake_ticks
        else:
            ticks = None  # SongClock falls back to the real pygame clock
        if mixer_pos_provider is not None:  # injected mixer wins
            mixer_pos = mixer_pos_provider
        elif self.headless:
            mixer_pos = lambda: -1  # no audio device in these runs
        else:
            mixer_pos = None  # use the real mixer

        if latency_offset_ms is None:  # no offset given: load the saved one
            latency_offset_ms = load_calibration()
        self.latency_offset = float(latency_offset_ms)  # the offset this run uses
        self.clock = SongClock(  # the song clock
            latency_offset_ms=self.latency_offset,
            ticks_provider=ticks,
            mixer_pos_provider=mixer_pos,
        )

        # run-time state
        self.state = STATE_TITLE  # the game starts on the title screen
        self.running = True  # False ends the loop
        self.exit_code = 0  # what main() returns
        self.countdown_start_ms: Optional[float] = None  # countdown anchor, in song time
        # automatic runs get a frame budget: no player means no one to close the
        # window, so a stall should fail loudly instead of spinning
        self.frame_budget: Optional[int] = 200_000 if self.automatic else None
        self.debug = False  # TAB toggles the debug overlay
        self.session: Optional[PlaySession] = None  # created when a run starts
        self.log: Optional[TapLog] = None  # the CSV log for this run
        self.last_log_path: Optional[Path] = None  # shown on the results screen
        self.auto_taps: Optional[SimulatedTaps] = (
            SimulatedTaps(simulated_taps) if simulated_taps else None
        )
        self.simulated_taps = list(simulated_taps) if simulated_taps else []  # kept for restarts
        self.best_accuracy: Optional[float] = None  # shown on the title screen
        self.status_message = ""  # one-line message under the title panel
        self.flashes: dict[int, float] = {}  # lane -> song time of the last press

        # calibration state
        self.calibration_run: Optional[CalibrationRun] = None
        self.calibration_last_beat = -1  # so each click only plays once
        self.calibration_last_offset: Optional[float] = None  # shown under the circle

        # pygame objects, created in _setup
        self.screen: Optional[pygame.Surface] = None  # the window
        # everything is drawn onto this offscreen frame first, then blitted to
        # the window. Depth 24 matters: on macOS the window surface carries an
        # alpha mask, and screenshots taken from it come out transparent. A
        # 24-bit surface has no alpha mask on any driver.
        self.frame: Optional[pygame.Surface] = None
        self.frame_clock = pygame.time.Clock()  # caps the frame rate
        self.click = None  # the metronome click sound
        self.audio_playing = False  # True while the song plays
        self.mixer_ok = False  # False means 'no audio device'

    # --- lifecycle --------------------------------------------------------
    def _setup(self) -> None:  # open the window, and the mixer when wanted
        pygame.init()
        pygame.display.set_caption(config.CAPTION)
        self.screen = pygame.display.set_mode((config.WINDOW_WIDTH, config.WINDOW_HEIGHT))
        self.frame = pygame.Surface(
            (config.WINDOW_WIDTH, config.WINDOW_HEIGHT), 0, 24  # 24-bit: no alpha
        )
        if self.enable_audio and not self.headless:  # only real runs open the mixer
            self.mixer_ok = audio.init_mixer()
            if self.mixer_ok:
                self.click = audio.make_click()  # the calibration metronome
        if not self.mixer_ok:
            self.status_message = self.status_message or "no audio device: running on the tick clock only"

    def _teardown(self) -> None:  # stop recording, close the log, shut pygame down
        self._stop_recording()
        if self.log is not None:  # flush the CSV
            self.log.close()
            self.log = None
        audio.stop_song()
        pygame.quit()

    def run(self) -> int:  # the frame loop, until the game ends
        self._setup()
        if self.record_path is not None:  # start the recorder first
            self._start_recording()
        if self.automatic and self.screenshot_state == STATE_CALIBRATE:
            self._start_calibration()  # go straight to the metronome
        elif self.automatic and self.screenshot_state != STATE_TITLE:
            self._start_play()  # no player, so skip the title screen
        try:
            while self.running:
                if self.frame_budget is not None:  # only automatic runs have one
                    if self.frame_budget <= 0:  # stalled: fail loudly
                        print("automatic run hit its frame budget without finishing")
                        self.exit_code = 1
                        break
                    self.frame_budget -= 1
                self._cap_frame_rate()  # hold 60 fps in a real run
                self._handle_events()  # keyboard and window events
                self._update()  # game logic
                self._draw()  # draw the frame
                pygame.display.flip()  # show it
                if self.fake_ticks is not None:  # move the fake clock
                    self.fake_ticks.advance()
                self._write_frame()  # feed the recorder
                if self._screenshot_written:  # capture done, that was the point
                    break
        finally:
            self._teardown()  # always clean up
        return self.exit_code

    def _cap_frame_rate(self) -> None:
        # tick(0) means 'do not wait', which is what a headless run wants
        self.frame_clock.tick(0 if self.headless else config.FPS)

    # --- events -----------------------------------------------------------
    def _handle_events(self) -> None:  # read the event queue
        for event in pygame.event.get():
            if event.type == pygame.QUIT:  # the X button
                self.running = False
            elif event.type == pygame.KEYDOWN:
                self._handle_key(pygame.key.name(event.key).lower())  # key name, lower case

    def _handle_key(self, name: str) -> None:  # one key press, handled by state
        lane = config.LANE_KEY_TO_INDEX.get(name)  # is it a lane key?

        if self.state == STATE_TITLE:  # waiting
            if name == "escape":  # quit
                self.running = False
            elif name == "space":  # start a run
                self._start_play()
            elif name == "c":  # calibration
                self._start_calibration()
            elif name == "left" or name == "right":  # pick a chart
                step = -1 if name == "left" else 1
                self.chart_index = (self.chart_index + step) % len(self.chart_paths)
                self.chart = load_chart(self.chart_paths[self.chart_index])  # load the newly picked one

        elif self.state == STATE_CALIBRATE:  # the metronome test
            if name == "escape":  # back out
                self.state = STATE_TITLE
            elif lane is not None:  # any lane key counts as a tap
                self._calibration_tap()

        elif self.state == STATE_COUNTDOWN:  # during the 3, 2, 1
            if name == "escape":  # bail out of the run
                self._finish_play()

        elif self.state == STATE_PLAY:  # the song is running
            if name == "escape":  # end the run early
                self._finish_play()
            elif name == "tab":  # toggle the debug overlay
                self.debug = not self.debug
            elif lane is not None:  # a lane key: judge it
                # the mixer is sampled on the same press, so the log has both
                # clock readings for the same moment
                judgement = self.session.register_tap(
                    lane, mixer_pos_ms=self.clock.mixer_position_ms()
                )
                if judgement is not None:  # a note was scored: light the lane
                    self.flashes[lane] = self.clock.song_time_ms()

        elif self.state == STATE_RESULTS:  # the run is over
            if name == "escape":  # quit
                self.running = False
            elif name == "r":  # play again
                self._start_play()
            elif name == "t":  # back to the title
                self.state = STATE_TITLE

    # --- state changes ----------------------------------------------------
    def _start_play(self) -> None:  # begin a run
        self.session = PlaySession(  # fresh note states and score
            self.chart,
            self.clock,
            logger=None,
            calibration_offset_ms=self.latency_offset,
        )
        self.log = TapLog(path=self.log_path, song=self.chart.title, calibration_ms=self.latency_offset)
        self.session.logger = self.log  # the session writes rows through this
        self.auto_taps = SimulatedTaps(self.simulated_taps) if self.simulated_taps else None
        self.flashes.clear()  # no lanes lit at the start
        self.audio_playing = bool(self.enable_audio and not self.headless and audio.start_song(self.song_path))
        # the clock starts now; the calibration offset is what absorbs the audio
        # buffer and the input path, so the clock does not guess either
        self.clock.start()
        # the countdown shows in real runs and recorded demos, but not in
        # headless test runs - a test should not wait for the numbers
        show_countdown = not self.headless or self.record_path is not None
        if not show_countdown:
            self.countdown_start_ms = None
            self.state = STATE_PLAY
        else:
            # anchored to the first note: 3, 2, 1 land on the three seconds
            # before it, GO when it reaches the judgement line
            first_note_ms = self.chart.notes[0].time_ms if self.chart.notes else 0
            self.countdown_start_ms = max(0.0, first_note_ms - 3000.0)
            self.state = STATE_COUNTDOWN

    def _finish_play(self) -> None:  # end the run, close the log, show results
        if self.session is not None:
            self.best_accuracy = self.session.score.accuracy  # shown on the title
        if self.log is not None:  # flush the CSV
            self.last_log_path = self.log.path
            self.log.close()
            self.log = None
        audio.stop_song()
        self.audio_playing = False
        self.state = STATE_RESULTS
        if self.automatic:  # nobody to press R or ESC
            self.running = False

    def _start_calibration(self) -> None:  # begin the metronome test
        self.calibration_run = CalibrationRun()
        self.calibration_last_beat = -1  # no click has played yet
        self.calibration_last_offset = None
        self.clock.start()  # the test runs on the same clock
        self.state = STATE_CALIBRATE

    def _calibration_tap(self) -> None:  # one tap during the test
        if self.calibration_run is None:  # not calibrating
            return
        offset = self.calibration_run.register_tap(self.clock.song_time_ms())
        if offset is not None:  # a usable tap: show it
            self.calibration_last_offset = offset

    def _finish_calibration(self) -> None:  # save the offset, or say why not
        run = self.calibration_run
        if run is not None and run.offset_ms is not None and run.finished:
            self.latency_offset = float(run.offset_ms)  # use the median
            self.clock.latency_offset = self.latency_offset  # live, no restart needed
            save_calibration(self.latency_offset, taps=run.tap_count)  # keep it for next time
            self.status_message = f"calibration saved - {run.summary()}"
        elif run is not None:  # not enough usable taps
            self.status_message = f"calibration skipped - {run.summary()}"
        self.calibration_run = None
        self.state = STATE_TITLE

    # --- update -----------------------------------------------------------
    def _update(self) -> None:  # game logic, once per frame
        if self.state == STATE_COUNTDOWN and self.session is not None:
            song_ms = self.clock.song_time_ms()
            # the countdown ends at the first note, when keys start to matter
            first_note_ms = self.chart.notes[0].time_ms if self.chart.notes else 0
            if song_ms >= first_note_ms:
                self.state = STATE_PLAY

        elif self.state == STATE_PLAY and self.session is not None:
            song_ms = self.clock.song_time_ms()
            if self.auto_taps is not None:
                # a prepared run: judgement uses the tap's own time, so the
                # result does not depend on the frame it lands in. The mixer is
                # read on that frame, which is how an automatic log gets second
                # clock readings; a real press reads it in the key handler.
                for lane, tap_ms in self.auto_taps.due(song_ms):
                    judgement = self.session.register_tap(
                        lane, tap_ms=tap_ms, mixer_pos_ms=self.clock.mixer_position_ms()
                    )
                    if judgement is not None:  # a note scored: light the lane
                        self.flashes[lane] = tap_ms
            self.session.update(song_ms)  # miss the notes the song passed
            if song_ms > self.chart.length_ms + 1200 and self.session.finished:
                self._finish_play()  # everything judged, plus a little tail
            elif song_ms > self.chart.length_ms + 5000:  # stuck (unjudgeable notes)
                self._finish_play()  # end anyway

        elif self.state == STATE_CALIBRATE and self.calibration_run is not None:
            run = self.calibration_run
            song_ms = self.clock.song_time_ms()
            if self.auto_taps is not None:
                # prepared taps stand in for a player tapping the metronome
                for _lane, tap_ms in self.auto_taps.due(song_ms):
                    offset = run.register_tap(tap_ms)
                    if offset is not None:
                        self.calibration_last_offset = offset
            beat = int(song_ms // run.beat_ms)  # which click we are on
            if beat != self.calibration_last_beat and 0 <= beat < run.beats:
                self.calibration_last_beat = beat  # remember, so it plays once
                if self.click is not None:
                    self.click.play()  # the metronome click
            if song_ms > run.duration_ms + 400:  # run over, plus a little tail
                self._finish_calibration()
                if self.automatic:  # nobody to press anything after
                    self.running = False

        # drop flashes that have finished, so the dictionary cannot grow forever
        if self.flashes:
            song_ms = self.clock.song_time_ms()
            for lane in [lane for lane, at in self.flashes.items() if song_ms - at > 400]:
                self.flashes.pop(lane, None)

    # --- draw -------------------------------------------------------------
    def _draw(self) -> None:  # draw one frame, by state
        surface = self.frame  # drawn offscreen, then blitted to the window
        if surface is None:  # not set up yet
            return

        if self.state == STATE_TITLE:  # the title screen
            render.draw_title(
                surface,
                self.chart.title,
                self.chart.note_count,
                self.latency_offset,
                self.best_accuracy,
                anim_ms=None if self.headless else pygame.time.get_ticks(),  # None keeps captures identical
                chart_picker=(len(self.chart_paths) > 1, self.chart_index, len(self.chart_paths)),
            )
            if self.status_message:  # e.g. 'no audio device'
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
            render.draw_calibration(  # the metronome screen
                surface,
                max(0, self.calibration_last_beat),  # clicks done
                run.beats,  # clicks total
                run.offsets,  # taps so far
                self.calibration_last_offset,  # the last tap
                run.beat_phase(song_ms),  # pulses the circle
            )

        elif self.state in (STATE_COUNTDOWN, STATE_PLAY) and self.session is not None:
            # the play screen; the countdown draws over it until the first note
            song_ms = self.clock.song_time_ms()
            render.draw_background(surface)
            render.draw_beat_grid(surface, song_ms, self.chart.bpm)
            render.draw_lanes(surface, self.flashes, song_ms)
            # the judge line needs the song time to age the receptor flashes and
            # hit bursts; with raw timestamps the flash never fired at all
            render.draw_judge_line(surface, self.flashes, song_ms)
            render.draw_notes(surface, self.session, song_ms)
            render.draw_lane_labels(surface)
            render.draw_play_hud(
                surface, self.session, song_ms, self.reported_fps(), self.chart.title
            )

            judgement = self.session.last_judgement  # the popup word
            if judgement is not None:
                age = song_ms - self.session.last_judged_song_ms  # for its animation
                render.draw_judgement_popup(
                    surface, judgement.verdict, judgement.offset_text, age
                )

            if self.debug:  # the two clocks side by side
                render.draw_debug_panel(
                    surface,
                    song_ms,
                    self.clock.tick_reading_ms(),  # raw ticks
                    self.clock.mixer_position_ms(),  # the mixer reading
                    self.clock.drift_ms(),  # the gap between them
                    self.latency_offset,  # the offset in use
                    self.reported_fps(),
                )

            # the countdown over the play screen, then GO over the first beat
            if self.countdown_start_ms is not None:
                first_note_ms = self.chart.notes[0].time_ms if self.chart.notes else 0
                remaining = first_note_ms - song_ms  # time before the first note
                if remaining > 0:  # still counting
                    render.draw_countdown(surface, remaining)
                elif remaining > -800:  # the 0.8 s of GO
                    render.draw_go(surface, 800 + remaining)

        elif self.state == STATE_RESULTS and self.session is not None:
            log_name = self.last_log_path.name if self.last_log_path else "not written"
            render.draw_results(surface, self.session, log_name, self.chart.title)

        if self.screen is not None:  # show the finished frame
            self.screen.blit(surface, (0, 0))

        if self.screenshot_path is not None and not self._screenshot_written:
            if self._screenshot_ready():  # the asked-for screen is on show
                self.screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                pygame.image.save(surface, str(self.screenshot_path))  # the frame is opaque
                self._screenshot_written = True
                self.exit_code = 0

    # --- recording -------------------------------------------------------
    def _start_recording(self) -> None:
        # pipe raw frames straight into ffmpeg; pygame has no video writer, and
        # dumping PNGs first would waste disk for no reason
        import shutil
        import subprocess

        if self.record_path is None:  # not recording
            return
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:  # no ffmpeg: say so, carry on without video
            print("ffmpeg not found, so no video was recorded")
            self.record_path = None
            return
        self.record_path.parent.mkdir(parents=True, exist_ok=True)
        self._recorder = subprocess.Popen(  # raw RGB frames in, h264 out
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

    def _write_frame(self) -> None:  # hand one frame to ffmpeg
        if self._recorder is None or self.frame is None:
            return
        frame = self.frame
        if self.record_scale != 1:  # upscale for HD footage
            frame = pygame.transform.smoothscale(
                frame,
                (config.WINDOW_WIDTH * self.record_scale, config.WINDOW_HEIGHT * self.record_scale),
            )
        try:
            self._recorder.stdin.write(pygame.image.tobytes(frame, "RGB"))
        except (BrokenPipeError, AttributeError):  # ffmpeg died: stop feeding it
            self._recorder = None

    def _stop_recording(self) -> None:  # close ffmpeg cleanly
        if self._recorder is None:
            return
        self._recorder.stdin.close()
        self._recorder.wait()
        print(f"wrote {self.record_path}")
        self._recorder = None

    def reported_fps(self) -> Optional[float]:  # for the HUD; headless has none
        if self.headless:
            return None
        return self.frame_clock.get_fps()

    def _screenshot_ready(self) -> bool:  # is the asked-for screen on show?
        if self.state != self.screenshot_state:
            return False
        if self.state in (STATE_PLAY, STATE_CALIBRATE):  # wait for the moment
            return self.clock.song_time_ms() >= self.screenshot_at_ms
        return True  # title and results are static screens

    # --- headless reporting ----------------------------------------------
    def selftest_report(self) -> dict:  # the numbers a --selftest run produced
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
