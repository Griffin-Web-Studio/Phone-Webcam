"""Draw the cover image, the "slate", that is shown instead of the camera.

An SVG file is filled in with the text to show and turned into one raw frame by
ffmpeg, which is already required and can draw SVG with its librsvg decoder.
The pipeline then repeats that frame, so it goes through the same turning as the
camera picture. Standard library only.
"""

import base64
import functools
import os
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from xml.sax.saxutils import escape

from phone_webcam import deps

# ──────────────────────────────────────────────────────────────────| Config |──
DEFAULT_TEMPLATE = Path(__file__).resolve().parent / "slates" / "default.svg"
ICON = Path(__file__).resolve().parent / "assets" / "phone-webcam.svg"
MAX_SVG_BYTES = 2_000_000
RENDER_TIMEOUT = 20

SHUTTER = "shutter"
# What is shown while the camera is busy, so a call does not look frozen.
NOTICES = {
    "starting": ("One moment", "Starting the camera"),
    "switching": ("One moment", "Switching camera"),
    "applying": ("One moment", "Changing settings"),
}

# The brand's dark blue as YUV, shown when a picture cannot be drawn.
FALLBACK_YUV = (59, 153, 114)


# ─────────────────────────────────────────────────────────────────| Helpers |──
@functools.lru_cache(maxsize=1)
def icon_address() -> str:
    """The app icon as a data: address, for an image inside the SVG.

    The renderer only finds files that are inside the SVG itself, which is why
    the icon is embedded and not linked. Empty if the icon is missing, which
    leaves the picture out and nothing else.
    """
    try:
        data = ICON.read_bytes()
    except OSError:
        return ""
    return "data:image/svg+xml;base64," + base64.b64encode(data).decode("ascii")


def fill_template(svg: str, title: str, subtitle: str) -> str:
    """Put the text and the icon into the placeholders, made safe for XML."""
    return (
        svg.replace("{{title}}", escape(title))
        .replace("{{subtitle}}", escape(subtitle))
        .replace("{{icon}}", icon_address())
    )


def solid_frame(width: int, height: int) -> bytes:
    """A plain frame in the brand blue, used when the SVG cannot be drawn."""
    luma, cb, cr = FALLBACK_YUV
    return (
        bytes([luma]) * (width * height)
        + bytes([cb]) * (width * height // 4)
        + bytes([cr]) * (width * height // 4)
    )


def has_svg_support() -> bool:
    """True if ffmpeg can draw SVG, which needs its librsvg decoder."""
    return bool(deps.ffmpeg_has_decoder("librsvg"))


def read_template(path: Path | None) -> str:
    """Read the SVG to draw, the default one when no path is given."""
    source = path or DEFAULT_TEMPLATE
    if source.stat().st_size > MAX_SVG_BYTES:
        raise ValueError(f"{source.name} is larger than 2 MB")
    return source.read_text(encoding="utf-8")


def check_svg(path: Path) -> str:
    """Try drawing a chosen SVG, returning why it cannot be, or empty if it can."""
    _, error = render_frame(path, "Test", "Test", 320, 180)
    return error


def render_frame(
    path: Path | None, title: str, subtitle: str, width: int, height: int
) -> tuple[bytes, str]:
    """Draw the slate as one I420 frame, with the reason if it fell back.

    The error is empty when the SVG was drawn. When it cannot be, a plain frame
    is returned, so a cover always covers.
    """
    try:
        svg = fill_template(read_template(path), title, subtitle)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return (
            solid_frame(width, height),
            f"The cover image cannot be read: {exc}",
        )

    handle, name = tempfile.mkstemp(suffix=".svg", prefix="phone-webcam-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(svg)
        try:
            proc = subprocess.run(
                [
                    "ffmpeg",
                    *("-hide_banner", "-loglevel", "error", "-nostdin"),
                    *("-i", name),
                    *("-vf", _fit(width, height)),
                    *("-pix_fmt", "yuv420p", "-frames:v", "1"),
                    *("-f", "rawvideo", "-"),
                ],
                capture_output=True,
                timeout=RENDER_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return (
                solid_frame(width, height),
                f"ffmpeg could not draw it: {exc}",
            )
    finally:
        os.unlink(name)

    expected = width * height * 3 // 2
    if proc.returncode != 0 or len(proc.stdout) != expected:
        reason = proc.stderr.decode(errors="replace").strip().splitlines()
        detail = reason[-1] if reason else "no picture came out"
        return solid_frame(width, height), f"ffmpeg could not draw it: {detail}"
    return proc.stdout, ""


def _fit(width: int, height: int) -> str:
    """Keep the picture's shape inside the output, padding what is left."""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    )


# ──────────────────────────────────────────────────────────────────| Slates |──
class Slates:
    """The frames to show, drawn once and kept until the settings change."""

    def __init__(
        self,
        width: int,
        height: int,
        render: Callable[..., tuple[bytes, str]] = render_frame,
    ) -> None:
        self._size = (width, height)
        self._render = render
        self._lock = threading.Lock()
        self._frames: dict[str, bytes] = {}
        self._generation = 0
        self._path: Path | None = None
        self._title = ""
        self._subtitle = ""
        self.error = ""

    def configure(self, path: Path | None, title: str, subtitle: str) -> None:
        """Use new text or a new SVG, which drops the frames drawn so far."""
        with self._lock:
            self._path = path
            self._title = title
            self._subtitle = subtitle
            self._frames = {}
            self._generation += 1
            self.error = ""

    def cached(self, kind: str) -> bytes | None:
        """The frame if it has been drawn already, without waiting for it."""
        with self._lock:
            return self._frames.get(kind)

    def frame(self, kind: str) -> bytes:
        """The frame for the shutter or a notice, drawn if it is not yet."""
        with self._lock:
            found = self._frames.get(kind)
            if found is not None:
                return found
            path, title, subtitle = self._path, self._title, self._subtitle
            generation = self._generation
        if kind != SHUTTER:
            title, subtitle = NOTICES[kind]
        frame, error = self._render(path, title, subtitle, *self._size)
        with self._lock:
            # A change made while drawing wins, so a stale frame is not kept.
            if generation == self._generation:
                self._frames[kind] = frame
                if error:
                    self.error = error
        return frame

    def warm(self) -> None:
        """Draw every frame at once, so showing one later takes no time."""
        threads = [
            threading.Thread(target=self.frame, args=(kind,))
            for kind in (SHUTTER, *NOTICES)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
