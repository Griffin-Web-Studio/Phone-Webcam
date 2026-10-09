"""Bridge exposed to the page through pywebview's js_api."""

import json
from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from phone_webcam import config, deps, webcam


class Api:
    """Methods the pages can call as window.pywebview.api.*."""

    def __init__(self, simulate: Iterable[str] = ()) -> None:
        self._simulate = tuple(simulate)
        self._window: Any = None
        self._webcam = webcam.Webcam(self._push)

    def attach(self, window: Any) -> None:
        """Give the bridge the window it pushes events to."""
        self._window = window

    # ─────────────────────────────────────────────────────────────| Gates |──
    def get_report(self) -> dict:
        """Run the system gates and describe them for the page."""
        results = deps.run_system_checks(self._simulate)
        missing = [r.key for r in results if not r.ok]
        return {
            "app_name": config.app_name(),
            "checks": [asdict(r) for r in results],
            "ready": not deps.blocking(results),
            "command": deps.install_command(missing, deps.detect_family()),
        }

    # ───────────────────────────────────────────────────────────| Webcam |──
    def get_state(self) -> str:
        """Current webcam state, for a page that has just loaded."""
        return self._webcam.state

    def start(self) -> None:
        self._webcam.start()

    def stop(self) -> None:
        self._webcam.stop()

    def shutdown(self) -> None:
        """Stop the webcam when the window closes."""
        self._window = None
        self._webcam.stop()

    # ───────────────────────────────────────────────────────────| Events |──
    def _push(self, event: dict) -> None:
        """Send an event to the page, if it is listening."""
        window = self._window
        if window is None:
            return
        payload = json.dumps(event)
        try:
            window.evaluate_js(
                f"window.onWebcamEvent && window.onWebcamEvent({payload})"
            )
        except Exception:  # noqa: BLE001 - the window may be mid-close
            pass
