"""Tests for the dependency gates. Nothing here touches the real system."""

import importlib
import importlib.util
import types
from pathlib import Path

import pytest

from phone_webcam import config, deps


# ─────────────────────────────────────────────────────────────────| Helpers |──
def result(key: str, ok: bool, required: bool = True) -> deps.CheckResult:
    return deps.CheckResult(key, key, ok, required)


# ──────────────────────────────────────────────────| Distribution detection |──
@pytest.mark.parametrize(
    ("content", "family"),
    [
        ("ID=fedora\nVERSION_ID=44\n", "fedora"),
        ('ID=debian\nVERSION_ID="13"\n', "debian"),
        ('ID=pop\nID_LIKE="ubuntu debian"\n', "debian"),
        ('ID=nobara\nID_LIKE="rhel centos fedora"\n', "fedora"),
        ("ID=arch\n", None),
    ],
)
def test_detect_family(tmp_path: Path, content: str, family: str | None):
    path = tmp_path / "os-release"
    path.write_text(content)
    assert deps.detect_family(path) == family


def test_detect_family_missing_file(tmp_path: Path):
    assert deps.detect_family(tmp_path / "nope") is None


# ────────────────────────────────────────────────────────| Install commands |──
def test_install_command_merges_and_deduplicates():
    cmd = deps.install_command(["v4l2_ctl", "scrcpy", "v4l2_ctl"], "fedora")
    assert cmd == "sudo dnf install v4l-utils scrcpy"


def test_packages_for_lists_without_duplicates():
    keys = ["adb", "v4l2_ctl", "adb"]
    assert deps.packages_for(keys, "debian") == ["adb", "v4l-utils"]


def test_scrcpy_has_no_debian_package_but_has_a_fedora_one():
    assert deps.packages_for(["scrcpy"], "debian") == []
    assert deps.install_command(["scrcpy"], "debian") is None
    assert deps.packages_for(["scrcpy"], "fedora") == ["scrcpy"]


@pytest.mark.parametrize("family", [None, "arch"])
def test_packages_for_unknown_family_is_empty(family):
    assert deps.packages_for(["scrcpy"], family) == []


def test_install_command_uses_family_package_names():
    assert deps.install_command(["adb"], "fedora").endswith("android-tools")
    assert deps.install_command(["adb"], "debian") == "sudo apt install adb"


@pytest.mark.parametrize(
    ("keys", "family"),
    [
        (["adb"], None),
        (["adb"], "arch"),
        ([], "fedora"),
        (["display"], "fedora"),
    ],
)
def test_install_command_none_when_nothing_to_suggest(keys, family):
    assert deps.install_command(keys, family) is None


# ────────────────────────────────────────────────────────────────| Blocking |──
def test_blocking_ignores_ok_and_optional():
    results = [result("a", True), result("b", False, required=False)]
    assert deps.blocking(results) == []
    assert deps.blocking(results + [result("c", False)]) == [result("c", False)]


# ────────────────────────────────────────────────────────────| Display gate |──
def test_display_missing():
    assert not deps.check_display({}).ok


@pytest.mark.parametrize("env", [{"DISPLAY": ":0"}, {"WAYLAND_DISPLAY": "w-0"}])
def test_display_present(env):
    assert deps.check_display(env).ok


def test_display_headless_qt_counts():
    assert deps.check_display({"QT_QPA_PLATFORM": "offscreen"}).ok


# ─────────────────────────────────────────────────────────| Qt library gate |──
SESSION = {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}


@pytest.fixture
def qt_tree(tmp_path: Path, monkeypatch):
    """A fake PyQt6 tree with both platform plugins present."""
    plugins = tmp_path / "plugins" / "platforms"
    plugins.mkdir(parents=True)
    for name in ("libqxcb.so", "libqwayland.so"):
        (plugins / name).touch()
    monkeypatch.setattr(deps, "_qt_root", lambda: tmp_path)
    return tmp_path


def fake_ldd(missing_by_name: dict[str, set[str]]):
    return lambda path: missing_by_name.get(path.name, set())


def test_qt_libs_ok(qt_tree, monkeypatch):
    monkeypatch.setattr(deps, "_ldd_missing", fake_ldd({}))
    res = deps.check_qt_libs(SESSION)
    assert res.ok
    assert res.detail == ""


def test_qt_libs_reports_missing_core_libs(qt_tree, monkeypatch):
    monkeypatch.setattr(
        deps, "_ldd_missing", fake_ldd({"libQt6Gui.so.6": {"libGL.so.1"}})
    )
    res = deps.check_qt_libs(SESSION)
    assert not res.ok
    assert "libGL.so.1" in res.detail


def test_qt_platform_prefers_wayland_when_it_works(qt_tree, monkeypatch):
    monkeypatch.setattr(deps, "_ldd_missing", fake_ldd({}))
    platform = deps.pick_qt_platform(SESSION)
    assert platform.name == "wayland"
    assert not platform.fell_back


def test_qt_platform_falls_back_to_xcb_when_wayland_is_broken(
    qt_tree, monkeypatch
):
    """The case seen on a Wayland session missing libwayland-cursor."""
    monkeypatch.setattr(
        deps,
        "_ldd_missing",
        fake_ldd({"libqwayland.so": {"libwayland-cursor.so.0"}}),
    )
    platform = deps.pick_qt_platform(SESSION)
    assert platform.name == "xcb"
    assert platform.fell_back
    res = deps.check_qt_libs(SESSION)
    assert res.ok
    assert "using xcb" in res.detail
    assert "libwayland-cursor.so.0" in res.detail


def test_qt_platform_wayland_only_session_broken_fails(qt_tree, monkeypatch):
    monkeypatch.setattr(
        deps,
        "_ldd_missing",
        fake_ldd({"libqwayland.so": {"libwayland-cursor.so.0"}}),
    )
    res = deps.check_qt_libs({"WAYLAND_DISPLAY": "wayland-0"})
    assert not res.ok
    assert "libwayland-cursor.so.0" in res.detail


def test_qt_platform_all_plugins_broken_reports_both(qt_tree, monkeypatch):
    monkeypatch.setattr(
        deps,
        "_ldd_missing",
        fake_ldd(
            {
                "libqxcb.so": {"libxcb-cursor.so.0"},
                "libqwayland.so": {"libwayland-cursor.so.0"},
            }
        ),
    )
    res = deps.check_qt_libs(SESSION)
    assert not res.ok
    assert "libxcb-cursor.so.0" in res.detail
    assert "libwayland-cursor.so.0" in res.detail


def test_qt_platform_missing_plugin_file_counts_as_broken(qt_tree, monkeypatch):
    (qt_tree / "plugins" / "platforms" / "libqwayland.so").unlink()
    monkeypatch.setattr(deps, "_ldd_missing", fake_ldd({}))
    platform = deps.pick_qt_platform(SESSION)
    assert platform.name == "xcb"
    assert "wayland" in platform.broken


def test_qt_platform_respects_user_override(qt_tree, monkeypatch):
    monkeypatch.setattr(
        deps, "_ldd_missing", fake_ldd({"libqxcb.so": {"libxcb-cursor.so.0"}})
    )
    env = {**SESSION, "QT_QPA_PLATFORM": "xcb"}
    assert deps.pick_qt_platform(env).name is None
    assert deps.check_qt_libs(env).ok


def test_qt_libs_headless_skips_platform_plugins(qt_tree, monkeypatch):
    monkeypatch.setattr(
        deps, "_ldd_missing", fake_ldd({"libqxcb.so": {"libxcb-cursor.so.0"}})
    )
    assert deps.check_qt_libs({"QT_QPA_PLATFORM": "offscreen"}).ok


def test_qt_libs_without_ldd_is_not_a_blocker(qt_tree, monkeypatch):
    monkeypatch.setattr(deps, "_ldd_missing", lambda path: None)
    assert deps.check_qt_libs({}).ok


def test_qt_libs_without_pyqt_defers_to_import_check(monkeypatch):
    monkeypatch.setattr(deps, "_qt_root", lambda: None)
    assert deps.check_qt_libs({}).ok


# ────────────────────────────────────────────────────────────| Import gates |──
def fake_import(monkeypatch, failing: str, exc: ImportError):
    """Make deps.py fail one import and succeed at every other.

    Nothing real is imported, so the result does not depend on which
    packages the test environment has. Only the name deps.py sees is
    replaced, so the real importlib stays intact for everything else.
    """

    def _import(name, *args):
        if name == failing:
            raise exc
        return types.ModuleType(name)

    stub = types.SimpleNamespace(import_module=_import, util=importlib.util)
    monkeypatch.setattr(deps, "importlib", stub)


def test_qt_import_missing_module_suggests_sync(monkeypatch):
    exc = ModuleNotFoundError("No module named 'qtpy'")
    fake_import(monkeypatch, "qtpy", exc)
    res = deps.check_qt_import()
    assert not res.ok
    assert "uv sync" in res.detail


def test_qt_import_system_library_does_not_suggest_sync(monkeypatch):
    exc = ImportError("libGL.so.1: cannot open shared object file")
    fake_import(monkeypatch, "PyQt6.QtWebEngineWidgets", exc)
    res = deps.check_qt_import()
    assert not res.ok
    assert "uv sync" not in res.detail
    assert "libGL.so.1" in res.detail


def test_webview_import_missing(monkeypatch):
    exc = ModuleNotFoundError("No module named 'webview'")
    fake_import(monkeypatch, "webview", exc)
    assert not deps.check_webview_import().ok


# ────────────────────────────────────────────────────────────| System gates |──
def test_binary_found(monkeypatch):
    monkeypatch.setattr(deps, "_which", lambda name: f"/usr/bin/{name}")
    assert deps.check_binary("adb", "adb", "adb").ok


def test_binary_missing_required_blocks(monkeypatch):
    monkeypatch.setattr(deps, "_which", lambda name: None)
    assert deps.check_binary("adb", "adb", "adb").blocking


def test_binary_missing_optional_does_not_block(monkeypatch):
    monkeypatch.setattr(deps, "_which", lambda name: None)
    assert not deps.check_binary("x", "x", "x", required=False).blocking


def test_which_falls_back_to_sbin(monkeypatch):
    calls = []

    def fake(name, path=None):
        calls.append(path)
        return "/usr/sbin/modprobe" if path == deps.SBIN_PATH else None

    monkeypatch.setattr(deps.shutil, "which", fake)
    assert deps._which("modprobe") == "/usr/sbin/modprobe"
    assert calls == [None, deps.SBIN_PATH]


def test_v4l2loopback_loaded(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(deps, "V4L2LOOPBACK_SYSFS", tmp_path)
    res = deps.check_v4l2loopback()
    assert res.ok
    assert res.detail == "loaded"


def test_v4l2loopback_installed_via_modinfo(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(deps, "V4L2LOOPBACK_SYSFS", tmp_path / "absent")
    monkeypatch.setattr(deps, "_which", lambda name: "/usr/sbin/modinfo")

    class Proc:
        returncode = 0

    monkeypatch.setattr(deps.subprocess, "run", lambda *a, **k: Proc())
    assert deps.check_v4l2loopback().detail == "installed"


def test_v4l2loopback_absent_via_modinfo(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(deps, "V4L2LOOPBACK_SYSFS", tmp_path / "absent")
    monkeypatch.setattr(deps, "_which", lambda name: "/usr/sbin/modinfo")

    class Proc:
        returncode = 1

    monkeypatch.setattr(deps.subprocess, "run", lambda *a, **k: Proc())
    assert not deps.check_v4l2loopback().ok


def test_v4l2loopback_found_by_scanning_modules(tmp_path: Path, monkeypatch):
    release = deps.os.uname().release
    module = tmp_path / release / "extra" / "v4l2loopback.ko.xz"
    module.parent.mkdir(parents=True)
    module.touch()
    monkeypatch.setattr(deps, "V4L2LOOPBACK_SYSFS", tmp_path / "absent")
    monkeypatch.setattr(deps, "_which", lambda name: None)
    monkeypatch.setattr(deps, "MODULES_DIRS", (tmp_path,))
    assert deps.check_v4l2loopback().ok


def test_v4l2loopback_not_found_anywhere(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(deps, "V4L2LOOPBACK_SYSFS", tmp_path / "absent")
    monkeypatch.setattr(deps, "_which", lambda name: None)
    monkeypatch.setattr(deps, "MODULES_DIRS", (tmp_path,))
    assert not deps.check_v4l2loopback().ok


# ──────────────────────────────────────────────────────────────────| Report |──
def test_report_marks_states_and_adds_one_install_line():
    results = [
        result("scrcpy", True),
        result("adb", False),
        result("v4l2_ctl", False, required=False),
    ]
    text = deps.format_report(results, "fedora")
    assert "[   ok   ] scrcpy" in text
    assert "[MISSING ] adb" in text
    assert "[optional] v4l2_ctl" in text
    assert "sudo dnf install android-tools v4l-utils" in text


def test_report_without_known_distro_has_no_install_line():
    assert "sudo" not in deps.format_report([result("adb", False)], None)


# ──────────────────────────────────────────────────────────────────| Config |──
def test_app_name_from_file(tmp_path: Path):
    path = tmp_path / "settings.ini"
    path.write_text("[branding]\nAPP_NAME = Cam Thing\n")
    assert config.app_name(path) == "Cam Thing"


@pytest.mark.parametrize("content", [None, "", "[branding]\n", "[x]\nA=1\n"])
def test_app_name_falls_back(tmp_path: Path, content: str | None):
    path = tmp_path / "settings.ini"
    if content is not None:
        path.write_text(content)
    assert config.app_name(path) == config.DEFAULT_APP_NAME


# @@Simulation@@
def test_simulate_missing_flips_only_the_named_checks():
    results = [result("scrcpy", True), result("adb", True)]
    out = deps.simulate_missing(results, ["adb"])
    assert [r.ok for r in out] == [True, False]
    assert out[1].detail == "simulated as missing"


def test_simulated_required_check_blocks():
    out = deps.simulate_missing([result("scrcpy", True)], ["scrcpy"])
    assert deps.blocking(out)


def test_run_system_checks_applies_simulation(monkeypatch):
    monkeypatch.setattr(deps, "_which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(deps, "V4L2LOOPBACK_SYSFS", Path("/"))
    results = deps.run_system_checks(["scrcpy"])
    assert not next(r for r in results if r.key == "scrcpy").ok
    assert next(r for r in results if r.key == "adb").ok
