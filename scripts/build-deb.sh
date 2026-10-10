#!/usr/bin/env bash
# phone-webcam build-deb.sh - packages dist/phone-webcam as a .deb in dist/
# Run from anywhere. Builds the binary first (scripts/build.sh) if it is not
# there yet.
#
# The package carries the prebuilt Nuitka binary, the desktop entry, the icon,
# the AppStream metadata and a man page. The binary must not be stripped, it is
# a small launcher with the app appended to it, and stripping cuts that off.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="phone-webcam"
APP_ID="studio.griffin_web.phone_webcam"
BINARY="$ROOT/dist/$NAME"
STAGE_ROOT="$ROOT/build/deb"

for tool in dpkg-deb dpkg-shlibdeps gzip; do
  if ! command -v "$tool" &>/dev/null; then
    echo "ERROR: $tool is not installed (sudo apt install dpkg-dev)." >&2
    exit 1
  fi
done

if [ ! -x "$BINARY" ]; then
  echo "dist/$NAME not found, building it first..."
  "$ROOT/scripts/build.sh"
fi

field() {
  (cd "$ROOT" && uv run --no-sync python -c \
    "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['$1'])")
}
VERSION="$(field version)"
# A pre-release such as 1.0.0-rc.0 or 1.0.0-nightly.abc1234 is a fine git tag, but
# in a package version a dash starts the revision, and rpm does not allow it at
# all. A tilde says "sorts before the plain version", which is what a
# pre-release means, so 1.0.0~rc.0 comes before 1.0.0.
VERSION="${VERSION//-/\~}"
SUMMARY="$(field description)"
ARCH="$(dpkg --print-architecture)"
HOMEPAGE="$(git -C "$ROOT" remote get-url origin 2>/dev/null | sed -E 's#\.git$##' || true)"
# CI has no git identity, so it passes MAINTAINER in the environment.
MAINTAINER="${MAINTAINER:-$(git -C "$ROOT" config user.name) <$(git -C "$ROOT" config user.email)>}"
DATE_RFC="$(date -R)"
DATE_ISO="$(date +%F)"

PKG="${NAME}_${VERSION}_${ARCH}"
STAGE="$STAGE_ROOT/$PKG"
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" \
  "$STAGE/usr/bin" \
  "$STAGE/usr/share/applications" \
  "$STAGE/usr/share/icons/hicolor/scalable/apps" \
  "$STAGE/usr/share/metainfo" \
  "$STAGE/usr/share/doc/$NAME" \
  "$STAGE/usr/share/man/man1"

install -m 0755 "$BINARY" "$STAGE/usr/bin/$NAME"
install -m 0644 "$ROOT/packaging/$APP_ID.desktop" \
  "$STAGE/usr/share/applications/$APP_ID.desktop"
install -m 0644 "$ROOT/phone_webcam/assets/$NAME.svg" \
  "$STAGE/usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"
sed "s/@VERSION@/$VERSION/; s/@DATE@/$DATE_ISO/" \
  "$ROOT/packaging/$APP_ID.metainfo.xml.in" \
  >"$STAGE/usr/share/metainfo/$APP_ID.metainfo.xml"
chmod 0644 "$STAGE/usr/share/metainfo/$APP_ID.metainfo.xml"

gzip -9n -c "$ROOT/packaging/$NAME.1" >"$STAGE/usr/share/man/man1/$NAME.1.gz"
chmod 0644 "$STAGE/usr/share/man/man1/$NAME.1.gz"

# Debian wants a changelog and a copyright file in every package. A version
# without a Debian revision is a native package, whose changelog is changelog.gz.
{
  echo "$NAME ($VERSION) unstable; urgency=low"
  echo
  echo "  * Release $VERSION."
  echo
  echo " -- $MAINTAINER  $DATE_RFC"
} | gzip -9n >"$STAGE/usr/share/doc/$NAME/changelog.gz"
chmod 0644 "$STAGE/usr/share/doc/$NAME/changelog.gz"

cat >"$STAGE/usr/share/doc/$NAME/copyright" <<COPYRIGHT
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: $NAME
Upstream-Contact: $MAINTAINER
Source: ${HOMEPAGE:-unknown}

Files: *
Copyright: $(date +%Y) Griffin Web Studio
License: GPL-3+

License: GPL-3+
 This program is free software: you can redistribute it and/or modify it under
 the terms of the GNU General Public License as published by the Free Software
 Foundation, either version 3 of the License, or (at your option) any later
 version.
 .
 On Debian systems, the complete text of the GNU General Public License
 version 3 can be found in /usr/share/common-licenses/GPL-3.
COPYRIGHT
chmod 0644 "$STAGE/usr/share/doc/$NAME/copyright"

# The libraries the launcher itself links against, worked out from the binary.
# Everything the app unpacks at run time needs glibc 2.38 at most, the same
# as the launcher, which was checked by reading the symbols of every file.
# dpkg-shlibdeps wants a debian/control to read, so it gets a throwaway one.
SHLIBS_DIR="$(mktemp -d)"
trap 'rm -rf "$SHLIBS_DIR"' EXIT
mkdir -p "$SHLIBS_DIR/debian"
printf 'Source: %s\n\nPackage: %s\nArchitecture: any\n' "$NAME" "$NAME" \
  >"$SHLIBS_DIR/debian/control"
SHLIBS="$(cd "$SHLIBS_DIR" && dpkg-shlibdeps -O -e"$STAGE/usr/bin/$NAME" 2>/dev/null \
  | sed -n 's/^shlibs:Depends=//p')"

join_lines() { paste -sd, - | sed 's/,/, /g'; }
REQUIRED="$(uv run --no-sync python "$ROOT/scripts/gen_requires.py" \
  --family debian --kind required | join_lines)"
RECOMMENDED="$(uv run --no-sync python "$ROOT/scripts/gen_requires.py" \
  --family debian --kind recommended | join_lines)"
DEPENDS="$(printf '%s, %s' "$SHLIBS" "$REQUIRED" | sed 's/^, //; s/, $//')"

INSTALLED_KB="$(du -sk "$STAGE" | cut -f1)"

cat >"$STAGE/DEBIAN/control" <<CONTROL
Package: $NAME
Version: $VERSION
Section: video
Priority: optional
Architecture: $ARCH
Maintainer: $MAINTAINER
Installed-Size: $INSTALLED_KB
Depends: $DEPENDS
Recommends: $RECOMMENDED
Suggests: scrcpy
${HOMEPAGE:+Homepage: $HOMEPAGE
}Description: $SUMMARY
 Turns the camera of an Android phone into a virtual webcam that other apps,
 such as video calls and browsers, can use. The phone is connected over USB,
 and the picture can be turned, mirrored and previewed while it is running.
 .
 It needs scrcpy 2.2 or newer, which Debian does not package at that version,
 and the v4l2loopback kernel module. The app checks for both when it starts
 and says what is missing.
CONTROL

# File checksums let dpkg --verify and debsums notice a damaged install.
(cd "$STAGE" && find usr -type f -print0 | sort -z | xargs -0 md5sum \
  >DEBIAN/md5sums)

mkdir -p "$ROOT/dist"
# The payload is already compressed, so a light pass is all it needs. xz is
# what Debian's own tools accept, newer compressors are rejected by lintian.
dpkg-deb --root-owner-group -Zxz -z1 --build "$STAGE" "$ROOT/dist/$PKG.deb"

echo "Package complete → $ROOT/dist/$PKG.deb ($(du -h "$ROOT/dist/$PKG.deb" | cut -f1))"
