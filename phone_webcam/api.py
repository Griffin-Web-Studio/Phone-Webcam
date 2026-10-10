"""Bridge exposed to the page through pywebview's js_api."""

import json
import queue
import sys
import threading
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from phone_webcam import config, deps, phone, pipeline, slate, webcam
from phone_webcam.clipboard import Clipboard
from phone_webcam.settings import Settings, SlateSettings

APP_SIZE = (1100, 720)


class Api:
    """Methods the pages can call as window.pywebview.api.*."""

    def __init__(
        self, simulate: Iterable[str] = (), debug: bool = False
    ) -> None:
        self._simulate = tuple(simulate)
        # --debug also prints the log to the terminal, as it is written.
        self._echo = debug
        self._window: Any = None
        self._clipboard = Clipboard()
        self._phone = phone.Monitor(self._push)
        # Events leave through one thread, so they reach the page in order.
        self._events: queue.Queue[dict | None] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        prefs = config.load_prefs()
        rotation = prefs.get("rotation", 0)
        self._webcam = webcam.Webcam(
            self._push,
            rotation if rotation in pipeline.ROTATIONS else 0,
            bool(prefs.get("mirror", False)),
            Settings.from_dict(prefs.get("settings")),
            SlateSettings.from_dict(prefs.get("cover")),
            debug or prefs.get("debug") is True,
        )

    def attach(self, window: Any) -> None:
        """Give the bridge the window it pushes events to."""
        self._window = window
        self._phone.start()

    def enter_app(self) -> None:
        """Make the window big enough for the main view."""
        window = self._window
        if window is not None:
            window.resize(*APP_SIZE)

    def get_side_width(self) -> int:
        """The side panel's saved width in pixels, 0 for the default."""
        width = config.load_prefs().get("side_width", 0)
        return width if isinstance(width, int) and width > 0 else 0

    def set_side_width(self, width: int) -> None:
        """Remember the side panel's width, 0 to go back to the default."""
        config.update_prefs({"side_width": max(0, int(width))})

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
    def get_phone(self) -> str:
        """The phone's state, for a page that has just loaded."""
        current = self._phone.current
        return (current or self._phone.poll()).state

    def get_state(self) -> str:
        """Current webcam state, for a page that has just loaded."""
        return self._webcam.state

    def start(self) -> None:
        self._webcam.start()

    def stop(self) -> None:
        self._webcam.stop()

    def get_settings(self) -> dict:
        """The stream settings, for a page that has just loaded."""
        return self._webcam.settings()

    def set_settings(self, data: dict) -> dict:
        """Change the stream settings and remember them."""
        applied = self._webcam.set_settings(data)
        config.update_prefs({"settings": applied})
        return applied

    def get_debug(self) -> bool:
        """Whether the detailed log is on, for a page that has just loaded."""
        return self._webcam.debugging()

    def set_debug(self, on: bool) -> None:
        """Turn the detailed log on or off, and remember the choice."""
        self._webcam.set_debugging(bool(on))
        config.update_prefs({"debug": bool(on)})

    def get_shutter(self) -> bool:
        """Whether the cover is on, for a page that has just loaded."""
        return self._webcam.shutter()

    def set_shutter(self, on: bool) -> None:
        """Cover the camera with the slate, or take the cover off."""
        self._webcam.set_shutter(bool(on))

    def get_cover(self) -> dict:
        """The cover's text, image and options."""
        return self._webcam.cover_settings()

    def set_cover(self, data: dict) -> dict:
        """Change the cover and remember it."""
        applied = self._webcam.set_cover_settings(data)
        config.update_prefs({"cover": applied})
        return applied

    def choose_cover_svg(self) -> dict:
        """Let the user pick an SVG for the cover, after checking it draws.

        Returns ok with the new settings, or the reason it was not used. A
        message that is empty means the dialog was cancelled.
        """
        window = self._window
        if window is None:
            return {"ok": False, "message": ""}
        import webview  # deferred, like the rest of the GUI stack

        chosen = window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=("SVG images (*.svg)",),
        )
        if not chosen:
            return {"ok": False, "message": ""}
        path = Path(chosen[0])
        error = slate.check_svg(path)
        if error:
            return {"ok": False, "message": error}
        return {
            "ok": True,
            "message": "",
            "cover": self.set_cover({"svg": str(path)}),
        }

    def get_orientation(self) -> dict:
        """The current rotation and mirror, for a page that has just loaded."""
        return self._webcam.orientation()

    def set_orientation(self, rotation: int, mirror: bool) -> None:
        """Turn the image, live, and remember the choice."""
        self._webcam.set_orientation(rotation, mirror)
        config.update_prefs({"rotation": rotation, "mirror": mirror})

    def list_cameras(self) -> list[dict]:
        """The phone's cameras, which takes a moment, so ask when needed."""
        return self._webcam.list_cameras()

    def get_camera(self) -> str:
        """The chosen camera's id, empty for the default."""
        return self._webcam.camera()

    def set_camera(self, camera_id: str) -> None:
        """Choose a camera, switching live if the webcam is running."""
        self._webcam.set_camera(camera_id)

    def answer(self, yes: bool) -> None:
        """Reply to a confirmation the page was asked to show."""
        self._webcam.answer(yes)

    def show_preview(self, wanted: bool) -> None:
        """Say whether the preview should show, it follows when it can."""
        self._webcam.set_preview_wanted(wanted)

    def shutdown(self) -> None:
        """Stop the webcam when the window closes."""
        self._phone.stop()
        self._webcam.stop()
        self._webcam.join()
        self._events.put(None)
        self._window = None

    # ───────────────────────────────────────────────────────────| Events |──
    def _push(self, event: dict) -> None:
        """Queue an event for the page, never blocking the caller."""
        if self._echo and event.get("type") == "log":
            print(event["line"], file=sys.stderr, flush=True)
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
