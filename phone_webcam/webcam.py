"""Run scrcpy as a virtual webcam, reporting progress through a callback.

Standard library only. All the slow work (pkexec, adb, scrcpy) happens on one
worker thread, and progress leaves through `emit`, so the UI never blocks and
nothing touches the UI from the wrong thread.
"""

import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from phone_webcam import deps

# ──────────────────────────────────────────────────────────────────| Config |──
CARD_LABEL = "Android Webcam"
CAMERA_SIZE = "1920x1080"
V4L2_SYSFS = Path("/sys/class/video4linux")
STARTED_MARKER = "v4l2 sink started"
SIGTERM_EXIT = -15

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


def find_device(
    label: str = CARD_LABEL, sysfs: Path = V4L2_SYSFS
) -> str | None:
    """Find the /dev/videoN node whose card label matches."""
    for entry in sorted(sysfs.glob("video*")):
        try:
            name = (entry / "name").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if name == label:
            return f"/dev/{entry.name}"
    return None


# ───────────────────────────────────────────────────────────────| Controller |──
class Webcam:
    """Starts and stops the webcam, one run at a time."""

    def __init__(self, emit: Emit) -> None:
        self._emit = emit
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._stop_requested = False
        self.state = STOPPED

    def start(self) -> None:
        """Begin a run on a worker thread, ignored if one is under way."""
        with self._lock:
            if self.state != STOPPED:
                return
            self._stop_requested = False
            self._set_state(STARTING)
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        """Ask the current run to end, ignored if nothing is running."""
        with self._lock:
            if self.state == STOPPED:
                return
            self._stop_requested = True
            self._set_state(STOPPING)
            if self._process is not None:
                self._process.terminate()

    # ──────────────────────────────────────────────────────────────| Worker |──
    def _set_state(self, state: str) -> None:
        self.state = state
        self._emit({"type": "state", "state": state})

    def _log(self, line: str) -> None:
        self._emit({"type": "log", "line": line})

    def _finish(self) -> None:
        with self._lock:
            self._process = None
            self._set_state(STOPPED)

    def _run(self) -> None:
        try:
            device = self._prepare()
            if device is not None and not self._stop_requested:
                self._stream(device)
        finally:
            self._finish()

    def _prepare(self) -> str | None:
        """Check the phone, load the module, find the device node."""
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

        if not deps.V4L2LOOPBACK_SYSFS.exists():
            self._log("Loading v4l2loopback, authentication may be asked...")
            result = subprocess.run(
                [
                    "pkexec",
                    "modprobe",
                    "v4l2loopback",
                    "exclusive_caps=1",
                    f"card_label={CARD_LABEL}",
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self._log(f"Failed to load v4l2loopback: {result.stderr}")
                return None
            self._log("v4l2loopback loaded.")

        device = find_device()
        if device is None:
            self._log(
                f"No webcam device labelled '{CARD_LABEL}'. The module may "
                "be loaded with another label, reload it and try again."
            )
        return device

    def _stream(self, device: str) -> None:
        """Run scrcpy until it exits, forwarding its output."""
        self._log(f"Starting scrcpy on {device}...")
        try:
            process = subprocess.Popen(
                scrcpy_args(device),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            self._log("scrcpy not found. Is it installed and on PATH?")
            return
        with self._lock:
            self._process = process
            if self._stop_requested:
                process.terminate()
        assert process.stdout is not None
        for line in process.stdout:
            self._log(line.rstrip())
            if STARTED_MARKER in line:
                with self._lock:
                    if not self._stop_requested:
                        self._set_state(RUNNING)
        code = process.wait()
        # A stop we asked for ends with SIGTERM, which is not an error.
        if code != 0 and not (self._stop_requested and code == SIGTERM_EXIT):
            self._log(f"scrcpy exited with code {code}")
