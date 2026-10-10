"""Bridge exposed to the page through pywebview's js_api."""

import json
import queue
import threading
from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from phone_webcam import config, deps, pipeline, webcam
from phone_webcam.clipboard import Clipboard


class Api:
    """Methods the pages can call as window.pywebview.api.*."""

    def __init__(self, simulate: Iterable[str] = ()) -> None:
        self._simulate = tuple(simulate)
        self._window: Any = None
        self._clipboard = Clipboard()
        # Events leave through one thread, so they reach the page in order.
        self._events: queue.Queue[dict | None] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        prefs = config.load_prefs()
        rotation = prefs.get("rotation", 0)
        self._webcam = webcam.Webcam(
            self._push,
            rotation if rotation in pipeline.ROTATIONS else 0,
            bool(prefs.get("mirror", False)),
        )

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

    def copy_text(self, text: str) -> None:
        """Put text on the system clipboard."""
        self._clipboard.copy(text)

    # ───────────────────────────────────────────────────────────| Webcam |──
    def get_state(self) -> str:
        """Current webcam state, for a page that has just loaded."""
        return self._webcam.state

    def start(self) -> None:
        self._webcam.start()

    def stop(self) -> None:
        self._webcam.stop()

    def get_orientation(self) -> dict:
        """The current rotation and mirror, for a page that has just loaded."""
        return self._webcam.orientation()

    def set_orientation(self, rotation: int, mirror: bool) -> None:
        """Turn the image, live, and remember the choice."""
        self._webcam.set_orientation(rotation, mirror)
        config.save_prefs({"rotation": rotation, "mirror": mirror})

    def answer(self, yes: bool) -> None:
        """Reply to a confirmation the page was asked to show."""
        self._webcam.answer(yes)

    def toggle_preview(self) -> None:
        """Open or close the preview window."""
        self._webcam.toggle_preview()

    def shutdown(self) -> None:
        """Stop the webcam when the window closes."""
        self._webcam.stop()
        self._webcam.join()
        self._events.put(None)
        self._window = None

    # ───────────────────────────────────────────────────────────| Events |──
    def _push(self, event: dict) -> None:
        """Queue an event for the page, never blocking the caller."""
        self._events.put(event)

    def _pump(self) -> None:
        """Deliver queued events to the page, in the order they were made."""
        while (event := self._events.get()) is not None:
            window = self._window
            if window is None:
                continue
            payload = json.dumps(event)
            try:
                window.evaluate_js(
                    f"window.onWebcamEvent && window.onWebcamEvent({payload})"
                )
            except Exception:  # noqa: BLE001 - the window may be mid-close
                pass
