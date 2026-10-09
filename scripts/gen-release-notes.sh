#!/bin/sh
# Generates release notes for a Phone Webcam GitLab Release: the tagged
# version's CHANGELOG.md section (written by `cz bump` before the tag lands
# here) plus a quick-start section.
# Usage: gen-release-notes.sh <tag> [project-url]
set -eu

TAG=$1
PROJECT_URL=${2:-}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CHANGELOG="$SCRIPT_DIR/CHANGELOG.md"

if [ -f "$CHANGELOG" ]; then
  awk -v tag="$TAG" '
    $0 ~ "^## " tag { found=1; print; next }
    found && /^## / { exit }
    found { print }
  ' "$CHANGELOG"
fi

cat << EOF

## Quick start

TBC
EOF
