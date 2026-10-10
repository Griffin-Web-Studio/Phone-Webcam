#!/bin/sh
# Generates release notes for a Phone Webcam GitLab Release: the tagged
# version's section of CHANGELOG.md (written by `cz bump` before the tag was
# made) followed by the install instructions from
# .gitlab/release_notes_templates/default.md.
#
# Usage: gen-release-notes.sh <tag> <channel> <package-url>
#   channel      alpha, beta, rc or stable
#   package-url  where the release's files were published, without a trailing /
#
# CHANGELOG_FILE can point at another changelog, which the tests use.
set -eu

TAG=$1
CHANNEL=$2
PACKAGE_URL=$3

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CHANGELOG=${CHANGELOG_FILE:-$SCRIPT_DIR/CHANGELOG.md}
TEMPLATE="$SCRIPT_DIR/.gitlab/release_notes_templates/default.md"

if [ -f "$CHANGELOG" ]; then
  # The heading is "## v1.0.0 (date)". It is matched whole, so the notes for
  # v1.0.0 never include a v1.0.0-rc.0 section that happens to start the same.
  awk -v heading="## $TAG " '
    index($0, heading) == 1 { found = 1; print; next }
    found && /^## / { exit }
    found { print }
  ' "$CHANGELOG"
  echo
fi

sed \
  -e "s|{{TAG}}|$TAG|g" \
  -e "s|{{VERSION}}|${TAG#v}|g" \
  -e "s|{{CHANNEL}}|$CHANNEL|g" \
  -e "s|{{PACKAGE_URL}}|$PACKAGE_URL|g" \
  "$TEMPLATE"
