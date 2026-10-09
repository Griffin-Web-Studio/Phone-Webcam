#!/bin/bash
# scrcpy is not packaged in Debian, so install the official release. It is
# pinned to the version used on the host, and the checksum is pinned here
# rather than fetched, so a changed download is rejected. The tarball also
# provides adb and scrcpy-server.
set -euo pipefail

VERSION=4.1
SHA256=ad56ae8bfeedf41e824945c11dbf55fcb092b3e615b9b486f48a50e30d389635
NAME="scrcpy-linux-x86_64-v${VERSION}.tar.gz"
URL="https://github.com/Genymobile/scrcpy/releases/download/v${VERSION}/${NAME}"
PREFIX=/opt/scrcpy

if [ -x "${PREFIX}/scrcpy" ] && "${PREFIX}/scrcpy" --version | grep -q "^scrcpy ${VERSION}"; then
  echo "scrcpy ${VERSION} already installed"
else
  TMP=$(mktemp -d)
  trap 'rm -rf "$TMP"' EXIT
  curl -fsSL -o "${TMP}/${NAME}" "$URL"
  echo "${SHA256}  ${TMP}/${NAME}" | sha256sum -c -
  sudo rm -rf "$PREFIX"
  sudo mkdir -p "$PREFIX"
  sudo tar -xzf "${TMP}/${NAME}" -C "$PREFIX" --strip-components=1
fi

# Symlinks are safe: scrcpy finds scrcpy-server next to its real binary.
sudo ln -sf "${PREFIX}/scrcpy" /usr/local/bin/scrcpy
sudo ln -sf "${PREFIX}/adb" /usr/local/bin/adb
