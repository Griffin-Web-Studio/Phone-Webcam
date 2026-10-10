"""Find and provision the v4l2loopback devices the pipeline needs.

One device is used: the pipeline turns the image and writes it into the
output that other apps open. scrcpy reaches the pipeline through a FIFO, so no
second, visible camera is needed. Standard library only.
"""

import shlex
import shutil
from pathlib import Path

# ──────────────────────────────────────────────────────────────────| Config |──
OUTPUT_LABEL = "Android Webcam"
LABELS = (OUTPUT_LABEL,)
V4L2_SYSFS = Path("/sys/class/video4linux")
MODULE_REFCOUNT = Path("/sys/module/v4l2loopback/refcnt")


# ────────────────────────────────────────────────────────────────| Discovery |──
def find_device(label: str, sysfs: Path = V4L2_SYSFS) -> str | None:
    """Find the /dev/videoN node whose card label matches."""
    for entry in sorted(sysfs.glob("video*")):
        try:
            name = (entry / "name").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if name == label:
            return f"/dev/{entry.name}"
    return None


def missing_labels(
    labels: tuple[str, ...] = LABELS, sysfs: Path = V4L2_SYSFS
) -> list[str]:
    """The labels that have no device yet."""
    return [label for label in labels if find_device(label, sysfs) is None]


def module_in_use(refcount: Path = MODULE_REFCOUNT) -> bool:
    """True if something has a loopback device open, so it cannot unload."""
    try:
        return int(refcount.read_text(encoding="utf-8").strip() or 0) > 0
    except OSError, ValueError:
        return False


def has_ctl() -> bool:
    """True if devices can be added to a loaded module."""
    return shutil.which("v4l2loopback-ctl") is not None


# ────────────────────────────────────────────────────────────────| Commands |──
# Each command runs through pkexec as one shell line, so there is a single
# password prompt however many devices it touches.
def _load_line(labels: tuple[str, ...]) -> str:
    caps = ",".join("1" for _ in labels)
    return (
        f"modprobe v4l2loopback devices={len(labels)} exclusive_caps={caps} "
        f"card_label={shlex.quote(','.join(labels))}"
    )


def load_command(labels: tuple[str, ...] = LABELS) -> list[str]:
    """Load the module with every device in one go."""
    return ["pkexec", "sh", "-c", _load_line(labels)]


def reload_command(labels: tuple[str, ...] = LABELS) -> list[str]:
    """Unload the module and load it again, replacing every device."""
    line = f"modprobe -r v4l2loopback && {_load_line(labels)}"
    return ["pkexec", "sh", "-c", line]


def add_command(labels: list[str]) -> list[str]:
    """Add devices to the loaded module, leaving the others untouched."""
    line = " && ".join(
        f"v4l2loopback-ctl add -x 1 -n {shlex.quote(label)}" for label in labels
    )
    return ["pkexec", "sh", "-c", line]
