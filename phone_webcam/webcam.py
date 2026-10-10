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
from pathlib import Path

from phone_webcam import deps, loopback, pipeline
from phone_webcam.preview import Preview

# ──────────────────────────────────────────────────────────────────| Config |──
CAMERA_SIZE = f"{pipeline.WIDTH}x{pipeline.HEIGHT}"
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

Emit = Callable[[dict], None]


# ─────────────────────────────────────────────────────────────────| Helpers |──
def scrcpy_args(fifo: str) -> list[str]:
    """The scrcpy command line that records the phone camera into a FIFO."""
    return [
        "scrcpy",
        "--no-window",
        "--no-audio",
        "--video-source=camera",
        f"--camera-size={CAMERA_SIZE}",
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


def parse_adb_devices(output: str) -> tuple[list[str], list[str]]:
    """Split `adb devices` output into ready and unauthorised serials."""
    ready: list[str] = []
    unauthorised: list[str] = []
    for line in output.splitlines()[1:]:
        serial, _, status = line.partition("\t")
        if status.strip() == "device":
            ready.append(serial)
        elif status.strip() == "unauthorized":
            unauthorised.append(serial)
    return ready, unauthorised


# ───────────────────────────────────────────────────────────────| Controller |──
class Webcam:
    """Starts and stops the webcam, one run at a time."""

    def __init__(
        self, emit: Emit, rotation: int = 0, mirror: bool = False
    ) -> None:
        self._emit = emit
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._pipeline: pipeline.Pipeline | None = None
        self._preview: Preview | None = None
        self._preview_busy = False
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
        preview = Preview(pipeline.WIDTH, pipeline.HEIGHT)
        try:
            url = preview.start()
        except OSError as exc:
            self._log(f"Could not start the preview: {exc}")
            self._emit_preview("closed")
            return
        self._preview = preview
        live.set_preview(preview)
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
        with self._lock:
            if self.state == STARTING:
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
        try:
            proc = subprocess.run(
                ["adb", "devices"], capture_output=True, text=True, timeout=30
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._log(f"Could not run adb: {exc}")
            return None
        ready, unauthorised = parse_adb_devices(proc.stdout)
        if not ready:
            if unauthorised:
                self._log("The phone is asking to authorise USB debugging.")
            else:
                self._log("No phone found. Connect it with USB debugging on.")
            return None
        self._log(f"Phone found: {ready[0]}")

        if not self._ensure_devices():
            return None
        output = loopback.find_device(loopback.OUTPUT_LABEL)
        if output is None:
            self._log("The webcam device could not be found.")
        return output

    def _start_pipeline(self, fifo: str, output: str) -> bool:
        live = pipeline.Pipeline(fifo, output, self._log, self._on_first_frame)
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

    def _stream(self, output: str) -> None:
        """Run scrcpy until it exits, forwarding its output."""
        fifo = make_fifo()
        try:
            # The reader opens its end first, scrcpy then opens the other.
            if not self._start_pipeline(str(fifo), output):
                return
            self._log(f"Starting scrcpy, the webcam is {output}...")
            try:
                process, lines = self._spawn(scrcpy_args(str(fifo)))
            except FileNotFoundError:
                self._log("scrcpy not found. Is it installed and on PATH?")
                return
            with self._lock:
                self._process = process
                if self._stop_requested:
                    process.terminate()
            for line in lines:
                self._log(line)
            code = process.wait()
            # A stop we asked for ends with SIGTERM, which is not an error.
            if code != 0 and not (
                self._stop_requested and code == SIGTERM_EXIT
            ):
                self._log(f"scrcpy exited with code {code}")
        finally:
            shutil.rmtree(fifo.parent, ignore_errors=True)
