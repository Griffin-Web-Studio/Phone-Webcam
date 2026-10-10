#!/usr/bin/env python3
"""Print the system packages the app needs, for the package builders.

The lists live in phone_webcam/deps.py, which is also what the app's own
dependency check uses, so a package can never ask for something different from
what the app looks for. One package name is printed per line.

    gen_requires.py --family debian --kind required
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phone_webcam import deps  # noqa: E402

# What the app cannot run without, and what only makes it nicer to use.
REQUIRED = ("scrcpy", "adb", "ffmpeg", "pkexec", "modprobe", "qt_libs")
RECOMMENDED = ("v4l2_ctl", "v4l2loopback_ctl", "v4l2loopback")

# ffmpeg is asked for by its command. Fedora's own ffmpeg-free and RPM Fusion's
# ffmpeg replace each other, and asking for either by name would force a swap
# on people who have the other.
COMMAND_DEPENDENCIES = {("fedora", "ffmpeg"): "/usr/bin/ffmpeg"}


def requirements(family: str, kind: str) -> list[str]:
    """The package names for one family, without duplicates."""
    keys = {"required": REQUIRED, "recommended": RECOMMENDED}[kind]
    names: list[str] = []
    for key in keys:
        replacement = COMMAND_DEPENDENCIES.get((family, key))
        found = (
            [replacement] if replacement else deps.packages_for([key], family)
        )
        for name in found:
            if name not in names:
                names.append(name)
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--family", choices=("debian", "fedora"), required=True)
    parser.add_argument(
        "--kind", choices=("required", "recommended"), required=True
    )
    args = parser.parse_args(argv)
    print("\n".join(requirements(args.family, args.kind)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
