#!/usr/bin/env bash
# phone-webcam check-packages.sh - checks what the packaging scripts made
# Run from anywhere, after scripts/build-deb.sh and scripts/build-rpm.sh. CI runs
# it too, so a package that would be rejected is caught before a release.
#
#   --require-tools   a missing checker is an error, not a skipped check
#
# It runs lintian on the .deb, rpmlint on the .rpm (with the project's filters),
# and validates the desktop entry and the AppStream metadata. Any error or
# warning fails it.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_ID="studio.griffin_web.phone_webcam"
REQUIRE=0
[ "${1:-}" = "--require-tools" ] && REQUIRE=1

failed=0
skipped=0

# Runs one check, or notes that its tool is missing.
check() {
  local tool="$1" label="$2"
  shift 2
  if ! command -v "$tool" &>/dev/null; then
    echo "SKIP  $label ($tool is not installed)"
    skipped=$((skipped + 1))
    return
  fi
  echo "CHECK $label"
  if ! "$@"; then
    echo "FAIL  $label"
    failed=$((failed + 1))
  fi
}

shopt -s nullglob
debs=("$ROOT"/dist/*.deb)
rpms=("$ROOT"/dist/*.rpm)
if [ ${#debs[@]} -eq 0 ] && [ ${#rpms[@]} -eq 0 ]; then
  echo "ERROR: no packages in dist/, run scripts/build-deb.sh or build-rpm.sh first" >&2
  exit 1
fi

for deb in "${debs[@]}"; do
  check lintian "lintian $(basename "$deb")" \
    lintian --fail-on error,warning --tag-display-limit 0 "$deb"
done

for rpm in "${rpms[@]}"; do
  check rpmlint "rpmlint $(basename "$rpm")" \
    rpmlint -r "$ROOT/packaging/rpm/phone-webcam.rpmlintrc" "$rpm"
done

check desktop-file-validate "desktop entry" \
  desktop-file-validate "$ROOT/packaging/$APP_ID.desktop"

# The metadata is a template, so its placeholders are filled in to validate it.
filled="$(mktemp --suffix=.metainfo.xml)"
trap 'rm -f "$filled"' EXIT
sed 's/@VERSION@/0.0.0/; s/@DATE@/2026-01-01/' \
  "$ROOT/packaging/$APP_ID.metainfo.xml.in" >"$filled"
check appstreamcli "AppStream metadata" appstreamcli validate --no-net "$filled"

echo
if [ "$failed" -gt 0 ]; then
  echo "$failed check(s) failed" >&2
  exit 1
fi
if [ "$skipped" -gt 0 ] && [ "$REQUIRE" -eq 1 ]; then
  echo "$skipped check(s) were skipped, and --require-tools was given" >&2
  exit 1
fi
echo "All checks passed ($skipped skipped)"
