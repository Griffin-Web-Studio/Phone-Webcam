"""Dependency gates for the app.

Standard library only, so the gates can run before anything heavy is
imported. They run in two tiers:

* preflight - can the GUI stack run at all? A failure here can only be
  reported on the terminal, because no window can be shown.
* system - are the phone and webcam tools installed? Reported inside the
  window, because by then the GUI works.
"""

import importlib
import importlib.util
import os
import shutil
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

# ───────────────────────────────────────────────────────────────| Constants |──
OS_RELEASE = Path("/etc/os-release")
MODULES_DIRS = (Path("/usr/lib/modules"), Path("/lib/modules"))
V4L2LOOPBACK_SYSFS = Path("/sys/module/v4l2loopback")
SBIN_PATH = "/usr/sbin:/sbin"

# Qt platform plugins and libraries that must resolve for a window to open.
HEADLESS_PLATFORMS = frozenset({"offscreen", "minimal"})
QT_CORE_LIBS = ("libQt6Gui.so.6", "libQt6WebEngineCore.so.6")
# Platforms in the order Qt prefers them, with the plugin file pattern and the
# environment variable that shows the session offers that display server.
QT_PLATFORMS = (
    ("wayland", "libqwayland*.so", "WAYLAND_DISPLAY"),
    ("xcb", "libqxcb.so", "DISPLAY"),
)

FAMILIES = {
    "fedora": "fedora",
    "rhel": "fedora",
    "centos": "fedora",
    "debian": "debian",
    "ubuntu": "debian",
}
INSTALL_PREFIX = {
    "fedora": "sudo dnf install",
    "debian": "sudo apt install",
}

# Package names per check key and distribution family.
PACKAGES: dict[str, dict[str, tuple[str, ...]]] = {
    # Debian has no scrcpy package, it comes from the official release.
    "scrcpy": {"fedora": ("scrcpy",), "debian": ()},
    "adb": {"fedora": ("android-tools",), "debian": ("adb",)},
    "v4l2_ctl": {"fedora": ("v4l-utils",), "debian": ("v4l-utils",)},
    "ffmpeg": {"fedora": ("ffmpeg-free",), "debian": ("ffmpeg",)},
    "v4l2loopback_ctl": {
        "fedora": ("v4l2loopback",),
        "debian": ("v4l2loopback-utils",),
    },
    "pkexec": {"fedora": ("polkit",), "debian": ("pkexec",)},
    "modprobe": {"fedora": ("kmod",), "debian": ("kmod",)},
    "v4l2loopback": {
        "fedora": ("v4l2loopback",),
        "debian": ("v4l2loopback-dkms",),
    },
    "qt_libs": {
        "fedora": (
            "mesa-libGL",
            "mesa-libEGL",
            "mesa-libgbm",
            "libxkbcommon",
            "libxkbfile",
            "dbus-libs",
            "alsa-lib",
            "libXcomposite",
            "libXdamage",
            "libXfixes",
            "libXrandr",
            "libXtst",
            "libX11-xcb",
            "libwayland-cursor",
            "libwayland-egl",
            "libxkbcommon-x11",
            "xcb-util",
            "xcb-util-cursor",
            "xcb-util-image",
            "xcb-util-keysyms",
            "xcb-util-renderutil",
            "xcb-util-wm",
        ),
        "debian": (
            "libgl1",
            "libegl1",
            "libgbm1",
            "libxkbcommon0",
            "libxkbfile1",
            "libdbus-1-3",
            "libasound2t64",
            "libxcomposite1",
            "libxdamage1",
            "libxfixes3",
            "libxrandr2",
            "libxtst6",
            "libx11-xcb1",
            "libwayland-cursor0",
            "libwayland-egl1",
            "libxkbcommon-x11-0",
            "libxcb-cursor0",
            "libxcb-dri3-0",
            "libxcb-icccm4",
            "libxcb-image0",
            "libxcb-keysyms1",
            "libxcb-randr0",
            "libxcb-render-util0",
            "libxcb-shape0",
            "libxcb-sync1",
            "libxcb-util1",
            "libxcb-xfixes0",
            "libxcb-xkb1",
        ),
    },
}


# ────────────────────────────────────────────────────────────| Result model |──
@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single gate."""

    key: str
    label: str
    ok: bool
    required: bool = True
    detail: str = ""

    @property
    def blocking(self) -> bool:
        """True if this failure must stop the app from starting."""
        return self.required and not self.ok


def blocking(results: Iterable[CheckResult]) -> list[CheckResult]:
    """Return only the failures that must stop the app."""
    return [r for r in results if r.blocking]


# ─────────────────────────────────────────────────────────────────| Helpers |──
def _which(name: str) -> str | None:
    """Find a binary, also looking in sbin dirs that users often lack."""
    return shutil.which(name) or shutil.which(name, path=SBIN_PATH)


def _ldd_missing(path: Path) -> set[str] | None:
    """Return unresolved shared libraries of a file, None if unknown."""
    ldd = shutil.which("ldd")
    if ldd is None:
        return None
    try:
        proc = subprocess.run(
            [ldd, str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    return {
        line.split("=>")[0].strip()
        for line in proc.stdout.splitlines()
        if "not found" in line
    }


def _qt_root() -> Path | None:
    """Locate the bundled Qt tree without importing PyQt6."""
    try:
        spec = importlib.util.find_spec("PyQt6")
    except ImportError, ValueError:
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations))) / "Qt6"


# ──────────────────────────────────────────────────────| Distribution hints |──
def detect_family(os_release: Path = OS_RELEASE) -> str | None:
    """Map /etc/os-release to a package manager family, if known."""
    try:
        text = os_release.read_text(encoding="utf-8")
    except OSError:
        return None
    fields: dict[str, str] = {}
    for line in text.splitlines():
        name, sep, value = line.partition("=")
        if sep:
            fields[name] = value.strip().strip('"')
    ids = [fields.get("ID", "")] + fields.get("ID_LIKE", "").split()
    for distro_id in ids:
        if distro_id in FAMILIES:
            return FAMILIES[distro_id]
    return None


def packages_for(keys: Iterable[str], family: str | None) -> list[str]:
    """List the packages for the given check keys, without duplicates."""
    packages: list[str] = []
    if family is None:
        return packages
    for key in keys:
        for package in PACKAGES.get(key, {}).get(family, ()):
            if package not in packages:
                packages.append(package)
    return packages


def install_command(keys: Iterable[str], family: str | None) -> str | None:
    """Build one install command covering every given check key."""
    packages = packages_for(keys, family)
    if family not in INSTALL_PREFIX or not packages:
        return None
    return f"{INSTALL_PREFIX[family]} {' '.join(packages)}"


# ─────────────────────────────────────────────────────────| Preflight gates |──
def check_display(env: Mapping[str, str] | None = None) -> CheckResult:
    """A graphical session must exist, or Qt aborts when opening a window."""
    env = os.environ if env is None else env
    label = "Graphical session"
    if env.get("QT_QPA_PLATFORM") in HEADLESS_PLATFORMS:
        return CheckResult("display", label, True, detail="headless Qt")
    if env.get("WAYLAND_DISPLAY") or env.get("DISPLAY"):
        return CheckResult("display", label, True)
    return CheckResult(
        "display",
        label,
        False,
        detail="no DISPLAY or WAYLAND_DISPLAY, run from a desktop session",
    )


@dataclass(frozen=True)
class QtPlatform:
    """Which Qt platform plugin can load, and which preferred ones cannot."""

    name: str | None
    broken: dict[str, frozenset[str]]
    verified: bool = True

    @property
    def fell_back(self) -> bool:
        """True if a preferred platform was skipped for a working one."""
        return self.name is not None and bool(self.broken)


def pick_qt_platform(env: Mapping[str, str] | None = None) -> QtPlatform:
    """Choose the first platform plugin whose libraries all resolve.

    Qt does not reliably fall back when a plugin is found but cannot load,
    so the choice is made here and applied through QT_QPA_PLATFORM.
    """
    env = os.environ if env is None else env
    root = _qt_root()
    if root is None or env.get("QT_QPA_PLATFORM"):
        return QtPlatform(None, {}, verified=False)

    broken: dict[str, frozenset[str]] = {}
    for name, pattern, session_var in QT_PLATFORMS:
        if not env.get(session_var):
            continue
        plugins = sorted((root / "plugins" / "platforms").glob(pattern))
        if not plugins:
            broken[name] = frozenset({f"{name} plugin"})
            continue
        missing = _ldd_missing(plugins[0])
        if missing is None:
            return QtPlatform(None, {}, verified=False)
        if not missing:
            return QtPlatform(name, broken)
        broken[name] = frozenset(missing)
    return QtPlatform(None, broken, verified=bool(broken))


def check_qt_libs(env: Mapping[str, str] | None = None) -> CheckResult:
    """The bundled Qt needs a few system libraries (GL, xkbcommon, ...)."""
    env = os.environ if env is None else env
    label = "Qt system libraries"
    root = _qt_root()
    if root is None:
        return CheckResult("qt_libs", label, True, detail="PyQt6 not found")

    missing: set[str] = set()
    for lib in QT_CORE_LIBS:
        found = _ldd_missing(root / "lib" / lib)
        if found is None:
            return CheckResult("qt_libs", label, True, detail="not verified")
        missing |= found
    if missing:
        return CheckResult(
            "qt_libs",
            label,
            False,
            detail="missing " + ", ".join(sorted(missing)),
        )

    platform = pick_qt_platform(env)
    if platform.name is None and platform.broken:
        for libs in platform.broken.values():
            missing |= libs
        return CheckResult(
            "qt_libs",
            label,
            False,
            detail="missing " + ", ".join(sorted(missing)),
        )
    if platform.fell_back:
        skipped = ", ".join(
            f"{name} lacks {', '.join(sorted(libs))}"
            for name, libs in platform.broken.items()
        )
        return CheckResult(
            "qt_libs", label, True, detail=f"using {platform.name} ({skipped})"
        )
    return CheckResult("qt_libs", label, True)


def check_qt_import() -> CheckResult:
    """PyQt6 with WebEngine, and qtpy, must import cleanly."""
    label = "Qt for Python"
    try:
        importlib.import_module("qtpy")
        importlib.import_module("PyQt6.QtWebEngineWidgets")
    except ImportError as exc:
        # A missing module means a broken environment, anything else is
        # usually a missing system library, which qt_libs reports.
        hint = ", try `uv sync`" if isinstance(exc, ModuleNotFoundError) else ""
        return CheckResult("qt_python", label, False, detail=f"{exc}{hint}")
    return CheckResult("qt_python", label, True)


def check_webview_import() -> CheckResult:
    """pywebview itself must be installed."""
    label = "pywebview"
    try:
        importlib.import_module("webview")
    except ImportError as exc:
        hint = ", try `uv sync`" if isinstance(exc, ModuleNotFoundError) else ""
        return CheckResult("webview", label, False, detail=f"{exc}{hint}")
    return CheckResult("webview", label, True)


def run_preflight() -> list[CheckResult]:
    """Run the checks that decide whether a window can be opened."""
    return [
        check_display(),
        check_qt_libs(),
        check_qt_import(),
        check_webview_import(),
    ]


# ────────────────────────────────────────────────────────────| System gates |──
def check_binary(
    key: str, label: str, binary: str, *, required: bool = True, why: str = ""
) -> CheckResult:
    """A command line tool must be on PATH."""
    if _which(binary):
        return CheckResult(key, label, True, required)
    return CheckResult(key, label, False, required, detail=why or "not found")


def check_v4l2loopback() -> CheckResult:
    """The kernel module must be loaded or at least installed."""
    key, label = "v4l2loopback", "v4l2loopback kernel module"
    if V4L2LOOPBACK_SYSFS.exists():
        return CheckResult(key, label, True, detail="loaded")

    modinfo = _which("modinfo")
    if modinfo:
        proc = subprocess.run(
            [modinfo, "v4l2loopback"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return CheckResult(key, label, True, detail="installed")
    else:
        release = os.uname().release
        for base in MODULES_DIRS:
            tree = base / release
            if tree.is_dir() and any(tree.rglob("v4l2loopback.ko*")):
                return CheckResult(key, label, True, detail="installed")

    return CheckResult(
        key,
        label,
        False,
        detail="not installed for this kernel, on Fedora it comes from "
        "RPM Fusion",
    )


SYSTEM_KEYS = (
    "scrcpy",
    "adb",
    "ffmpeg",
    "v4l2_ctl",
    "v4l2loopback_ctl",
    "pkexec",
    "modprobe",
    "v4l2loopback",
)


def simulate_missing(
    results: Iterable[CheckResult], keys: Iterable[str]
) -> list[CheckResult]:
    """Mark the given checks as failed, to preview the missing states."""
    wanted = set(keys)
    return [
        (
            replace(r, ok=False, detail="simulated as missing")
            if r.key in wanted
            else r
        )
        for r in results
    ]


def run_system_checks(simulate: Iterable[str] = ()) -> list[CheckResult]:
    """Run the checks for the phone and webcam toolchain."""
    results = [
        check_binary("scrcpy", "scrcpy", "scrcpy"),
        check_binary("adb", "adb", "adb"),
        check_binary(
            "ffmpeg", "ffmpeg", "ffmpeg", why="needed to turn the image"
        ),
        check_binary(
            "v4l2_ctl",
            "v4l2-ctl",
            "v4l2-ctl",
            required=False,
            why="optional, helps find the webcam device",
        ),
        check_binary(
            "v4l2loopback_ctl",
            "v4l2loopback-ctl",
            "v4l2loopback-ctl",
            required=False,
            why="optional, adds a camera without reloading the module",
        ),
        check_binary(
            "pkexec", "pkexec", "pkexec", why="needed to load the module"
        ),
        check_binary("modprobe", "modprobe", "modprobe"),
        check_v4l2loopback(),
    ]
    return simulate_missing(results, simulate)


# ───────────────────────────────────────────────────────────────| Reporting |──
def format_report(
    results: Iterable[CheckResult], family: str | None = None
) -> str:
    """Render results as terminal text with one combined install line."""
    results = list(results)
    lines = []
    for r in results:
        if r.ok:
            mark = "ok"
        else:
            mark = "MISSING" if r.required else "optional"
        suffix = f" - {r.detail}" if r.detail else ""
        lines.append(f"[{mark:^8}] {r.label}{suffix}")
    command = install_command([r.key for r in results if not r.ok], family)
    if command:
        lines += ["", "Install the missing packages with:", f"  {command}"]
    return "\n".join(lines)
