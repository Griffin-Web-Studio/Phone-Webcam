"""Application settings, read from settings.ini with in-code fallbacks."""

import json
import os
from configparser import ConfigParser
from pathlib import Path

# ──────────────────────────────────────────────────────────────────| Config |──
SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.ini"
DEFAULT_APP_NAME = "Phone Webcam"


# ────────────────────────────────────────────────────────────────| Settings |──
def app_name(path: Path = SETTINGS_PATH) -> str:
    """Return the branding name, falling back if the file or key is missing."""
    parser = ConfigParser()
    parser.read(path, encoding="utf-8")
    name = parser.get("branding", "APP_NAME", fallback="").strip()
    return name or DEFAULT_APP_NAME


# ─────────────────────────────────────────────────────────────| Preferences |──
def prefs_path() -> Path:
    """Where the user's own choices are kept, following the XDG layout."""
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "phone-webcam" / "prefs.json"


def load_prefs(path: Path | None = None) -> dict:
    """Read saved choices, an empty dict if there are none or they are bad."""
    try:
        data = json.loads((path or prefs_path()).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def save_prefs(prefs: dict, path: Path | None = None) -> None:
    """Write the user's choices, ignoring a folder that cannot be written."""
    target = path or prefs_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    except OSError:
        pass
