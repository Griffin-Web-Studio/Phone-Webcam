"""The stream settings the user can change, with validation.

Standard library only.
"""

from dataclasses import asdict, dataclass

# ──────────────────────────────────────────────────────────────────| Choices |──
RESOLUTIONS = {"720p": (1280, 720), "1080p": (1920, 1080)}
FPS_CHOICES = (15, 24, 30, 60)
BITRATE_CHOICES = (4, 8, 12, 16, 24)
PREVIEW_FPS_CHOICES = (15, 30, 60)


# ─────────────────────────────────────────────────────────────────| Settings |──
@dataclass(frozen=True)
class Settings:
    """How the webcam is produced. Bitrates are in megabits per second."""

    resolution: str = "1080p"
    fps: int = 30
    bitrate: int = 8
    preview_fps: int = 30

    @property
    def size(self) -> tuple[int, int]:
        return RESOLUTIONS[self.resolution]

    @property
    def preview_rate(self) -> int:
        """The preview cannot show more frames than the output makes."""
        return min(self.preview_fps, self.fps)

    @classmethod
    def from_dict(cls, data: object) -> "Settings":
        """Build settings from saved or submitted data, ignoring bad values."""
        base = cls()
        if not isinstance(data, dict):
            return base
        choices = {
            "resolution": tuple(RESOLUTIONS),
            "fps": FPS_CHOICES,
            "bitrate": BITRATE_CHOICES,
            "preview_fps": PREVIEW_FPS_CHOICES,
        }
        values = {
            key: data[key] if data.get(key) in options else getattr(base, key)
            for key, options in choices.items()
        }
        return cls(**values)

    def as_dict(self) -> dict:
        return asdict(self)
