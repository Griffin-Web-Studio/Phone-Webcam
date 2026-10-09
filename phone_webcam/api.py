"""Bridge exposed to the page through pywebview's js_api."""

from collections.abc import Iterable
from dataclasses import asdict

from phone_webcam import config, deps


class GateApi:
    """Methods the gate page can call as window.pywebview.api.*."""

    def __init__(self, simulate: Iterable[str] = ()) -> None:
        self._simulate = tuple(simulate)

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
