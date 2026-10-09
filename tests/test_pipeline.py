"""Tests for turning frames and for the pipeline's process handling."""

import subprocess

import numpy as np
import pytest

from phone_webcam import pipeline

W, H = 16, 8


def frame():
    """A frame whose bytes are all different, so any move shows up."""
    return bytearray(np.arange(W * H * 3 // 2, dtype=np.uint8))


# ───────────────────────────────────────────────────────────────| Turning |──
def plane():
    return np.arange(6, dtype=np.uint8).reshape(2, 3)


def test_zero_turn_keeps_the_plane():
    out = pipeline.orient_plane(plane(), 0, False, 2, 3, 0)
    assert (out == plane()).all()


def test_ninety_turns_clockwise():
    out = pipeline.orient_plane(plane(), 90, False, 3, 2, 0)
    assert out.tolist() == [[3, 0], [4, 1], [5, 2]]


def test_one_eighty_reverses_both_axes():
    out = pipeline.orient_plane(plane(), 180, False, 2, 3, 0)
    assert out.tolist() == [[5, 4, 3], [2, 1, 0]]


def test_two_seventy_turns_anticlockwise():
    out = pipeline.orient_plane(plane(), 270, False, 3, 2, 0)
    assert out.tolist() == [[2, 5], [1, 4], [0, 3]]


def test_mirror_flips_the_turned_image():
    out = pipeline.orient_plane(plane(), 0, True, 2, 3, 0)
    assert out.tolist() == [[2, 1, 0], [5, 4, 3]]


def test_portrait_is_letterboxed_into_the_output_size():
    out = pipeline.orient_plane(
        np.full((H, W), 200, np.uint8), 90, False, H, W, 16
    )
    assert out.shape == (H, W)
    assert (out[:, 0] == 16).all() and (out[:, -1] == 16).all()
    assert (out[:, W // 2] == 200).all()


# ─────────────────────────────────────────────────────────────────| Frames |──
def test_split_planes_has_i420_shapes():
    luma, cb, cr = pipeline.split_planes(frame(), W, H)
    assert luma.shape == (H, W)
    assert cb.shape == cr.shape == (H // 2, W // 2)


def test_black_frame_has_the_right_size_and_values():
    data = pipeline.black_frame(W, H)
    assert len(data) == W * H * 3 // 2
    luma, cb, cr = pipeline.split_planes(data, W, H)
    assert (luma == 16).all() and (cb == 128).all() and (cr == 128).all()


def test_turned_frames_always_match_the_output_size():
    live = pipeline.Pipeline("src", "out", print, W, H)
    for rotation in pipeline.ROTATIONS:
        for mirror in (False, True):
            live.set_orientation(rotation, mirror)
            luma, cb, cr = live._turned(frame())
            assert luma.shape == (H, W)
            assert cb.shape == cr.shape == (H // 2, W // 2)


def test_bad_rotation_is_rejected():
    live = pipeline.Pipeline("src", "out", print, W, H)
    with pytest.raises(ValueError):
        live.set_orientation(45, False)


# ───────────────────────────────────────────────────────────────| Processes |──
class FakeStream:
    def __init__(self, data=b""):
        self.data = memoryview(data)
        self.written = bytearray()

    def readinto(self, buf):
        count = min(len(buf), len(self.data))
        buf[:count] = self.data[:count]
        self.data = self.data[count:]
        return count

    def write(self, chunk):
        self.written += bytes(chunk)

    def read(self):
        return self.data.tobytes()


class FakeProcess:
    def __init__(self, data=b"", error=b""):
        self.stdout = FakeStream(data)
        self.stdin = FakeStream()
        self.stderr = FakeStream(error)

    def terminate(self):
        pass

    def kill(self):
        pass

    def wait(self, timeout=None):
        return 0


def fake_popen(reader_runs, writer):
    """Hand out the writer for stdin pipes and each reader in turn."""
    readers = iter(reader_runs)

    def popen(*args, **kwargs):
        return writer if kwargs.get("stdin") else next(readers)

    return popen


def run_pipeline(monkeypatch, reader_runs, writer=None, attempts=None):
    writer = writer or FakeProcess()
    monkeypatch.setattr(subprocess, "Popen", fake_popen(reader_runs, writer))
    monkeypatch.setattr(pipeline, "CONNECT_DELAY", 0)
    if attempts:
        monkeypatch.setattr(pipeline, "CONNECT_ATTEMPTS", attempts)
    logs = []
    live = pipeline.Pipeline("src", "out", logs.append, W, H, fps=200)
    live.start()
    live._threads[0].join(timeout=5)
    live.stop()
    return live, writer, logs


def test_frames_flow_from_reader_to_writer(monkeypatch):
    _, writer, logs = run_pipeline(monkeypatch, [FakeProcess(bytes(frame()))])
    assert "The camera feed ended." in logs
    size = W * H * 3 // 2
    assert bytes(writer.stdin.written[-size:]) == bytes(frame())


def test_reader_retries_until_the_source_is_ready(monkeypatch):
    not_ready = FakeProcess(error=b"Not a video capture device.\n")
    _, writer, logs = run_pipeline(
        monkeypatch, [not_ready, not_ready, FakeProcess(bytes(frame()))]
    )
    size = W * H * 3 // 2
    assert bytes(writer.stdin.written[-size:]) == bytes(frame())
    assert not any("Could not read" in line for line in logs)


def test_reader_gives_up_and_says_why(monkeypatch):
    never = FakeProcess(error=b"Not a video capture device.\n")
    _, _, logs = run_pipeline(monkeypatch, [never] * 3, attempts=3)
    assert logs == [
        "Could not read the camera feed. Not a video capture device."
    ]
