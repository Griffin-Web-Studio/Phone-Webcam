"""Turn the camera image on its way from the source to the output device.

scrcpy writes into a hidden loopback device. One ffmpeg reads it, the frames
are turned here, and a second ffmpeg that never closes feeds the device other
apps use. The turn is applied per frame, so changing it never interrupts the
output. Frames stay in planar YUV 4:2:0, which is what scrcpy delivers and
half the size of RGB.
"""

import subprocess
import threading
import time
from collections.abc import Callable

import numpy as np

# ──────────────────────────────────────────────────────────────────| Config |──
WIDTH = 1920
HEIGHT = 1080
FPS = 30
ROTATIONS = (0, 90, 180, 270)

# Black in YUV: luma 16, both chroma planes at the neutral 128.
BLACK = (16, 128, 128)

FFMPEG_QUIET = ["ffmpeg", "-hide_banner", "-loglevel", "error"]

# A loopback source only offers capture once its producer has written a frame,
# which happens a moment after scrcpy reports the sink as started.
CONNECT_ATTEMPTS = 40
CONNECT_DELAY = 0.5


# ───────────────────────────────────────────────────────────────| Turning |──
def orient_plane(
    plane: np.ndarray,
    rotation: int,
    mirror: bool,
    out_height: int,
    out_width: int,
    pad: int,
) -> np.ndarray:
    """Rotate clockwise, mirror, and fit the plane into the output size.

    A plane that no longer matches the output shape (a portrait turn) is
    scaled down to fit and centred on a padded canvas. Nearest neighbour is
    enough for a live feed and keeps the cost low.
    """
    img = np.rot90(plane, k=-(rotation // 90) % 4)
    if mirror:
        img = img[:, ::-1]
    height, width = img.shape
    if (height, width) == (out_height, out_width):
        return img

    scale = min(out_height / height, out_width / width)
    new_h = max(1, round(height * scale))
    new_w = max(1, round(width * scale))
    rows = np.arange(new_h) * height // new_h
    cols = np.arange(new_w) * width // new_w
    canvas = np.full((out_height, out_width), pad, dtype=np.uint8)
    top = (out_height - new_h) // 2
    left = (out_width - new_w) // 2
    canvas[top : top + new_h, left : left + new_w] = img[rows[:, None], cols]
    return canvas


def split_planes(
    frame: bytes | bytearray, width: int, height: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """View one I420 frame as its Y, U and V planes without copying."""
    data = np.frombuffer(frame, dtype=np.uint8)
    luma = width * height
    chroma = luma // 4
    return (
        data[:luma].reshape(height, width),
        data[luma : luma + chroma].reshape(height // 2, width // 2),
        data[luma + chroma : luma + 2 * chroma].reshape(
            height // 2, width // 2
        ),
    )


def black_frame(width: int, height: int) -> bytes:
    """A black I420 frame, shown until the first real one arrives."""
    luma, cb, cr = BLACK
    return (
        bytes([luma]) * (width * height)
        + bytes([cb]) * (width * height // 4)
        + bytes([cr]) * (width * height // 4)
    )


# ─────────────────────────────────────────────────────────────────| Pipeline |──
class Pipeline:
    """Reads the source, turns each frame, writes the output at a fixed rate."""

    def __init__(
        self,
        source: str,
        output: str,
        log: Callable[[str], None],
        width: int = WIDTH,
        height: int = HEIGHT,
        fps: int = FPS,
    ) -> None:
        self._source = source
        self._output = output
        self._log = log
        self._width = width
        self._height = height
        self._fps = fps
        self._frame_size = width * height * 3 // 2
        self._latest: bytes | bytearray = black_frame(width, height)
        self._turn = (0, False)
        self._stopping = threading.Event()
        self._reader: subprocess.Popen[bytes] | None = None
        self._writer: subprocess.Popen[bytes] | None = None
        self._threads: list[threading.Thread] = []

    def set_orientation(self, rotation: int, mirror: bool) -> None:
        """Change the turn, taking effect on the next frame."""
        if rotation not in ROTATIONS:
            raise ValueError(f"rotation must be one of {ROTATIONS}")
        self._turn = (rotation, mirror)

    def _open_reader(self) -> subprocess.Popen[bytes]:
        size = f"{self._width}x{self._height}"
        return subprocess.Popen(
            [
                *FFMPEG_QUIET,
                *("-f", "v4l2", "-video_size", size, "-i", self._source),
                *("-vf", f"scale={self._width}:{self._height}"),
                *("-pix_fmt", "yuv420p", "-f", "rawvideo", "-"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

    def start(self) -> None:
        size = f"{self._width}x{self._height}"
        self._writer = subprocess.Popen(
            [
                *FFMPEG_QUIET,
                *("-f", "rawvideo", "-pix_fmt", "yuv420p"),
                *("-video_size", size, "-framerate", str(self._fps)),
                *("-i", "-", "-f", "v4l2", "-pix_fmt", "yuv420p"),
                self._output,
            ],
            stdin=subprocess.PIPE,
            bufsize=0,
        )
        for target in (self._read_loop, self._write_loop):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stopping.set()
        for process in (self._reader, self._writer):
            if process is not None:
                process.terminate()
        for process in (self._reader, self._writer):
            if process is not None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        for thread in self._threads:
            thread.join(timeout=5)

    # ───────────────────────────────────────────────────────────────| Loops |──
    def _read_loop(self) -> None:
        """Keep a reader connected, retrying until the source is ready."""
        for attempt in range(CONNECT_ATTEMPTS):
            if self._stopping.is_set():
                return
            try:
                self._reader = self._open_reader()
            except OSError as exc:
                self._log(f"Could not start ffmpeg: {exc}")
                return
            if self._read_frames(self._reader):
                return
            reason = self._reader.stderr.read().decode(errors="replace")
            self._reader.wait()
            if self._stopping.wait(CONNECT_DELAY):
                return
        last = reason.strip().splitlines()[-1] if reason.strip() else ""
        self._log(f"Could not read the camera feed. {last}".strip())

    def _read_frames(self, reader: subprocess.Popen[bytes]) -> bool:
        """Store frames until the feed ends, False if none ever arrived."""
        stream = reader.stdout
        received = False
        while not self._stopping.is_set():
            frame = bytearray(self._frame_size)
            view = memoryview(frame)
            got = 0
            while got < self._frame_size:
                count = stream.readinto(view[got:])
                if not count:
                    if received and not self._stopping.is_set():
                        self._log("The camera feed ended.")
                    return received
                got += count
            received = True
            self._latest = frame
        return True

    def _write_loop(self) -> None:
        stream = self._writer.stdin  # type: ignore[union-attr]
        interval = 1 / self._fps
        deadline = time.monotonic()
        while not self._stopping.is_set():
            try:
                for plane in self._turned(self._latest):
                    stream.write(memoryview(np.ascontiguousarray(plane)))
            except BrokenPipeError, ValueError:
                if not self._stopping.is_set():
                    self._log("The webcam output closed unexpectedly.")
                return
            deadline += interval
            delay = deadline - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                deadline = time.monotonic()

    def _turned(
        self, frame: bytes | bytearray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        rotation, mirror = self._turn
        luma, cb, cr = split_planes(frame, self._width, self._height)
        if rotation == 0 and not mirror:
            return luma, cb, cr
        h, w = self._height, self._width
        return (
            orient_plane(luma, rotation, mirror, h, w, BLACK[0]),
            orient_plane(cb, rotation, mirror, h // 2, w // 2, BLACK[1]),
            orient_plane(cr, rotation, mirror, h // 2, w // 2, BLACK[2]),
        )
