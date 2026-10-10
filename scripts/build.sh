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

# The version comes from pyproject.toml, so the binary reports the same one as
# the project and the packages.
project_field() {
  (cd "$SCRIPT_DIR" && uv run --no-sync python -c \
    "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['$1'])")
}
VERSION="$(project_field version)"
# Nuitka wants up to four plain numbers, so a suffix such as -rc1 is dropped.
FILE_VERSION="$(echo "$VERSION" | grep -oE '^[0-9]+(\.[0-9]+){0,3}')"
# Nightly builds are all the same plain version, and the folder the binary
# unpacks into is named after it, so each one would run the files of the one
# before. CI passes a number that is different every time, which becomes the
# fourth part of the file version, and so a folder of its own.
if [ -n "${BUILD_NUMBER:-}" ]; then
  FILE_VERSION="$FILE_VERSION.$BUILD_NUMBER"
fi

# The binary unpacks itself once into ~/.cache/<company>/<product>/<version> and
# reuses that on every later start, which is what makes it start quickly. The
# folder is named after the version, so a rebuild with the same version keeps
# running the old unpacked files. Bump the version for a release, and while
# testing delete that folder, or run the binary with XDG_CACHE_HOME pointing
# somewhere empty.

echo "Syncing build dependencies..."
(cd "$SCRIPT_DIR" && uv sync --all-extras)

mkdir -p "$SCRIPT_DIR/dist"

# What the app reads at run time. The web folder is the whole interface, the
# slates folder holds the default cover image, the assets folder holds the app
# icon the cover shows, and settings.ini holds the branding name. pywebview's own script files are found
# by Nuitka itself.
DATA_ARGS=(
  --include-data-dir="$SCRIPT_DIR/phone_webcam/web=phone_webcam/web"
  --include-data-dir="$SCRIPT_DIR/phone_webcam/slates=phone_webcam/slates"
  --include-data-dir="$SCRIPT_DIR/phone_webcam/assets=phone_webcam/assets"
  --include-data-files="$SCRIPT_DIR/settings.ini=settings.ini"
)

echo "Building $BINARY_NAME $VERSION (this takes several minutes the first time)..."
(cd "$SCRIPT_DIR" && uv run python -m nuitka run.py \
  --mode=onefile \
  --output-filename="$BINARY_NAME" \
  --output-dir=build \
  --enable-plugin=pyqt6 \
  --include-module=webview.platforms.qt \
  --include-module=qtpy \
  --noinclude-qt-translations \
  --company-name="$COMPANY_NAME" \
  --product-name="$PRODUCT_NAME" \
  --file-version="$FILE_VERSION" \
  --onefile-tempdir-spec='{CACHE_DIR}/{COMPANY}/{PRODUCT}/{VERSION}' \
  --assume-yes-for-downloads \
  --remove-output \
  "${DATA_ARGS[@]}")

cp "$SCRIPT_DIR/build/$BINARY_NAME" "$SCRIPT_DIR/dist/$BINARY_NAME"

if [ ! -f "$SCRIPT_DIR/dist/$BINARY_NAME" ]; then
  echo "ERROR: build failed - dist/$BINARY_NAME not found" >&2
  exit 1
fi

echo "Build complete → $SCRIPT_DIR/dist/$BINARY_NAME ($(du -h "$SCRIPT_DIR/dist/$BINARY_NAME" | cut -f1))"
