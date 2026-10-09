"""Start-up flow: preflight gates, then the window, then system gates."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from phone_webcam import config, deps

WEB_DIR = Path(__file__).resolve().parent / "web"

# ──────────────────────────────────────────────────────────────| Exit codes |──
EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_PREFLIGHT = 2
EXIT_BACKEND = 3


# ───────────────────────────────────────────────────────| Failure reporting |──
def notify(title: str, body: str) -> None:
    """Best-effort desktop popup, for launches without a terminal."""
    if sys.stderr.isatty():
        return
    for tool, args in (
        ("zenity", ["--error", "--title", title, "--text", body]),
        ("notify-send", [title, body]),
    ):
        path = shutil.which(tool)
        if path:
            try:
                subprocess.run([path, *args], check=False, timeout=60)
            except OSError, subprocess.TimeoutExpired:
                continue
            return


def fail(results: list[deps.CheckResult], heading: str) -> None:
    """Print the failure report to stderr and try a desktop popup."""
    report = deps.format_report(results, deps.detect_family())
    print(f"{heading}\n\n{report}", file=sys.stderr)
    notify(config.app_name(), f"{heading}\n\n{report}")


# ──────────────────────────────────────────────────────────────────| Window |──
def run_window(simulate: tuple[str, ...] = ()) -> int:
    """Open the gate window. Only reached once preflight has passed."""
    platform = deps.pick_qt_platform()
    if platform.fell_back and platform.name:
        # The preferred display server cannot load, use the working one.
        os.environ["QT_QPA_PLATFORM"] = platform.name

    import webview  # deferred, pywebview is imported after preflight

    from phone_webcam.api import GateApi

    webview.create_window(
        config.app_name(),
        url=str(WEB_DIR / "gate.html"),
        js_api=GateApi(simulate),
        width=520,
        height=620,
    )
    try:
        webview.start(gui="qt")
    except webview.errors.WebViewException as exc:
        fail(
            [
                deps.CheckResult(
                    "backend", "GUI backend", False, detail=str(exc)
                )
            ],
            "The window could not be opened.",
        )
        return EXIT_BACKEND
    return EXIT_OK


# ────────────────────────────────────────────────────────────────────| Main |──
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phone Webcam")
    parser.add_argument(
        "--check",
        action="store_true",
        help="run every dependency gate, print the result and exit",
    )
    parser.add_argument(
        "--simulate-missing",
        metavar="KEYS",
        default="",
        help="pretend these system checks fail, comma separated, one or more "
        f"of: {', '.join(deps.SYSTEM_KEYS)}",
    )
    args = parser.parse_args(argv)
    simulate = tuple(k for k in args.simulate_missing.split(",") if k)
    unknown = [k for k in simulate if k not in deps.SYSTEM_KEYS]
    if unknown:
        parser.error(f"unknown check key(s): {', '.join(unknown)}")

    preflight = deps.run_preflight()

    if args.check:
        results = preflight + deps.run_system_checks(simulate)
        print(deps.format_report(results, deps.detect_family()))
        return EXIT_CHECK_FAILED if deps.blocking(results) else EXIT_OK

    if deps.blocking(preflight):
        fail(preflight, "Cannot open the window, the GUI stack is incomplete.")
        return EXIT_PREFLIGHT

    return run_window(simulate)
