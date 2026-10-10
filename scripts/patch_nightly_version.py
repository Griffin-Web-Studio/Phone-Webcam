#!/usr/bin/env python3
"""Mark the version in pyproject.toml as a nightly build.

Run by the GitLab CI nightly build job before anything is built, so the
packages carry a distinct, traceable version, for example
"0.2.0+nightly.57.a1b2c3d", instead of the release version committed to the
repo. Only the checked-out worktree of that CI job is changed, it is never
committed.

It is a "local version", which is what PEP 440 calls a +suffix. That matters,
because uv refuses any version that is not valid PEP 440, and a "-nightly" label
is not. It also sorts right: a nightly is built after the release it is based
on, so it is newer than it, and Debian and RPM both order a +suffix that way.
The suffix starts with the pipeline number, so nightlies sort by recency and
not by the random letters of a commit hash.
"""

import re
import sys
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

# The project's own version is the first one in the file. The commitizen
# section has one too, but nothing builds from it.
VERSION_LINE = re.compile(r'^version = "([^"]*)"', re.MULTILINE)
SUFFIX = re.compile(r"[0-9A-Za-z]+(\.[0-9A-Za-z]+)*")


def patch(text: str, suffix: str) -> str:
    """Return the file's text with the first version suffixed."""
    if not SUFFIX.fullmatch(suffix):
        raise ValueError(
            f"the suffix must be letters and digits split by dots, not {suffix!r}"
        )
    patched, count = VERSION_LINE.subn(
        lambda m: f'version = "{m.group(1)}+nightly.{suffix}"', text, count=1
    )
    if count == 0:
        raise ValueError("no version line found")
    return patched


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not argv[1]:
        print(
            "usage: patch_nightly_version.py <pipeline>.<sha>", file=sys.stderr
        )
        return 1
    try:
        PYPROJECT.write_text(
            patch(PYPROJECT.read_text(encoding="utf-8"), argv[1]),
            encoding="utf-8",
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Patched {PYPROJECT}: version suffixed with +nightly.{argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
