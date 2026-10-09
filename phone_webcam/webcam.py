"""Run scrcpy as a virtual webcam, reporting progress through a callback.

All the slow work (pkexec, adb, scrcpy, ffmpeg) happens on worker threads, and
progress leaves through `emit`, so the UI never blocks and nothing touches the
UI from the wrong thread.

scrcpy writes into a hidden loopback device and a pipeline copies it, turned
as asked, into the device other apps open. Turning therefore works live,
without restarting scrcpy or interrupting the output.
"""

import os
import pty
import re
import shutil
import subprocess
import threading
from collections.abc import Callable, Iterator

from phone_webcam import deps, loopback, pipeline

# ──────────────────────────────────────────────────────────────────| Config |──
CAMERA_SIZE = f"{pipeline.WIDTH}x{pipeline.HEIGHT}"
STARTED_MARKER = "v4l2 sink started"
SIGTERM_EXIT = -15
CONFIRM_TIMEOUT = 300

STOPPED = "stopped"
STARTING = "starting"
RUNNING = "running"
STOPPING = "stopping"

Emit = Callable[[dict], None]


# ─────────────────────────────────────────────────────────────────| Helpers |──
def scrcpy_args(device: str) -> list[str]:
    """The scrcpy command line that turns the phone camera into a webcam."""
    return [
        "scrcpy",
        f"--v4l2-sink={device}",
        "--no-window",
        "--video-source=camera",
        f"--camera-size={CAMERA_SIZE}",
        "--no-audio",
    ]


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
        self._preview: subprocess.Popen[bytes] | None = None
        self._output: str | None = None
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
        """Open or close an ffplay window showing the output device."""
        with self._lock:
            if self._preview is not None:
                self._preview.terminate()
                return
            output = self._output
        if output is None:
            self._log("Start the webcam first, there is nothing to preview.")
            return
        ffplay = shutil.which("ffplay")
        if ffplay is None:
            self._log("ffplay is not installed, install ffmpeg to preview.")
            return
        preview = subprocess.Popen(
            [
                ffplay,
                *("-loglevel", "error", "-fflags", "nobuffer"),
                *("-window_title", "Preview", output),
            ],
        )
        with self._lock:
            self._preview = preview
        self._emit({"type": "preview", "open": True})
        threading.Thread(target=self._watch_preview, daemon=True).start()

    # ──────────────────────────────────────────────────────────────| Worker |──
    def _set_state(self, state: str) -> None:
        self.state = state
        self._emit({"type": "state", "state": state})

    def _log(self, line: str) -> None:
        self._emit({"type": "log", "line": line})

    def _watch_preview(self) -> None:
        preview = self._preview
        if preview is not None:
            preview.wait()
        with self._lock:
            self._preview = None
        self._emit({"type": "preview", "open": False})

    def _finish(self) -> None:
        live, self._pipeline = self._pipeline, None
        if live is not None:
            live.stop()
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
            self._process = None
            self._output = None
            if self._preview is not None:
                self._preview.terminate()
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
            devices = self._prepare()
            if devices is not None and not self._stop_requested:
                self._stream(*devices)
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
        """Make sure the source and output loopback devices both exist."""
        missing = loopback.missing_labels()
        if not missing:
            return True

        if not deps.V4L2LOOPBACK_SYSFS.exists():
            self._log("Loading v4l2loopback, authentication may be asked...")
            if not self._pkexec(loopback.load_command()):
                return False
        else:
            if loopback.has_ctl():
                self._log("Adding the webcam devices...")
                if self._pkexec(loopback.add_command(missing)):
                    return not loopback.missing_labels()
            if loopback.module_in_use():
                self._log(
                    "The webcam devices cannot be set up while another app "
                    "uses v4l2loopback. Close it and try again."
                )
                return False
            if not self._confirm(
                "The webcam devices have to be created by reloading "
                "v4l2loopback. Other virtual cameras, such as OBS's, are "
                "removed until they are set up again. Reload it now?"
            ):
                self._log("Reload declined, the webcam was not started.")
                return False
            if not self._pkexec(loopback.reload_command()):
                return False

        if loopback.missing_labels():
            self._log("The webcam devices were not created.")
            return False
        return True

    def _prepare(self) -> tuple[str, str] | None:
        """Check the phone, set up the devices, find the device nodes."""
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
        source = loopback.find_device(loopback.SOURCE_LABEL)
        output = loopback.find_device(loopback.OUTPUT_LABEL)
        if source is None or output is None:
            self._log("The webcam devices could not be found.")
            return None
        return source, output

    def _start_pipeline(self, source: str, output: str) -> None:
        live = pipeline.Pipeline(source, output, self._log)
        live.set_orientation(*self._turn)
        try:
            live.start()
        except OSError as exc:
            self._log(f"Could not start ffmpeg: {exc}")
            return
        self._pipeline = live

    @staticmethod
    def _spawn(args: list[str]) -> tuple[subprocess.Popen, Iterator[str]]:
        """Start a process on a pty and return it with its output lines.

        scrcpy buffers its own messages when writing to a pipe, so the start
        marker would only arrive on exit. A pty makes it print line by line.
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

    def _stream(self, source: str, output: str) -> None:
        """Run scrcpy until it exits, forwarding its output."""
        self._log(f"Starting scrcpy on {source}...")
        try:
            process, lines = self._spawn(scrcpy_args(source))
        except FileNotFoundError:
            self._log("scrcpy not found. Is it installed and on PATH?")
            return
        with self._lock:
            self._process = process
            if self._stop_requested:
                process.terminate()
        for line in lines:
            self._log(line)
            if STARTED_MARKER in line and not self._stop_requested:
                self._start_pipeline(source, output)
                with self._lock:
                    self._output = output
                    self._set_state(RUNNING)
        code = process.wait()
        # A stop we asked for ends with SIGTERM, which is not an error.
        if code != 0 and not (self._stop_requested and code == SIGTERM_EXIT):
            self._log(f"scrcpy exited with code {code}")
