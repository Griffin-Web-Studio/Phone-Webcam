"""Tests for the webcam helpers and the start/stop state machine."""

import subprocess
import threading

from phone_webcam import webcam


# ─────────────────────────────────────────────────────────────| Pure helpers |──
def test_parse_adb_devices_splits_ready_and_unauthorised():
    out = "List of devices attached\nabc\tdevice\ndef\tunauthorized\nghi\toffline\n\n"
    assert webcam.parse_adb_devices(out) == (["abc"], ["def"])


def test_parse_adb_devices_empty_list():
    assert webcam.parse_adb_devices("List of devices attached\n\n") == ([], [])


def test_find_device_matches_card_label(tmp_path):
    for node, name in (
        ("video0", "Integrated Camera"),
        ("video2", "Android Webcam"),
    ):
        (tmp_path / node).mkdir()
        (tmp_path / node / "name").write_text(name + "\n")
    assert webcam.find_device(sysfs=tmp_path) == "/dev/video2"


def test_find_device_none_when_label_differs(tmp_path):
    (tmp_path / "video0").mkdir()
    (tmp_path / "video0" / "name").write_text("Iriun Webcam\n")
    assert webcam.find_device(sysfs=tmp_path) is None


# ───────────────────────────────────────────────────────────────| Controller |──
def make(monkeypatch, *, prepared="/dev/video0", lines=(), code=0):
    events: list[dict] = []
    cam = webcam.Webcam(events.append)
    monkeypatch.setattr(cam, "_prepare", lambda: prepared)

    class FakeProcess:
        stdout = iter(lines)

        def terminate(self):
            pass

        def wait(self):
            return code

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: FakeProcess())
    return cam, events


def run_to_end(cam):
    cam.start()
    for thread in threading.enumerate():
        if thread is not threading.current_thread():
            thread.join(timeout=5)


def states(events):
    return [e["state"] for e in events if e["type"] == "state"]


def logs(events):
    return [e["line"] for e in events if e["type"] == "log"]


def test_successful_run_reports_running_then_stopped(monkeypatch):
    cam, events = make(monkeypatch, lines=["v4l2 sink started\n"])
    run_to_end(cam)
    assert states(events) == ["starting", "running", "stopped"]


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
