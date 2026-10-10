#!/usr/bin/env bash
# phone-webcam build.sh - builds the Nuitka binary into dist/phone-webcam
# Run from anywhere, it works out the project root from its own location.
#
# The binary is one self-extracting file. It still needs scrcpy, adb, ffmpeg
# and the v4l2loopback kernel module on the machine, the app's dependency
# check tells the user what is missing, so none of them are bundled.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BINARY_NAME="phone-webcam"
PRODUCT_NAME="Phone Webcam"
COMPANY_NAME="Griffin Web Studio"
ICON="$SCRIPT_DIR/phone_webcam/assets/phone-webcam.svg"

if ! command -v uv &>/dev/null; then
  echo "ERROR: uv is not installed." >&2
  echo "       Install it from: https://docs.astral.sh/uv/getting-started/installation/" >&2
  echo "       or reopen this project in the devcontainer, where it is" >&2
  echo "       installed automatically along with the other dependencies." >&2
  exit 1
fi

if [ ! -f "$SCRIPT_DIR/pyproject.toml" ]; then
  echo "ERROR: pyproject.toml not found in $SCRIPT_DIR" >&2
  exit 1
fi

# Nuitka turns the Python into C and compiles it, then needs patchelf to
# rewrite the library paths of the files it bundles.
for tool in gcc patchelf; do
  if ! command -v "$tool" &>/dev/null; then
    echo "ERROR: $tool is not installed, Nuitka needs it to build." >&2
    echo "       Fedora: sudo dnf install gcc patchelf" >&2
    echo "       Debian: sudo apt install gcc patchelf" >&2
    exit 1
  fi
done

if [ ! -f "$ICON" ]; then
  echo "ERROR: icon not found at $ICON" >&2
  exit 1
fi

# The version and licence come from pyproject.toml, so the binary and the
# desktop metadata Nuitka writes agree with the project.
project_field() {
  (cd "$SCRIPT_DIR" && uv run --no-sync python -c \
    "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['$1'])")
}
VERSION="$(project_field version)"
LICENSE_ID="$(project_field license)"
# Nuitka wants up to four plain numbers, so a suffix such as -rc1 is dropped.
FILE_VERSION="$(echo "$VERSION" | grep -oE '^[0-9]+(\.[0-9]+){0,3}')"

# The binary unpacks itself once into ~/.cache/<company>/<product>/<version> and
# reuses that on every later start, which is what makes it start quickly. The
# folder is named after the version, so a rebuild with the same version keeps
# running the old unpacked files. Bump the version for a release, and while
# testing delete that folder, or run the binary with XDG_CACHE_HOME pointing
# somewhere empty.

echo "Syncing build dependencies..."
(cd "$SCRIPT_DIR" && uv sync --all-extras)

mkdir -p "$SCRIPT_DIR/dist"

# What the app reads at run time. The web folder is the whole interface and
# settings.ini holds the branding name. pywebview's own script files are found
# by Nuitka itself.
DATA_ARGS=(
  --include-data-dir="$SCRIPT_DIR/phone_webcam/web=phone_webcam/web"
  --include-data-files="$SCRIPT_DIR/settings.ini=settings.ini"
)

echo "Building $BINARY_NAME $VERSION (this takes several minutes the first time)..."
(cd "$SCRIPT_DIR" && uv run python -m nuitka run.py \
  --mode=app \
  --output-filename="$BINARY_NAME" \
  --output-dir=build \
  --enable-plugin=pyqt6 \
  --include-module=webview.platforms.qt \
  --include-module=qtpy \
  --noinclude-qt-translations \
  --linux-app-icon="$ICON" \
  --linux-app-license="$LICENSE_ID" \
  --company-name="$COMPANY_NAME" \
  --product-name="$PRODUCT_NAME" \
  --file-version="$FILE_VERSION" \
  --onefile-tempdir-spec='{CACHE_DIR}/{COMPANY}/{PRODUCT}/{VERSION}' \
  --assume-yes-for-downloads \
  --remove-output \
  "${DATA_ARGS[@]}")

cp "$SCRIPT_DIR/build/$BINARY_NAME" "$SCRIPT_DIR/dist/$BINARY_NAME"

# With --mode=app Nuitka also writes a desktop entry, AppStream metadata and
# the icon beside the binary. They are what a package or an installer needs.
for extra in "$SCRIPT_DIR"/build/com.griffin_web_studio.phone_webcam.*; do
  [ -e "$extra" ] && cp "$extra" "$SCRIPT_DIR/dist/"
done

if [ ! -f "$SCRIPT_DIR/dist/$BINARY_NAME" ]; then
  echo "ERROR: build failed - dist/$BINARY_NAME not found" >&2
  exit 1
fi

echo "Build complete → $SCRIPT_DIR/dist/$BINARY_NAME ($(du -h "$SCRIPT_DIR/dist/$BINARY_NAME" | cut -f1))"
