"""A live preview of the output, served as MJPEG on a local port.

The pipeline hands over the frames it has already turned, so the preview shows
exactly what other apps receive and never opens a loopback device. A small
ffmpeg shrinks and encodes them, and the page shows the stream in an <img>.
"""

import secrets
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from phone_webcam.pipeline import end_process

# ──────────────────────────────────────────────────────────────────| Config |──
PREVIEW_WIDTH = 480
JPEG_END = b"\xff\xd9"
BOUNDARY = "frame"

Planes = tuple[np.ndarray, np.ndarray, np.ndarray]


# ───────────────────────────────────────────────────────────────| Frame hub |──
class Hub:
    """Holds the newest JPEG and wakes every viewer when it changes."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._frame = b""
        self._serial = 0
        self.closed = False

    def publish(self, frame: bytes) -> None:
        with self._cond:
            self._frame = frame
            self._serial += 1
            self._cond.notify_all()

    def wait(self, seen: int, timeout: float) -> tuple[int, bytes] | None:
        """Block for a frame newer than `seen`, None on timeout or close."""
        with self._cond:
            self._cond.wait_for(
                lambda: self._serial != seen or self.closed, timeout
            )
            if self.closed or self._serial == seen:
                return None
            return self._serial, self._frame

    def close(self) -> None:
        with self._cond:
            self.closed = True
            self._cond.notify_all()


def split_jpegs(buffer: bytearray) -> list[bytes]:
    """Cut complete JPEGs off the front of a buffer, keeping the rest."""
    frames = []
    while (end := buffer.find(JPEG_END)) != -1:
        frames.append(bytes(buffer[: end + 2]))
        del buffer[: end + 2]
    return frames


# ──────────────────────────────────────────────────────────────────| Server |──
class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, path: str, hub: Hub) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.path = path
        self.hub = hub


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, *_args) -> None:
        pass

    def do_GET(self) -> None:
        if self.path != self.server.path:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header(
            "Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}"
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        seen = 0
        hub = self.server.hub
        try:
            while not hub.closed:
                item = hub.wait(seen, 1.0)
                if item is None:
                    continue
                seen, frame = item
                self.wfile.write(
                    f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                    f"Content-Length: {len(frame)}\r\n\r\n".encode()
                    + frame
                    + b"\r\n"
                )
        except BrokenPipeError, ConnectionResetError:
            return


# ─────────────────────────────────────────────────────────────────| Preview |──
class Preview:
    """Encodes offered frames and serves them until stopped."""

    def __init__(self, width: int, height: int, fps: int = 30) -> None:
        self._width = width
        self._height = height
        self._fps = fps
        self._hub = Hub()
        self._server: _Server | None = None
        self._encoder: subprocess.Popen[bytes] | None = None
        self._pending: Planes | None = None
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> str:
        """Start encoding and serving, returning the stream's address."""
        size = f"{self._width}x{self._height}"
        self._encoder = subprocess.Popen(
            [
                "ffmpeg",
                *("-hide_banner", "-loglevel", "fatal"),
                *("-f", "rawvideo", "-pix_fmt", "yuv420p"),
                *("-video_size", size, "-framerate", str(self._fps)),
                *("-i", "-", "-vf", f"scale={PREVIEW_WIDTH}:-2"),
                *("-q:v", "6", "-flush_packets", "1", "-f", "mjpeg", "-"),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            bufsize=0,
        )
        path = f"/{secrets.token_urlsafe(12)}.mjpg"
        self._server = _Server(path, self._hub)
        for target in (
            self._feed,
            self._collect,
            lambda: self._server.serve_forever(poll_interval=0.05),
        ):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self._threads.append(thread)
        return f"http://127.0.0.1:{self._server.server_port}{path}"

    def offer(self, planes: Planes) -> None:
        """Take the newest frame, replacing one the encoder has not used."""
        self._pending = planes
        self._wake.set()

    def wait_for_first_frame(self, timeout: float) -> bool:
        """Block until a picture can be served, False if none arrives."""
        return self._hub.wait(0, timeout) is not None

    def stop(self) -> None:
        self._stopping.set()
        self._wake.set()
        self._hub.close()
        # End the encoder first, so the thread reading it is released at once.
        if self._encoder is not None:
            end_process(self._encoder)
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        for thread in self._threads:
            thread.join(timeout=5)

    # ───────────────────────────────────────────────────────────────| Loops |──
    def _feed(self) -> None:
        stream = self._encoder.stdin  # type: ignore[union-attr]
        while not self._stopping.is_set():
            self._wake.wait()
            self._wake.clear()
            planes, self._pending = self._pending, None
            if planes is None:
                continue
            try:
                for plane in planes:
                    stream.write(memoryview(np.ascontiguousarray(plane)))
            except BrokenPipeError, ValueError:
                return

    def _collect(self) -> None:
        stream = self._encoder.stdout  # type: ignore[union-attr]
        buffer = bytearray()
        while chunk := stream.read(65536):
            buffer += chunk
            for frame in split_jpegs(buffer):
                self._hub.publish(frame)
