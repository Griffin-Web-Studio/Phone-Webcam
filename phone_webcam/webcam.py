"""Run scrcpy as a virtual webcam, reporting progress through a callback.

All the slow work (pkexec, adb, scrcpy, ffmpeg) happens on worker threads, and
progress leaves through `emit`, so the UI never blocks and nothing touches the
UI from the wrong thread.

scrcpy records into a FIFO and a pipeline decodes it, turns it as asked and
writes it into the one loopback device other apps open. Turning therefore works
live, without restarting scrcpy or interrupting the output.
"""

import os
import pty
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path

from phone_webcam import cameras, deps, loopback, phone, pipeline
from phone_webcam.preview import Preview
from phone_webcam.settings import Settings

# ──────────────────────────────────────────────────────────────────| Config |──
# A keyframe every second, with its parameter sets, so the decoder can start
# within moments. Without it the first picture can take twenty seconds.
CODEC_OPTIONS = "i-frame-interval=1,prepend-sps-pps-to-idr-frames=1"
SIGTERM_EXIT = -15
CONFIRM_TIMEOUT = 300
PREVIEW_TIMEOUT = 8

STOPPED = "stopped"
STARTING = "starting"
RUNNING = "running"
STOPPING = "stopping"
SWITCHING = "switching"
APPLYING = "applying"

Emit = Callable[[dict], None]


# ─────────────────────────────────────────────────────────────────| Helpers |──
def scrcpy_args(
    fifo: str,
    camera: cameras.Camera | None = None,
    settings: Settings = Settings(),
) -> list[str]:
    """The scrcpy command line that records a phone camera into a FIFO.

    Without a camera, scrcpy picks its default one. The size and frame rate
    are the settings, kept within what the chosen camera can do.
    """
    selection = [f"--camera-id={camera.id}"] if camera else []
    limit = settings.size
    if camera:
        size = cameras.pick_size(camera.sizes, limit)
        fps = cameras.pick_fps(camera.fps, settings.fps)
    else:
        size = f"{limit[0]}x{limit[1]}"
        fps = settings.fps
    return [
        "scrcpy",
        "--no-window",
        "--no-audio",
        "--video-source=camera",
        *selection,
        f"--camera-size={size}",
        f"--camera-fps={fps}",
        f"--video-bit-rate={settings.bitrate}M",
        f"--record={fifo}",
        "--record-format=mkv",
        f"--video-codec-options={CODEC_OPTIONS}",
    ]


def make_fifo() -> Path:
    """Create a private FIFO, in the runtime directory when there is one."""
    folder = Path(
        tempfile.mkdtemp(
            prefix="phone-webcam-", dir=os.environ.get("XDG_RUNTIME_DIR")
        )
    )
    fifo = folder / "camera.mkv"
    os.mkfifo(fifo, 0o600)
    return fifo


# Terminal control sequences: title changes (OSC) and cursor or erase codes.
ESCAPES = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[ -/]*[@-~]"
)


def clean_line(raw: str) -> str:
    """Drop terminal control codes, keeping what a progress bar ended on."""
    text = ESCAPES.sub("", raw)
    pieces = [piece for piece in text.split("\r") if piece.strip()]
    return pieces[-1].rstrip() if pieces else ""


def read_lines(fd: int) -> Iterator[str]:
    """Yield clean lines from a pty master until the process on it exits."""
    with os.fdopen(fd, encoding="utf-8", errors="replace", newline="\n") as f:
        try:
            for raw in f:
                line = clean_line(raw)
                if line:
                    yield line
        except OSError:
            # Linux reports the end of a pty as EIO, not as end of file.
            return


# ───────────────────────────────────────────────────────────────| Controller |──
class Webcam:
    """Starts and stops the webcam, one run at a time."""

    def __init__(
        self,
        emit: Emit,
        rotation: int = 0,
        mirror: bool = False,
        settings: Settings | None = None,
    ) -> None:
        self._emit = emit
        self._settings = settings or Settings()
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._pipeline: pipeline.Pipeline | None = None
        self._preview: Preview | None = None
        self._preview_busy = False
        self._cameras: dict[str, cameras.Camera] = {}
        self._camera_id: str | None = None
        self._previous: tuple[str | None, Settings] | None = None
        self._switching = False
        self._switched = False
        self._got_frame = False
        self._stop_requested = False
        self._answer = False
        self._answered = threading.Event()
        self._turn = (rotation, mirror)
        self._worker: threading.Thread | None = None
        self.state = STOPPED

    # ──────────────────────────────────────────────────────────────| Public |──
    def start(self) -> None:
        """Begin a run on a worker thread, ignored if one is under way."""
        with self._lock:
            if self.state != STOPPED:
                return
            self._stop_requested = False
            self._set_state(STARTING)
        self._worker = threading.Thread(
            target=self._run, name="webcam-worker", daemon=True
        )
        self._worker.start()

    def stop(self) -> None:
        """Ask the current run to end, ignored if nothing is running."""
        with self._lock:
            if self.state == STOPPED:
                return
            self._stop_requested = True
            self._set_state(STOPPING)
            if self._pipeline is not None:
                self._pipeline.quiet()
            if self._process is not None:
                self._process.terminate()
        self.answer(False)

    def join(self, timeout: float = 10) -> None:
        """Wait for the current run to clean up, used when the app closes."""
        worker = self._worker
        if worker is not None:
            worker.join(timeout)

    def orientation(self) -> dict:
        rotation, mirror = self._turn
        return {"rotation": rotation, "mirror": mirror}

    def set_orientation(self, rotation: int, mirror: bool) -> None:
        """Turn the image, live if a run is under way."""
        if rotation not in pipeline.ROTATIONS:
            raise ValueError(f"rotation must be one of {pipeline.ROTATIONS}")
        self._turn = (rotation, mirror)
        live = self._pipeline
        if live is not None:
            live.set_orientation(rotation, mirror)
        self._emit({"type": "orientation", **self.orientation()})

    def answer(self, yes: bool) -> None:
        """Reply to a confirmation the worker is waiting on."""
        self._answer = yes
        self._answered.set()

    def settings(self) -> dict:
        return self._settings.as_dict()

    def set_settings(self, data: dict) -> dict:
        """Change the stream settings, returning what was applied.

        The resolution is the output's format, which apps have already
        agreed to, so it only changes while stopped. The frame rate and
        bitrate are decided on the phone, so while running they restart scrcpy
        behind the output, which holds its last picture meanwhile. The preview
        rate is read each time a preview opens, so it can always change.
        """
        wanted = Settings.from_dict({**self._settings.as_dict(), **data})
        with self._lock:
            current = self._settings
            if self.state == STOPPED:
                self._settings = wanted
            elif self.state == RUNNING and self._process is not None:
                live = replace(
                    current,
                    fps=wanted.fps,
                    bitrate=wanted.bitrate,
                    preview_fps=wanted.preview_fps,
                )
                restart = (live.fps, live.bitrate) != (
                    current.fps,
                    current.bitrate,
                )
                if restart:
                    self._previous = (self._camera_id, current)
                self._settings = live
                if restart:
                    if self._pipeline is not None:
                        self._pipeline.set_fps(live.fps)
                    self._restart_scrcpy(APPLYING)
            else:
                self._settings = replace(
                    current, preview_fps=wanted.preview_fps
                )
        self._emit({"type": "settings", **self.settings()})
        return self.settings()

    def _restart_scrcpy(self, state: str) -> None:
        """End this scrcpy so the run loop starts another. Lock is held."""
        assert self._process is not None
        self._switching = True
        self._switched = True
        self._set_state(state)
        self._process.terminate()

    def list_cameras(self) -> list[dict]:
        """Ask the phone for its cameras, keeping them for later switches."""
        found = cameras.list_cameras()
        self._cameras = {camera.id: camera for camera in found}
        return [
            {"id": c.id, "label": c.label, "facing": c.facing} for c in found
        ]

    def camera(self) -> str:
        """The chosen camera's id, an empty string for the default."""
        return self._camera_id or ""

    def set_camera(self, camera_id: str) -> None:
        """Choose a camera, switching to it live if a run is going."""
        chosen = camera_id or None
        with self._lock:
            if chosen == self._camera_id:
                return
            self._previous = (self._camera_id, self._settings)
            self._camera_id = chosen
            if self.state == RUNNING and self._process is not None:
                self._restart_scrcpy(SWITCHING)
        self._emit({"type": "camera", "id": self.camera()})

    def toggle_preview(self) -> None:
        """Open or close the live preview, ignored while one is changing."""
        with self._lock:
            if self._preview_busy:
                return
            self._preview_busy = True
        threading.Thread(target=self._toggle_preview, daemon=True).start()

    # ──────────────────────────────────────────────────────────────| Worker |──
    def _set_state(self, state: str) -> None:
        self.state = state
        self._emit({"type": "state", "state": state})

    def _log(self, line: str) -> None:
        self._emit({"type": "log", "line": line})

    def _toggle_preview(self) -> None:
        try:
            if self._preview is not None:
                self._emit_preview("stopping")
                self._stop_preview()
            else:
                self._start_preview()
        finally:
            self._preview_busy = False

    def _emit_preview(self, state: str, url: str | None = None) -> None:
        self._emit({"type": "preview", "state": state, "url": url})

    def _start_preview(self) -> None:
        live = self._pipeline
        if live is None or self.state != RUNNING:
            self._log("Start the webcam first, there is nothing to preview.")
            return
        self._emit_preview("starting")
        width, height = self._settings.size
        rate = self._settings.preview_rate
        preview = Preview(width, height, rate)
        try:
            url = preview.start()
        except OSError as exc:
            self._log(f"Could not start the preview: {exc}")
            self._emit_preview("closed")
            return
        self._preview = preview
        live.set_preview(preview, rate)
        if not preview.wait_for_first_frame(PREVIEW_TIMEOUT):
            self._log("The preview did not produce a picture in time.")
            self._stop_preview()
            return
        self._emit_preview("open", url)

    def _stop_preview(self) -> None:
        preview, self._preview = self._preview, None
        live = self._pipeline
        if live is not None:
            live.set_preview(None)
        if preview is not None:
            preview.stop()
        self._emit_preview("closed")

    def _on_first_frame(self) -> None:
        """The first picture has arrived, so the webcam is really running."""
        self._got_frame = True
        self._switched = False
        with self._lock:
            if self.state in (STARTING, SWITCHING, APPLYING):
                self._set_state(RUNNING)

    def _finish(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
        self._stop_preview()
        live, self._pipeline = self._pipeline, None
        if live is not None:
            live.stop()
        with self._lock:
            self._process = None
            self._set_state(STOPPED)

    def _confirm(self, message: str) -> bool:
        """Ask the user a yes or no question and wait for the answer."""
        self._answered.clear()
        self._emit({"type": "confirm", "message": message})
        if not self._answered.wait(CONFIRM_TIMEOUT):
            return False
        return self._answer

    def _run(self) -> None:
        try:
            output = self._prepare()
            if output is not None and not self._stop_requested:
                self._stream(output)
        except Exception as exc:  # noqa: BLE001 - report it, never die silently
            self._log(f"Unexpected error: {type(exc).__name__}: {exc}")
        finally:
            self._finish()

    def _pkexec(self, command: list[str]) -> bool:
        """Run a privileged command, logging why it failed."""
        try:
            result = subprocess.run(command, capture_output=True, text=True)
        except OSError as exc:
            self._log(f"Could not run {command[0]}: {exc}")
            return False
        if result.returncode != 0:
            self._log(f"The command failed: {result.stderr.strip()}")
            return False
        return True

    def _ensure_devices(self) -> bool:
        """Make sure the output loopback device exists."""
        missing = loopback.missing_labels()
        if not missing:
            return True

        if not deps.V4L2LOOPBACK_SYSFS.exists():
            self._log("Loading v4l2loopback, authentication may be asked...")
            if not self._pkexec(loopback.load_command()):
                return False
        else:
            if loopback.has_ctl():
                self._log("Adding the webcam device...")
                if self._pkexec(loopback.add_command(missing)):
                    return not loopback.missing_labels()
            if loopback.module_in_use():
                self._log(
                    "The webcam device cannot be set up while another app "
                    "uses v4l2loopback. Close it and try again."
                )
                return False
            if not self._confirm(
                "The webcam device has to be created by reloading "
                "v4l2loopback. Other virtual cameras, such as OBS's, are "
                "removed until they are set up again. Reload it now?"
            ):
                self._log("Reload declined, the webcam was not started.")
                return False
            if not self._pkexec(loopback.reload_command()):
                return False

        if loopback.missing_labels():
            self._log("The webcam device was not created.")
            return False
        return True

    def _prepare(self) -> str | None:
        """Check the phone, set up the device, find its node."""
        status = phone.check_phone()
        if not status.ready:
            self._log(phone.MESSAGES[status.state])
            return None
        self._log(f"Phone found: {status.serial}")

        if not self._ensure_devices():
            return None
        output = loopback.find_device(loopback.OUTPUT_LABEL)
        if output is None:
            self._log("The webcam device could not be found.")
        return output

    def _start_pipeline(self, fifo: str, output: str) -> bool:
        width, height = self._settings.size
        live = pipeline.Pipeline(
            fifo,
            output,
            self._log,
            self._on_first_frame,
            width,
            height,
            self._settings.fps,
        )
        live.set_orientation(*self._turn)
        try:
            live.start()
        except OSError as exc:
            self._log(f"Could not start ffmpeg: {exc}")
            return False
        self._pipeline = live
        return True

    @staticmethod
    def _spawn(args: list[str]) -> tuple[subprocess.Popen, Iterator[str]]:
        """Start a process on a pty and return it with its output lines.

        scrcpy buffers its own messages when writing to a pipe, so they would
        only arrive on exit. A pty makes it print line by line.
        """
        master, slave = pty.openpty()
        try:
            process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=slave,
                stderr=slave,
                close_fds=True,
            )
        except OSError:
            os.close(master)
            raise
        finally:
            os.close(slave)
        return process, read_lines(master)

    def _camera(self) -> cameras.Camera | None:
        """The chosen camera, if the phone has reported it."""
        return self._cameras.get(self._camera_id or "")

    def _stream(self, output: str) -> None:
        """Run scrcpy until it ends, restarting it to switch cameras."""
        fifo = make_fifo()
        try:
            # The reader opens its end first, scrcpy then opens the other.
            if not self._start_pipeline(str(fifo), output):
                return
            while True:
                self._got_frame = False
                code = self._run_scrcpy(fifo)
                if code is None or self._stop_requested:
                    return
                if self._switching:
                    self._switching = False
                elif self._switched and not self._got_frame and code != 0:
                    self._revert_change()
                else:
                    if code != 0:
                        self._log(f"scrcpy exited with code {code}")
                    return
                live = self._pipeline
                if live is not None:
                    live.restart_reader()
        finally:
            shutil.rmtree(fifo.parent, ignore_errors=True)

    def _revert_change(self) -> None:
        """A camera or settings that would not start, go back to the last."""
        previous = self._previous
        if previous is None:
            return
        with self._lock:
            self._camera_id, self._settings = previous
            self._switched = False
            self._set_state(APPLYING)
        if self._pipeline is not None:
            self._pipeline.set_fps(self._settings.fps)
        self._log("That could not start, going back to the previous choice.")
        self._emit({"type": "camera", "id": self.camera()})
        self._emit({"type": "settings", **self.settings()})

    def _run_scrcpy(self, fifo: Path) -> int | None:
        """Run one scrcpy, returning its exit code, None if it never ran."""
        camera = self._camera()
        name = f"camera {camera.id}" if camera else "the default camera"
        self._log(f"Starting scrcpy on {name}...")
        try:
            process, lines = self._spawn(
                scrcpy_args(str(fifo), camera, self._settings)
            )
        except FileNotFoundError:
            self._log("scrcpy not found. Is it installed and on PATH?")
            return None
        with self._lock:
            self._process = process
            if self._stop_requested:
                process.terminate()
        for line in lines:
            self._log(line)
        code = process.wait()
        # An ending we asked for is SIGTERM, which is not an error.
        if code == SIGTERM_EXIT and (self._stop_requested or self._switching):
            return 0
        return code
