"""Tests for the start-up flow, covering each fallback level."""

import types

import pytest

from phone_webcam import deps, main


def ok(key: str) -> deps.CheckResult:
    return deps.CheckResult(key, key, True)


def bad(key: str) -> deps.CheckResult:
    return deps.CheckResult(key, key, False, detail="gone")


class FakeEvent:
    def __iadd__(self, handler):
        return self


class FakeWindow:
    def __init__(self):
        self.events = types.SimpleNamespace(closed=FakeEvent())


@pytest.fixture(autouse=True)
def no_popups(monkeypatch):
    monkeypatch.setattr(main, "notify", lambda title, body: None)


@pytest.fixture
def no_window(monkeypatch):
    """Fail the test if the window would have been opened."""

    def _boom(*_):
        raise AssertionError("window must not open")

    monkeypatch.setattr(main, "run_window", _boom)


# ──────────────────────────────────────────────────────| Preflight fallback |──
def test_broken_gui_stack_exits_on_terminal(monkeypatch, capsys, no_window):
    monkeypatch.setattr(
        deps, "run_preflight", lambda: [ok("display"), bad("qt_libs")]
    )
    assert main.main([]) == main.EXIT_PREFLIGHT
    err = capsys.readouterr().err
    assert "GUI stack is incomplete" in err
    assert "[MISSING ] qt_libs - gone" in err


def test_healthy_stack_opens_window(monkeypatch):
    monkeypatch.setattr(deps, "run_preflight", lambda: [ok("display")])
    monkeypatch.setattr(main, "run_window", lambda *_: main.EXIT_OK)
    assert main.main([]) == main.EXIT_OK


def test_system_gates_do_not_block_the_window(monkeypatch):
    """Missing scrcpy is shown inside the window, not on the terminal."""
    monkeypatch.setattr(deps, "run_preflight", lambda: [ok("display")])
    monkeypatch.setattr(deps, "run_system_checks", lambda *_: [bad("scrcpy")])
    monkeypatch.setattr(main, "run_window", lambda *_: main.EXIT_OK)
    assert main.main([]) == main.EXIT_OK


# ──────────────────────────────────────────────────────────────| Check mode |──
def test_check_mode_covers_both_tiers(monkeypatch, capsys, no_window):
    monkeypatch.setattr(deps, "run_preflight", lambda: [ok("display")])
    monkeypatch.setattr(deps, "run_system_checks", lambda *_: [bad("scrcpy")])
    assert main.main(["--check"]) == main.EXIT_CHECK_FAILED
    out = capsys.readouterr().out
    assert "display" in out
    assert "[MISSING ] scrcpy" in out


def test_check_mode_all_good(monkeypatch, no_window):
    monkeypatch.setattr(deps, "run_preflight", lambda: [ok("display")])
    monkeypatch.setattr(deps, "run_system_checks", lambda *_: [ok("scrcpy")])
    assert main.main(["--check"]) == main.EXIT_OK


# ────────────────────────────────────────────────────────────────| Gate API |──
def test_gate_api_report_shape(monkeypatch):
    from phone_webcam.api import Api

    monkeypatch.setattr(deps, "detect_family", lambda: "fedora")
    monkeypatch.setattr(
        deps, "run_system_checks", lambda *_: [ok("scrcpy"), bad("adb")]
    )
    report = Api().get_report()
    assert report["ready"] is False
    assert report["command"] == "sudo dnf install android-tools"
    assert [c["key"] for c in report["checks"]] == ["scrcpy", "adb"]
    assert report["app_name"]


def test_gate_api_ready_when_only_optional_missing(monkeypatch):
    from phone_webcam.api import Api

    optional = deps.CheckResult("v4l2_ctl", "v4l2-ctl", False, required=False)
    monkeypatch.setattr(
        deps, "run_system_checks", lambda *_: [ok("adb"), optional]
    )
    assert Api().get_report()["ready"] is True


# @@Platform fallback@@
def test_window_uses_working_platform_when_preferred_is_broken(monkeypatch):
    """run_window must export QT_QPA_PLATFORM before Qt starts."""
    import sys

    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr(
        deps,
        "pick_qt_platform",
        lambda: deps.QtPlatform("xcb", {"wayland": frozenset({"libx.so"})}),
    )
    fake = types.SimpleNamespace(
        create_window=lambda *a, **k: FakeWindow(),
        start=lambda **k: None,
        errors=types.SimpleNamespace(WebViewException=RuntimeError),
    )
    monkeypatch.setitem(sys.modules, "webview", fake)
    assert main.run_window() == main.EXIT_OK
    assert main.os.environ["QT_QPA_PLATFORM"] == "xcb"
    monkeypatch.delenv("QT_QPA_PLATFORM")


def test_window_leaves_platform_alone_when_preferred_works(monkeypatch):
    import sys

    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr(
        deps, "pick_qt_platform", lambda: deps.QtPlatform("wayland", {})
    )
    fake = types.SimpleNamespace(
        create_window=lambda *a, **k: FakeWindow(),
        start=lambda **k: None,
        errors=types.SimpleNamespace(WebViewException=RuntimeError),
    )
    monkeypatch.setitem(sys.modules, "webview", fake)
    main.run_window()
    assert "QT_QPA_PLATFORM" not in main.os.environ


# @@Simulation flag@@
def test_unknown_simulate_key_is_rejected(capsys):
    with pytest.raises(SystemExit) as exc:
        main.main(["--simulate-missing", "nope"])
    assert exc.value.code == 2
    assert "unknown check key" in capsys.readouterr().err


def test_simulate_flag_reaches_the_window(monkeypatch):
    seen = {}
    monkeypatch.setattr(deps, "run_preflight", lambda: [ok("display")])
    monkeypatch.setattr(
        main, "run_window", lambda simulate=(): seen.update(keys=simulate) or 0
    )
    main.main(["--simulate-missing", "scrcpy,adb"])
    assert seen["keys"] == ("scrcpy", "adb")


def test_simulate_flag_reaches_check_mode(monkeypatch, capsys):
    monkeypatch.setattr(deps, "run_preflight", lambda: [ok("display")])
    monkeypatch.setattr(deps, "_which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(deps, "V4L2LOOPBACK_SYSFS", main.Path("/"))
    code = main.main(["--check", "--simulate-missing", "adb"])
    assert code == main.EXIT_CHECK_FAILED
    assert "adb - simulated as missing" in capsys.readouterr().out


def test_gate_api_passes_simulation_through(monkeypatch):
    from phone_webcam.api import Api

    monkeypatch.setattr(deps, "_which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(deps, "V4L2LOOPBACK_SYSFS", main.Path("/"))
    report = Api(["scrcpy"]).get_report()
    assert report["ready"] is False
    assert report["command"] is None or "scrcpy" in report["command"]


# @@Orientation@@
def test_api_saves_the_orientation(monkeypatch):
    from phone_webcam import config
    from phone_webcam.api import Api

    api = Api()
    api.set_orientation(270, True)
    assert api.get_orientation() == {"rotation": 270, "mirror": True}
    assert config.load_prefs() == {"rotation": 270, "mirror": True}
    assert Api().get_orientation() == {"rotation": 270, "mirror": True}


def test_api_delivers_events_to_the_page_in_order():
    import json
    import time

    from phone_webcam.api import Api

    seen = []
    api = Api()
    api.attach(types.SimpleNamespace(evaluate_js=seen.append))
    for n in range(50):
        api._push({"type": "log", "line": str(n)})
    for _ in range(100):
        if len(seen) == 50:
            break
        time.sleep(0.01)
    lines = [json.loads(js.split("(", 1)[1].rstrip(")"))["line"] for js in seen]
    assert lines == [str(n) for n in range(50)]
