"""Tests for the webcam helpers and the start/stop state machine."""

import subprocess
import threading
import types

import pytest

from phone_webcam import webcam


# ─────────────────────────────────────────────────────────────| Pure helpers |──
def test_parse_adb_devices_splits_ready_and_unauthorised():
    out = "List of devices attached\nabc\tdevice\ndef\tunauthorized\nghi\toffline\n\n"
    assert webcam.parse_adb_devices(out) == (["abc"], ["def"])


def test_parse_adb_devices_empty_list():
    assert webcam.parse_adb_devices("List of devices attached\n\n") == ([], [])


# ───────────────────────────────────────────────────────────────| Controller |──
def make(monkeypatch, *, prepared="/dev/video0", lines=(), code=0):
    events: list[dict] = []
    cam = webcam.Webcam(events.append)
    monkeypatch.setattr(cam, "_prepare", lambda: prepared)

    class FakeProcess:
        def terminate(self):
            pass

        def poll(self):
            return code

        def wait(self):
            return code

    monkeypatch.setattr(
        cam, "_spawn", lambda args: (FakeProcess(), iter(lines))
    )
    monkeypatch.setattr(cam, "_start_pipeline", lambda *a: True)
    return cam, events


def run_to_end(cam):
    cam.start()
    for thread in threading.enumerate():
        if thread.name == "webcam-worker":
            thread.join(timeout=5)


def states(events):
    return [e["state"] for e in events if e["type"] == "state"]


def logs(events):
    return [e["line"] for e in events if e["type"] == "log"]


def test_run_ends_stopped_and_running_waits_for_the_first_frame(monkeypatch):
    cam, events = make(monkeypatch)
    run_to_end(cam)
    assert states(events) == ["starting", "stopped"]
    cam.state = webcam.STARTING
    cam._on_first_frame()
    assert states(events)[-1] == "running"


def test_prepare_failure_goes_straight_back_to_stopped(monkeypatch):
    cam, events = make(monkeypatch, prepared=None)
    run_to_end(cam)
    assert states(events) == ["starting", "stopped"]


def test_nonzero_exit_is_logged(monkeypatch):
    cam, events = make(monkeypatch, code=1)
    run_to_end(cam)
    assert "scrcpy exited with code 1" in logs(events)


def test_user_stop_with_sigterm_is_not_an_error(monkeypatch):
    cam, events = make(monkeypatch, code=webcam.SIGTERM_EXIT)
    cam._stop_requested = True
    cam.state = webcam.STARTING
    cam._stream("/dev/video0")
    assert not any("exited" in line for line in logs(events))


def test_sigterm_without_a_stop_request_is_an_error(monkeypatch):
    cam, events = make(monkeypatch, code=webcam.SIGTERM_EXIT)
    cam._stream("/dev/video0")
    assert "scrcpy exited with code -15" in logs(events)


def test_start_is_ignored_while_a_run_is_under_way(monkeypatch):
    cam, events = make(monkeypatch)
    cam.state = webcam.RUNNING
    cam.start()
    assert events == []


# ─────────────────────────────────────────────────────────────| Orientation |──
def test_orientation_is_applied_to_the_live_pipeline(monkeypatch):
    cam, events = make(monkeypatch)
    turns = []
    cam._pipeline = types.SimpleNamespace(
        set_orientation=lambda r, m: turns.append((r, m))
    )
    cam.set_orientation(90, True)
    assert turns == [(90, True)]
    assert cam.orientation() == {"rotation": 90, "mirror": True}
    assert events[-1] == {"type": "orientation", "rotation": 90, "mirror": True}


def test_orientation_rejects_odd_angles(monkeypatch):
    cam, _ = make(monkeypatch)
    with pytest.raises(ValueError):
        cam.set_orientation(45, False)


def test_pipeline_starts_before_scrcpy_and_gets_the_fifo(monkeypatch):
    cam, events = make(monkeypatch)
    order = []
    monkeypatch.setattr(
        cam,
        "_start_pipeline",
        lambda f, o: order.append(("pipeline", f, o)) or True,
    )
    monkeypatch.setattr(
        cam,
        "_spawn",
        lambda args: order.append(("scrcpy", args))
        or (
            types.SimpleNamespace(
                poll=lambda: 0, wait=lambda: 0, terminate=lambda: None
            ),
            iter([]),
        ),
    )
    run_to_end(cam)
    assert [step[0] for step in order] == ["pipeline", "scrcpy"]
    fifo = order[0][1]
    assert f"--record={fifo}" in order[1][1]
    assert order[0][2] == "/dev/video0"


def test_the_fifo_is_removed_after_a_run(monkeypatch):
    cam, _ = make(monkeypatch)
    seen = []
    monkeypatch.setattr(
        cam, "_start_pipeline", lambda f, o: seen.append(f) or True
    )
    run_to_end(cam)
    import os

    assert seen and not os.path.exists(seen[0])


def test_scrcpy_args_record_to_the_fifo_with_frequent_keyframes():
    args = webcam.scrcpy_args("/run/x/camera.mkv")
    assert "--record=/run/x/camera.mkv" in args
    assert "--record-format=mkv" in args
    assert any(
        a.startswith("--video-codec-options=i-frame-interval=1") for a in args
    )
    assert not any(a.startswith("--v4l2-sink") for a in args)


def test_preview_needs_a_running_webcam(monkeypatch):
    cam, events = make(monkeypatch)
    cam._toggle_preview()
    assert "Start the webcam first" in logs(events)[-1]


class FakePreview:
    def __init__(self, ready=True):
        self.ready = ready
        self.stopped = False

    def start(self):
        return "http://127.0.0.1:1/secret.mjpg"

    def wait_for_first_frame(self, timeout):
        return self.ready

    def stop(self):
        self.stopped = True


def running(monkeypatch, preview):
    cam, events = make(monkeypatch)
    pipeline_calls = []
    cam._pipeline = types.SimpleNamespace(set_preview=pipeline_calls.append)
    cam.state = webcam.RUNNING
    monkeypatch.setattr(webcam, "Preview", lambda *a: preview)
    return cam, events, pipeline_calls


def preview_states(events):
    return [e["state"] for e in events if e["type"] == "preview"]


def test_preview_goes_starting_then_open_with_the_address(monkeypatch):
    preview = FakePreview()
    cam, events, calls = running(monkeypatch, preview)
    cam._toggle_preview()
    assert preview_states(events) == ["starting", "open"]
    assert events[-1]["url"] == "http://127.0.0.1:1/secret.mjpg"
    assert calls == [preview]


def test_preview_goes_stopping_then_closed(monkeypatch):
    preview = FakePreview()
    cam, events, calls = running(monkeypatch, preview)
    cam._toggle_preview()
    events.clear()
    cam._toggle_preview()
    assert preview_states(events) == ["stopping", "closed"]
    assert preview.stopped
    assert calls[-1] is None


def test_preview_that_never_shows_a_picture_is_closed(monkeypatch):
    preview = FakePreview(ready=False)
    cam, events, _ = running(monkeypatch, preview)
    cam._toggle_preview()
    assert preview_states(events) == ["starting", "closed"]
    assert preview.stopped
    assert "did not produce a picture" in logs(events)[-1]


def test_preview_toggles_are_ignored_while_one_is_changing(monkeypatch):
    cam, events, _ = running(monkeypatch, FakePreview())
    cam._preview_busy = True
    cam.toggle_preview()
    assert events == []


# ───────────────────────────────────────────────────────────────| Confirming |──
def test_confirm_returns_the_answer(monkeypatch):
    cam, events = make(monkeypatch)
    threading.Timer(0.05, cam.answer, args=(True,)).start()
    assert cam._confirm("Reload?") is True
    assert events[0] == {"type": "confirm", "message": "Reload?"}


def test_stop_declines_a_pending_confirmation(monkeypatch):
    cam, _ = make(monkeypatch)
    cam.state = webcam.STARTING
    threading.Timer(0.05, cam.stop).start()
    assert cam._confirm("Reload?") is False


# ──────────────────────────────────────────────────────────────────| Output |──
def test_spawn_gives_lines_without_waiting_for_the_process_to_exit():
    """A child on a pty is line buffered, so output arrives while it runs."""
    import sys

    script = "import time; print('first', flush=False); time.sleep(5)"
    process, lines = webcam.Webcam._spawn([sys.executable, "-c", script])
    try:
        assert next(lines) == "first"
    finally:
        process.kill()
        process.wait()


def test_clean_line_strips_terminal_codes():
    raw = "\x1b[22;2t\x1b]0;scrcpy - HMD Skyline\x07INFO: Video decoding\x1b[K"
    assert webcam.clean_line(raw) == "INFO: Video decoding"


def test_clean_line_keeps_the_last_progress_update():
    assert webcam.clean_line("[  8%] push\r[100%] push done\x1b[K") == (
        "[100%] push done"
    )


def test_clean_line_of_only_codes_is_empty():
    assert webcam.clean_line("\x1b[K\r") == ""
