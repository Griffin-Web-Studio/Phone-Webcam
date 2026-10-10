"""Tests for turning frames and for the pipeline's process handling."""

import subprocess
import time
import types

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
    live = pipeline.Pipeline("src", "out", print, width=W, height=H)
    for rotation in pipeline.ROTATIONS:
        for mirror in (False, True):
            live.set_orientation(rotation, mirror)
            luma, cb, cr = live._turned(frame())
            assert luma.shape == (H, W)
            assert cb.shape == cr.shape == (H // 2, W // 2)


def test_bad_rotation_is_rejected():
    live = pipeline.Pipeline("src", "out", print, width=W, height=H)
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

    def close(self):
        pass

    def readline(self):
        data, self.data = self.data.tobytes(), memoryview(b"")
        return data


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


def fake_popen(reader, writer):
    """Hand out the writer for stdin pipes and the reader otherwise."""

    def popen(*args, **kwargs):
        return writer if kwargs.get("stdin") else reader

    return popen


def run_pipeline(monkeypatch, reader, writer=None, on_first_frame=None):
    writer = writer or FakeProcess()
    monkeypatch.setattr(subprocess, "Popen", fake_popen(reader, writer))
    logs = []
    live = pipeline.Pipeline(
        "src", "out", logs.append, on_first_frame, W, H, fps=200
    )
    live.start()
    live._reader_threads[0].join(timeout=5)
    for _ in range(200):
        if len(writer.stdin.written) >= W * H * 3 // 2 * 2:
            break
        time.sleep(0.005)
    live.stop()
    return live, writer, logs


def test_frames_flow_from_reader_to_writer(monkeypatch):
    _, writer, logs = run_pipeline(monkeypatch, FakeProcess(bytes(frame())))
    size = W * H * 3 // 2
    assert bytes(writer.stdin.written[-size:]) == bytes(frame())
    assert "The camera feed ended." in logs


def test_first_frame_is_reported_once(monkeypatch):
    calls = []
    data = bytes(frame()) * 3
    run_pipeline(
        monkeypatch, FakeProcess(data), on_first_frame=lambda: calls.append(1)
    )
    assert calls == [1]


def test_feed_end_includes_the_decoder_error(monkeypatch):
    reader = FakeProcess(error=b"Invalid data found\n")
    live = pipeline.Pipeline("src", "out", print, width=W, height=H)
    live._last_error = "Invalid data found"
    logs = []
    live._log = logs.append
    live._read_loop(reader)
    assert logs == ["The camera feed ended. Invalid data found"]


def test_a_quiet_pipeline_does_not_report_the_feed_ending(monkeypatch):
    _, _, logs = run_pipeline(monkeypatch, FakeProcess(b""))
    quiet = pipeline.Pipeline("src", "out", logs.append, width=W, height=H)
    logs.clear()
    quiet.quiet()
    quiet._read_loop(FakeProcess(b""))
    assert logs == []


def test_preview_gets_every_other_turned_frame(monkeypatch):
    offered = []
    writer = FakeProcess()
    monkeypatch.setattr(
        subprocess, "Popen", fake_popen(FakeProcess(bytes(frame())), writer)
    )
    live = pipeline.Pipeline("src", "out", print, width=W, height=H, fps=500)
    live.set_preview(types.SimpleNamespace(offer=offered.append))
    live.start()
    live._reader_threads[0].join(timeout=5)
    time.sleep(0.1)
    live.stop()
    assert offered
    assert offered[0][0].shape == (H, W)


def test_restarting_the_reader_keeps_the_writer_and_stays_quiet(monkeypatch):
    writer = FakeProcess()
    readers = iter([FakeProcess(b""), FakeProcess(bytes(frame()))])
    spawned = []

    def popen(*args, **kwargs):
        if kwargs.get("stdin"):
            return writer
        spawned.append(1)
        return next(readers)

    monkeypatch.setattr(subprocess, "Popen", popen)
    logs = []
    live = pipeline.Pipeline(
        "src", "out", logs.append, width=W, height=H, fps=200
    )
    live.start()
    live.restart_reader()
    live._reader_threads[0].join(timeout=5)
    live.stop()
    assert len(spawned) == 2
    assert live._writer is writer
    assert logs == ["The camera feed ended."]


def test_fit_filter_pads_instead_of_stretching():
    live = pipeline.Pipeline("src", "out", print, width=W, height=H)
    assert live._fit_filter() == (
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2"
    )


def test_preview_gets_frames_at_its_own_rate():
    live = pipeline.Pipeline("src", "out", print, width=W, height=H, fps=60)
    live.set_preview(types.SimpleNamespace(offer=print), 30)
    assert live._preview_every == 2
    live.set_preview(types.SimpleNamespace(offer=print), 60)
    assert live._preview_every == 1
    live.set_preview(None)
    assert live._preview is None
