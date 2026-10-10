"""Tests for reading adb's device list and watching for the phone."""

import subprocess
import time

from phone_webcam import phone

HEADER = "List of devices attached\n"
# The suite replaces check_phone with a stub, so keep the real one to test.
real_check_phone = phone.check_phone


def test_a_ready_phone_is_found():
    found = phone.parse_devices(HEADER + "abc\tdevice\n\n")
    assert found == phone.Phone(phone.READY, "abc")
    assert found.ready


def test_a_phone_awaiting_approval_is_unauthorised():
    found = phone.parse_devices(HEADER + "abc\tunauthorized\n")
    assert found == phone.Phone(phone.UNAUTHORISED, "abc")
    assert not found.ready


def test_an_offline_phone_is_reported():
    assert phone.parse_devices(HEADER + "abc\toffline\n").state == phone.OFFLINE


def test_no_devices_means_missing():
    assert phone.parse_devices(HEADER + "\n") == phone.Phone(phone.MISSING)
    assert phone.parse_devices("") == phone.Phone(phone.MISSING)


def test_a_ready_phone_wins_over_others():
    out = HEADER + "old\tunauthorized\nnew\tdevice\n"
    assert phone.parse_devices(out) == phone.Phone(phone.READY, "new")


def test_check_phone_reports_a_missing_adb(monkeypatch):
    def gone(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", gone)
    assert real_check_phone() == phone.Phone(phone.UNAVAILABLE)


def test_check_phone_reads_adb_output(monkeypatch):
    done = subprocess.CompletedProcess([], 0, HEADER + "abc\tdevice\n", "")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: done)
    assert real_check_phone().ready


def test_every_problem_has_a_message():
    for state in (
        phone.UNAUTHORISED,
        phone.OFFLINE,
        phone.MISSING,
        phone.UNAVAILABLE,
    ):
        assert phone.MESSAGES[state]


def test_monitor_reports_only_changes():
    events = []
    answers = iter(
        [
            phone.Phone(phone.MISSING),
            phone.Phone(phone.MISSING),
            phone.Phone(phone.UNAUTHORISED, "abc"),
            phone.Phone(phone.READY, "abc"),
            phone.Phone(phone.READY, "abc"),
        ]
    )
    monitor = phone.Monitor(events.append, check=lambda: next(answers))
    for _ in range(5):
        monitor.poll()
    assert [e["state"] for e in events] == ["missing", "unauthorised", "ready"]
    assert events[-1] == {"type": "phone", "state": "ready", "serial": "abc"}


def test_monitor_polls_in_the_background_until_stopped():
    events = []
    monitor = phone.Monitor(
        events.append, interval=0.01, check=lambda: phone.Phone(phone.MISSING)
    )
    monitor.start()
    for _ in range(100):
        if events:
            break
        time.sleep(0.01)
    monitor.stop()
    assert len(events) == 1
    assert monitor.current == phone.Phone(phone.MISSING)


# ─────────────────────────────────────────────────────────| Properties |──
GETPROP = """\
[ro.product.manufacturer]: [samsung]
[ro.product.model]: [SM-G975F]
[ro.build.version.release]: [16]
[ro.secure]: [1]
[ro.build.version.sdk]: [36]
not a property line
"""


def test_only_the_properties_of_interest_are_kept():
    assert phone.parse_properties(GETPROP) == {
        "ro.product.manufacturer": "samsung",
        "ro.product.model": "SM-G975F",
        "ro.build.version.release": "16",
        "ro.build.version.sdk": "36",
    }


def test_properties_are_empty_when_adb_cannot_run(monkeypatch):
    def gone(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", gone)
    assert phone.read_properties() == {}
