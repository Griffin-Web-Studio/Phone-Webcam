"""Watch for the phone through adb, and say what is wrong when it is absent.

Standard library only.
"""

import re
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass

# ──────────────────────────────────────────────────────────────────| Config |──
READY = "ready"
UNAUTHORISED = "unauthorised"
OFFLINE = "offline"
MISSING = "missing"
UNAVAILABLE = "unavailable"

POLL_SECONDS = 2.0

MESSAGES = {
    UNAUTHORISED: "The phone is asking to authorise USB debugging.",
    OFFLINE: "The phone is connected but not responding, try unplugging it.",
    MISSING: "No phone found. Connect it with USB debugging on.",
    UNAVAILABLE: "adb could not be run.",
}


# ──────────────────────────────────────────────────────────────────| Status |──
@dataclass(frozen=True)
class Phone:
    """What adb says about the phone."""

    state: str
    serial: str = ""

    @property
    def ready(self) -> bool:
        return self.state == READY


def parse_devices(output: str) -> Phone:
    """Read `adb devices` output, preferring a ready phone over the rest."""
    found: dict[str, str] = {}
    for line in output.splitlines()[1:]:
        serial, _, status = line.partition("\t")
        status = status.strip()
        if serial and status:
            found.setdefault(status, serial)
    if "device" in found:
        return Phone(READY, found["device"])
    if "unauthorized" in found:
        return Phone(UNAUTHORISED, found["unauthorized"])
    if "offline" in found:
        return Phone(OFFLINE, found["offline"])
    return Phone(MISSING)


def check_phone(timeout: float = 10) -> Phone:
    """Ask adb about the phone right now."""
    try:
        proc = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, timeout=timeout
        )
    except OSError, subprocess.TimeoutExpired:
        return Phone(UNAVAILABLE)
    return parse_devices(proc.stdout)


PROPERTY_LINE = re.compile(r"^\[(?P<key>[^\]]+)\]: \[(?P<value>.*)\]$")
# What is worth knowing about a phone when a camera misbehaves.
PROPERTIES = (
    "ro.product.manufacturer",
    "ro.product.model",
    "ro.build.version.release",
    "ro.build.version.sdk",
    "ro.build.display.id",
)


def parse_properties(output: str) -> dict[str, str]:
    """Read `adb shell getprop` output, keeping the properties of interest."""
    found: dict[str, str] = {}
    for line in output.splitlines():
        match = PROPERTY_LINE.match(line.strip())
        if match and match["key"] in PROPERTIES:
            found[match["key"]] = match["value"]
    return found


def read_properties(timeout: float = 10) -> dict[str, str]:
    """Ask the phone about itself, empty if it does not answer."""
    try:
        proc = subprocess.run(
            ["adb", "shell", "getprop"],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except OSError, subprocess.TimeoutExpired:
        return {}
    return parse_properties(proc.stdout)


# ─────────────────────────────────────────────────────────────────| Monitor |──
class Monitor:
    """Polls for the phone and reports every change, and only changes."""

    def __init__(
        self,
        emit: Callable[[dict], None],
        interval: float = POLL_SECONDS,
        check: Callable[[], Phone] | None = None,
    ) -> None:
        self._emit = emit
        self._interval = interval
        self._check = check or check_phone
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.current: Phone | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def poll(self) -> Phone:
        """Check once, reporting it if it differs from the last result."""
        phone = self._check()
        if phone != self.current:
            self.current = phone
            self._emit(
                {"type": "phone", "state": phone.state, "serial": phone.serial}
            )
        return phone

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.poll()
            self._stop.wait(self._interval)
