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
        main,
        "run_window",
        lambda simulate=(), debug=False: seen.update(keys=simulate) or 0,
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
        if sum('"log"' in js for js in seen) == 50:
            break
        time.sleep(0.01)
    events = [json.loads(js.split("(", 1)[1].rstrip(")")) for js in seen]
    lines = [e["line"] for e in events if e["type"] == "log"]
    assert lines == [str(n) for n in range(50)]


def test_api_reports_the_phone_to_the_page(monkeypatch):
    import json
    import time

    from phone_webcam import phone
    from phone_webcam.api import Api

    monkeypatch.setattr(
        phone,
        "check_phone",
        lambda *a, **k: phone.Phone(phone.UNAUTHORISED, "x"),
    )
    seen = []
    api = Api()
    assert api.get_phone() == "unauthorised"
    api.attach(types.SimpleNamespace(evaluate_js=seen.append))
    for _ in range(100):
        if seen:
            break
        time.sleep(0.01)
    api.shutdown()
    assert seen
    event = json.loads(seen[0].split("(", 1)[1].rstrip(")"))
    assert event == {"type": "phone", "state": "unauthorised", "serial": "x"}


def test_api_saves_settings_without_losing_the_orientation():
    from phone_webcam import config
    from phone_webcam.api import Api

    api = Api()
    api.set_orientation(90, False)
    api.set_settings({"fps": 60, "bitrate": 16})
    saved = config.load_prefs()
    assert saved["rotation"] == 90
    assert saved["settings"]["fps"] == 60
    assert Api().get_settings()["bitrate"] == 16


def test_entering_the_app_resizes_the_window():
    from phone_webcam import api as api_module

    sizes = []
    api = api_module.Api()
    api.attach(
        types.SimpleNamespace(
            resize=lambda w, h: sizes.append((w, h)),
            evaluate_js=lambda js: None,
        )
    )
    api.enter_app()
    api.shutdown()
    assert sizes == [api_module.APP_SIZE]


def test_entering_the_app_without_a_window_is_harmless():
    from phone_webcam.api import Api

    Api().enter_app()


def test_the_side_panel_width_is_saved_and_reset():
    from phone_webcam.api import Api

    api = Api()
    assert api.get_side_width() == 0
    api.set_side_width(412)
    assert Api().get_side_width() == 412
    api.set_side_width(0)
    assert api.get_side_width() == 0


def test_a_bad_saved_width_is_ignored():
    from phone_webcam import config
    from phone_webcam.api import Api

    config.update_prefs({"side_width": "wide"})
    assert Api().get_side_width() == 0


def test_saving_the_width_keeps_the_other_choices():
    from phone_webcam import config
    from phone_webcam.api import Api

    api = Api()
    api.set_orientation(90, True)
    api.set_side_width(300)
    saved = config.load_prefs()
    assert saved["rotation"] == 90 and saved["side_width"] == 300


def test_api_passes_the_preview_wish_to_the_webcam(monkeypatch):
    from phone_webcam.api import Api

    api = Api()
    seen = []
    monkeypatch.setattr(api._webcam, "set_preview_wanted", seen.append)
    api.show_preview(True)
    api.show_preview(False)
    assert seen == [True, False]


# ───────────────────────────────────────────────────────────────────| Cover |──
def test_the_cover_is_saved_with_the_other_choices():
    from phone_webcam import config
    from phone_webcam.api import Api

    api = Api()
    api.set_orientation(90, False)
    api.set_cover({"title": "Lunch", "mirror": False})
    saved = config.load_prefs()
    assert saved["rotation"] == 90
    assert (
        saved["cover"]["title"] == "Lunch" and saved["cover"]["mirror"] is False
    )
    assert Api().get_cover()["title"] == "Lunch"


def test_the_shutter_is_not_remembered_between_launches():
    from phone_webcam.api import Api

    api = Api()
    api.set_shutter(True)
    assert api.get_shutter() is True
    assert Api().get_shutter() is False


def fake_window(monkeypatch, answer):
    import types as t

    import webview

    dialogs = []

    def create_file_dialog(kind, **kwargs):
        dialogs.append((kind, kwargs))
        return answer

    window = t.SimpleNamespace(
        create_file_dialog=create_file_dialog, evaluate_js=lambda js: None
    )
    return window, dialogs, webview


def test_choosing_a_good_svg_uses_it(monkeypatch, tmp_path):
    from phone_webcam import slate
    from phone_webcam.api import Api

    svg = tmp_path / "mine.svg"
    svg.write_text("<svg/>")
    monkeypatch.setattr(slate, "check_svg", lambda path: "")
    api = Api()
    window, dialogs, webview = fake_window(monkeypatch, [str(svg)])
    api.attach(window)
    result = api.choose_cover_svg()
    api.shutdown()
    assert result["ok"] is True and result["cover"]["svg"] == str(svg)
    assert dialogs[0][0] == webview.FileDialog.OPEN
    assert api.get_cover()["svg"] == str(svg)


def test_choosing_a_bad_svg_keeps_the_old_one_and_says_why(
    monkeypatch, tmp_path
):
    from phone_webcam import slate
    from phone_webcam.api import Api

    monkeypatch.setattr(
        slate, "check_svg", lambda path: "ffmpeg could not draw it"
    )
    api = Api()
    window, _, _ = fake_window(monkeypatch, [str(tmp_path / "bad.svg")])
    api.attach(window)
    result = api.choose_cover_svg()
    api.shutdown()
    assert result == {"ok": False, "message": "ffmpeg could not draw it"}
    assert api.get_cover()["svg"] == ""


def test_cancelling_the_dialog_changes_nothing(monkeypatch):
    from phone_webcam.api import Api

    api = Api()
    window, _, _ = fake_window(monkeypatch, None)
    api.attach(window)
    assert api.choose_cover_svg() == {"ok": False, "message": ""}
    api.shutdown()


def test_choosing_without_a_window_does_nothing():
    from phone_webcam.api import Api

    assert Api().choose_cover_svg() == {"ok": False, "message": ""}


def test_debug_flag_reaches_the_window(monkeypatch):
    seen = {}
    monkeypatch.setattr(deps, "run_preflight", lambda: [ok("display")])
    monkeypatch.setattr(
        main,
        "run_window",
        lambda simulate=(), debug=False: seen.update(debug=debug) or 0,
    )
    main.main(["--debug"])
    assert seen["debug"] is True
    main.main([])
    assert seen["debug"] is False
