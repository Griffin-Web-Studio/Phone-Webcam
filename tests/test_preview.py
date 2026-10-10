"""Tests for the MJPEG preview stream."""

import subprocess
import time
import urllib.request

import numpy as np

from phone_webcam import preview

JPEG_A = b"\xff\xd8AAA\xff\xd9"
JPEG_B = b"\xff\xd8BBBB\xff\xd9"


def test_split_jpegs_keeps_the_unfinished_tail():
    buffer = bytearray(JPEG_A + JPEG_B + b"\xff\xd8CC")
    assert preview.split_jpegs(buffer) == [JPEG_A, JPEG_B]
    assert bytes(buffer) == b"\xff\xd8CC"


def test_split_jpegs_waits_for_a_whole_image():
    buffer = bytearray(b"\xff\xd8AA")
    assert preview.split_jpegs(buffer) == []
    buffer += b"\xff\xd9"
    assert preview.split_jpegs(buffer) == [b"\xff\xd8AA\xff\xd9"]


def test_hub_hands_viewers_only_newer_frames():
    hub = preview.Hub()
    assert hub.wait(0, 0.01) is None
    hub.publish(JPEG_A)
    assert hub.wait(0, 0.01) == (1, JPEG_A)
    assert hub.wait(1, 0.01) is None


def test_closed_hub_releases_waiting_viewers():
    hub = preview.Hub()
    hub.close()
    assert hub.wait(0, 5) is None


class FakeEncoder:
    """Stands in for ffmpeg: swallows raw frames and emits two JPEGs."""

    def __init__(self):
        outer = self
        self.received = bytearray()
        self.alive = True

        class Stdin:
            def write(self, chunk):
                outer.received += bytes(chunk)

            def close(self):
                pass

        class Stdout:
            def __init__(self):
                self.parts = [JPEG_A + JPEG_B[:3], JPEG_B[3:]]

            def read(self, _size):
                if self.parts:
                    return self.parts.pop(0)
                while outer.alive:
                    time.sleep(0.01)
                return b""

        self.stdin = Stdin()
        self.stdout = Stdout()

    def terminate(self):
        self.alive = False

    def kill(self):
        self.alive = False

    def wait(self, timeout=None):
        return 0


def test_stream_serves_multipart_jpegs_on_a_secret_path(monkeypatch):
    encoder = FakeEncoder()
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: encoder)
    stream = preview.Preview(16, 8)
    url = stream.start()
    try:
        assert url.startswith("http://127.0.0.1:")
        assert url.endswith(".mjpg")
        with urllib.request.urlopen(url, timeout=5) as response:
            assert response.headers["Content-Type"].startswith(
                "multipart/x-mixed-replace"
            )
            body = response.read1(400)
        assert b"image/jpeg" in body
        assert JPEG_B in body
    finally:
        stream.stop()


def test_wrong_path_is_not_served(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: FakeEncoder())
    stream = preview.Preview(16, 8)
    url = stream.start()
    try:
        bad = url.rsplit("/", 1)[0] + "/guess.mjpg"
        try:
            urllib.request.urlopen(bad, timeout=5)
            assert False, "the wrong path must not be served"
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        stream.stop()


def test_offered_frames_reach_the_encoder(monkeypatch):
    encoder = FakeEncoder()
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: encoder)
    stream = preview.Preview(16, 8)
    stream.start()
    try:
        planes = (
            np.zeros((8, 16), np.uint8),
            np.zeros((4, 8), np.uint8),
            np.zeros((4, 8), np.uint8),
        )
        stream.offer(planes)
        for _ in range(100):
            if len(encoder.received) == 16 * 8 * 3 // 2:
                break
            time.sleep(0.01)
        assert len(encoder.received) == 16 * 8 * 3 // 2
    finally:
        stream.stop()


def test_waiting_for_the_first_frame(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: FakeEncoder())
    stream = preview.Preview(16, 8)
    stream.start()
    try:
        assert stream.wait_for_first_frame(5) is True
    finally:
        stream.stop()


def test_no_first_frame_times_out():
    stream = preview.Preview(16, 8)
    assert stream.wait_for_first_frame(0.01) is False


def test_stop_is_quick(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: FakeEncoder())
    stream = preview.Preview(16, 8)
    stream.start()
    began = time.monotonic()
    stream.stop()
    assert time.monotonic() - began < 1
