#!/usr/bin/env bash
# phone-webcam build-rpm.sh - packages dist/phone-webcam as an .rpm in dist/
# Run from anywhere. Builds the binary first (scripts/build.sh) if it is not
# there yet. Needs rpmbuild (Fedora: sudo dnf install rpm-build).
#
# The package carries the prebuilt Nuitka binary, the desktop entry, the icon,
# the AppStream metadata and a man page. Nothing is compiled by rpmbuild.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="phone-webcam"
APP_ID="studio.griffin_web.phone_webcam"
BINARY="$ROOT/dist/$NAME"
TOP="$ROOT/build/rpm"

if ! command -v rpmbuild &>/dev/null; then
  echo "ERROR: rpmbuild is not installed." >&2
  echo "       Fedora: sudo dnf install rpm-build" >&2
  echo "       Debian: sudo apt install rpm" >&2
  exit 1
fi

if [ ! -x "$BINARY" ]; then
  echo "dist/$NAME not found, building it first..."
  "$ROOT/scripts/build.sh"
fi

field() {
  (cd "$ROOT" && uv run --no-sync python -c \
    "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['$1'])")
}
VERSION="$(field version)"
SUMMARY="$(field description)"
URL="$(git -C "$ROOT" remote get-url origin 2>/dev/null | sed -E 's#\.git$##' || true)"
MAINTAINER="${MAINTAINER:-$(git -C "$ROOT" config user.name) <$(git -C "$ROOT" config user.email)>}"
# rpm checks that the weekday matches the date, so it is written the way it wants.
CHANGELOG_DATE="$(LC_ALL=C date '+%a %b %d %Y')"
DATE_ISO="$(date +%F)"

rm -rf "$TOP"
mkdir -p "$TOP"/{SOURCES,SPECS,BUILD,RPMS,SRPMS,BUILDROOT}

cp "$BINARY" "$TOP/SOURCES/$NAME"
cp "$ROOT/packaging/$APP_ID.desktop" "$TOP/SOURCES/"
cp "$ROOT/phone_webcam/assets/$NAME.svg" "$TOP/SOURCES/$APP_ID.svg"
cp "$ROOT/packaging/$NAME.1" "$TOP/SOURCES/"
cp "$ROOT/LICENSE" "$TOP/SOURCES/"
sed "s/@VERSION@/$VERSION/; s/@DATE@/$DATE_ISO/" \
  "$ROOT/packaging/$APP_ID.metainfo.xml.in" \
  >"$TOP/SOURCES/$APP_ID.metainfo.xml"

# One "Requires:" or "Recommends:" line per package, taken from deps.py.
dependency_lines() {
  uv run --no-sync python "$ROOT/scripts/gen_requires.py" \
    --family fedora --kind "$1" | sed "s/^/$2: /"
}
REQUIRES="$(dependency_lines required Requires)"
RECOMMENDS="$(dependency_lines recommended Recommends)"

# Fill the spec in with Python, the lists are several lines long.
VERSION="$VERSION" SUMMARY="$SUMMARY" URL="${URL:-unknown}" \
MAINTAINER="$MAINTAINER" CHANGELOG_DATE="$CHANGELOG_DATE" \
REQUIRES="$REQUIRES" RECOMMENDS="$RECOMMENDS" \
uv run --no-sync python - "$ROOT/packaging/rpm/$NAME.spec.in" \
  "$TOP/SPECS/$NAME.spec" <<'PY'
import os
import sys

template, target = sys.argv[1:3]
text = open(template, encoding="utf-8").read()
for key in (
    "VERSION", "SUMMARY", "URL", "MAINTAINER",
    "CHANGELOG_DATE", "REQUIRES", "RECOMMENDS",
):
    text = text.replace(f"@{key}@", os.environ[key])
open(target, "w", encoding="utf-8").write(text)
PY

# A private package database keeps rpmbuild away from the system's one, which
# a non-root user, or Debian's rpm, cannot open.
rpmbuild -bb --quiet "$TOP/SPECS/$NAME.spec" \
  --define "_topdir $TOP" \
  --define "_dbpath $TOP/db" \
  --define "_build_id_links none"

mkdir -p "$ROOT/dist"
cp "$TOP"/RPMS/*/*.rpm "$ROOT/dist/"
RPM_FILE="$(ls -1 "$ROOT"/dist/*.rpm | tail -1)"

# Check the result when rpmlint is there. It only reports, a finding does not
# stop the build. The filters and the reason for each are in the rpmlintrc.
if command -v rpmlint &>/dev/null; then
  rpmlint -r "$ROOT/packaging/rpm/$NAME.rpmlintrc" "$RPM_FILE" || true
fi

echo "Package complete → $RPM_FILE ($(du -h "$RPM_FILE" | cut -f1))"
