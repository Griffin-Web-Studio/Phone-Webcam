"""Turn the camera image on its way from scrcpy to the output device.

scrcpy records into a FIFO. One ffmpeg decodes it, the frames are turned here,
and a second ffmpeg that never closes feeds the device other apps use. The
turn is applied per frame, so changing it never interrupts the output. Frames
stay in planar YUV 4:2:0, which is half the size of RGB.
"""

import subprocess
import threading
import time
from collections.abc import Callable
from typing import Protocol

import numpy as np

# ──────────────────────────────────────────────────────────────────| Config |──
WIDTH = 1920
HEIGHT = 1080
FPS = 30
ROTATIONS = (0, 90, 180, 270)

# Black in YUV: luma 16, both chroma planes at the neutral 128.
BLACK = (16, 128, 128)

FFMPEG_QUIET = ["ffmpeg", "-hide_banner", "-loglevel", "error"]


# ──────────────────────────────────────────────────────────────| Processes |──
def end_process(process: subprocess.Popen, grace: float = 2.0) -> None:
    """Stop an ffmpeg promptly.

    ffmpeg only notices SIGTERM when it next wakes from reading, which may be
    never if nothing is feeding it. Closing its input ends it at once, and the
    signal and the kill are there for whatever is left.
    """
    if process.stdin is not None:
        try:
            process.stdin.close()
        except OSError, ValueError:
            pass
    process.terminate()
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


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
Planes = tuple[np.ndarray, np.ndarray, np.ndarray]


class PreviewSink(Protocol):
    """Anything that can take the turned frames for a preview."""

    def offer(self, planes: Planes) -> None: ...


class Pipeline:
    """Reads the recording, turns each frame, writes the output at a rate."""

    def __init__(
        self,
        source: str,
        output: str,
        log: Callable[[str], None],
        on_first_frame: Callable[[], None] | None = None,
        width: int = WIDTH,
        height: int = HEIGHT,
        fps: int = FPS,
    ) -> None:
        self._source = source
        self._output = output
        self._log = log
        self._on_first_frame = on_first_frame
        self._width = width
        self._height = height
        self._fps = fps
        self._frame_size = width * height * 3 // 2
        self._latest: bytes | bytearray = black_frame(width, height)
        self._turn = (0, False)
        self._preview: PreviewSink | None = None
        self._preview_every = 1
        self._preview_fps: int | None = None
        self._last_error = ""
        self._stopping = threading.Event()
        self._reader_quiet = threading.Event()
        self._reader: subprocess.Popen[bytes] | None = None
        self._writer: subprocess.Popen[bytes] | None = None
        self._threads: list[threading.Thread] = []
        self._reader_threads: list[threading.Thread] = []

    def set_orientation(self, rotation: int, mirror: bool) -> None:
        """Change the turn, taking effect on the next frame."""
        if rotation not in ROTATIONS:
            raise ValueError(f"rotation must be one of {ROTATIONS}")
        self._turn = (rotation, mirror)

    def set_preview(
        self, sink: PreviewSink | None, preview_fps: int | None = None
    ) -> None:
        """Send turned frames to a preview, or stop with None.

        The preview gets every nth frame, so it runs at about its own rate.
        """
        if preview_fps:
            self._preview_fps = preview_fps
            self._preview_every = max(1, round(self._fps / preview_fps))
        self._preview = sink

    def set_fps(self, fps: int) -> None:
        """Change the rate frames are written at, taking effect at once.

        The output device keeps its format, only the pace changes.
        """
        self._fps = fps
        if self._preview_fps:
            self._preview_every = max(1, round(fps / self._preview_fps))

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
        thread = threading.Thread(target=self._write_loop, daemon=True)
        thread.start()
        self._threads.append(thread)
        self._start_reader()

    def _start_reader(self) -> None:
        # Opening the FIFO waits for scrcpy to open its end, which is fine,
        # and a stop wakes it by ending the process.
        reader = subprocess.Popen(
            [
                "ffmpeg",
                *("-hide_banner", "-loglevel", "fatal"),
                *("-fflags", "nobuffer", "-flags", "low_delay"),
                *("-i", self._source),
                *("-vf", self._fit_filter()),
                *("-fps_mode", "passthrough"),
                *("-pix_fmt", "yuv420p", "-f", "rawvideo", "-"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._reader = reader
        self._reader_threads = [
            threading.Thread(
                target=self._read_loop, args=(reader,), daemon=True
            ),
            threading.Thread(
                target=self._drain_errors, args=(reader,), daemon=True
            ),
        ]
        for thread in self._reader_threads:
            thread.start()

    def _fit_filter(self) -> str:
        """Scale to the output size, padding when the shape differs."""
        w, h = self._width, self._height
        return (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        )

    def restart_reader(self) -> None:
        """Reconnect to a new recording while the output keeps running.

        The writer is untouched and keeps repeating the last frame, so apps
        see a short pause instead of a camera that vanished.
        """
        self._reader_quiet.set()
        try:
            if self._reader is not None:
                end_process(self._reader)
            for thread in self._reader_threads:
                thread.join(timeout=5)
            self._start_reader()
        finally:
            self._reader_quiet.clear()

    def quiet(self) -> None:
        """Expect the feed to end, so its ending is not reported as a fault."""
        self._stopping.set()

    def stop(self) -> None:
        self._stopping.set()
        for process in (self._reader, self._writer):
            if process is not None:
                end_process(process)
        for thread in (*self._threads, *self._reader_threads):
            thread.join(timeout=5)

    # ───────────────────────────────────────────────────────────────| Loops |──
    def _drain_errors(self, reader: subprocess.Popen[bytes]) -> None:
        """Keep the reader's stderr empty, so it never blocks on a full pipe."""
        stream = reader.stderr  # type: ignore[union-attr]
        for raw in iter(stream.readline, b""):
            text = raw.decode(errors="replace").strip()
            if text:
                self._last_error = text

    def _read_loop(self, reader: subprocess.Popen[bytes]) -> None:
        stream = reader.stdout  # type: ignore[union-attr]
        first = True
        while not self._stopping.is_set():
            frame = bytearray(self._frame_size)
            view = memoryview(frame)
            got = 0
            while got < self._frame_size:
                count = stream.readinto(view[got:])
                if not count:
                    if not (
                        self._stopping.is_set() or self._reader_quiet.is_set()
                    ):
                        self._log(
                            f"The camera feed ended. {self._last_error}".strip()
                        )
                    return
                got += count
            self._latest = frame
            if first:
                first = False
                if self._on_first_frame is not None:
                    self._on_first_frame()

    def _write_loop(self) -> None:
        stream = self._writer.stdin  # type: ignore[union-attr]
        deadline = time.monotonic()
        count = 0
        while not self._stopping.is_set():
            planes = self._turned(self._latest)
            try:
                for plane in planes:
                    stream.write(memoryview(np.ascontiguousarray(plane)))
            except BrokenPipeError, ValueError:
                if not self._stopping.is_set():
                    self._log("The webcam output closed unexpectedly.")
                return
            preview = self._preview
            if preview is not None and count % self._preview_every == 0:
                preview.offer(planes)
            count += 1
            deadline += 1 / self._fps
            delay = deadline - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                deadline = time.monotonic()

    def _turned(self, frame: bytes | bytearray) -> Planes:
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
