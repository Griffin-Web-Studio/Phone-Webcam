"""List the phone's cameras through scrcpy and choose a size for each.

Standard library only.
"""

import re
import subprocess
from dataclasses import dataclass

# ──────────────────────────────────────────────────────────────────| Config |──
DEFAULT_SIZE = "1920x1080"
MAX_WIDTH = 1920
MAX_HEIGHT = 1080

CAMERA_LINE = re.compile(
    r"--camera-id=(?P<id>\S+)\s+\((?P<facing>[^,)]+)(?:,\s*(?P<size>\d+x\d+))?"
    # scrcpy 5 writes the rates in braces, fps={15, 30}, older ones in brackets.
    r"(?:,\s*fps=[\[{](?P<fps>[\d,\s]*)[\]}])?"
)
SIZE_LINE = re.compile(r"^\s*-\s*(?P<size>\d+x\d+)\s*$")


# ─────────────────────────────────────────────────────────────────| Cameras |──
@dataclass(frozen=True)
class Camera:
    """One camera as scrcpy reports it."""

    id: str
    facing: str
    sizes: tuple[str, ...] = ()
    fps: tuple[int, ...] = ()

    @property
    def label(self) -> str:
        best = self.sizes[0] if self.sizes else ""
        detail = f", {best}" if best else ""
        # The limit is worth showing, a camera cannot be asked for more.
        rate = f", up to {max(self.fps)} fps" if self.fps else ""
        return f"{self.facing.capitalize()} camera {self.id}{detail}{rate}"


def parse_cameras(text: str) -> list[Camera]:
    """Read the output of `scrcpy --list-cameras`.

    Each camera is a `--camera-id=N (facing, WxH, fps=[...])` line, followed by
    `- WxH` lines for the sizes it supports. High speed modes, which carry a
    frame rate after the size, are not matched, they are not wanted.
    """
    cameras: list[Camera] = []
    current: dict | None = None
    for line in text.splitlines():
        header = CAMERA_LINE.search(line)
        if header:
            current = {
                "id": header["id"],
                "facing": header["facing"].strip(),
                "sizes": [header["size"]] if header["size"] else [],
                "fps": [
                    int(n)
                    for n in (header["fps"] or "").split(",")
                    if n.strip()
                ],
            }
            cameras.append(current)  # type: ignore[arg-type]
            continue
        size = SIZE_LINE.match(line)
        if (
            size
            and current is not None
            and size["size"] not in current["sizes"]
        ):
            current["sizes"].append(size["size"])
    return [
        Camera(
            c["id"], c["facing"], tuple(c["sizes"]), tuple(c["fps"])
        )  # type: ignore[index]
        for c in cameras
    ]


def pick_size(
    sizes: tuple[str, ...],
    limit: tuple[int, int] = (MAX_WIDTH, MAX_HEIGHT),
) -> str:
    """The largest size within the limit, preferring 16:9, else the limit."""
    fitting = []
    for size in sizes:
        width, height = (int(part) for part in size.split("x"))
        if width <= limit[0] and height <= limit[1]:
            wide = abs(width * 9 - height * 16) < 16
            fitting.append((wide, width * height, size))
    if not fitting:
        return f"{limit[0]}x{limit[1]}"
    return max(fitting)[2]


def pick_fps(supported: tuple[int, ...], wanted: int) -> int:
    """The wanted rate, or the closest one the camera offers below it."""
    if not supported or wanted in supported:
        return wanted
    below = [rate for rate in supported if rate <= wanted]
    return max(below) if below else min(supported)


def unread_lines(text: str) -> list[str]:
    """The lines that mention a camera id but that the parser did not read.

    scrcpy's wording changes between versions, and a line that stops matching
    would otherwise just make a camera, or its limits, quietly vanish.
    """
    return [
        line.strip()
        for line in text.splitlines()
        if "--camera-id=" in line and not CAMERA_LINE.search(line)
    ]


def read_listing(timeout: float = 30) -> str:
    """What `scrcpy --list-cameras` prints, empty if it cannot be run."""
    try:
        proc = subprocess.run(
            ["scrcpy", "--list-cameras"],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except OSError, subprocess.TimeoutExpired:
        return ""
    return proc.stdout + "\n" + proc.stderr


def list_cameras(timeout: float = 30) -> list[Camera]:
    """Ask scrcpy for the phone's cameras, empty if it cannot."""
    return parse_cameras(read_listing(timeout))
