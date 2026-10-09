"""Application settings, read from settings.ini with in-code fallbacks."""

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
