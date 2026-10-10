# Contributing to Phone Webcam

## Building

The app is compiled into one self-contained binary with Nuitka, which is then
packaged. Everything is run from the project root, and the results land in
`dist/`. The devcontainer has all of the tools.

| Script                   | Result                                         |
| ------------------------ | ---------------------------------------------- |
| `scripts/build.sh`       | `dist/phone-webcam`, the binary                |
| `scripts/build-deb.sh`   | `dist/phone-webcam_<version>_amd64.deb`        |
| `scripts/build-rpm.sh`   | `dist/phone-webcam-<version>-1.x86_64.rpm`     |

The packages need the binary and build it first if it is missing. The first
build takes a few minutes, later ones are quicker.

- The version and the licence come from `pyproject.toml`.
- The binary unpacks itself once into
  `~/.cache/Griffin Web Studio/Phone Webcam/<version>` and reuses that. A rebuild
  with the same version therefore keeps running the old files until that folder
  is deleted, so bump the version for a release.
- The system packages a package depends on come from `phone_webcam/deps.py`,
  the same table the app's own dependency check uses. Change them there.
- The binary must not be stripped, it is a launcher with the app appended to it.
  The packaging scripts leave it alone, keep it that way.
- The icon is `packaging/phone-webcam.svg`, the desktop entry, AppStream
  metadata and man page are beside it.
- The binary needs a glibc at least as new as the symbols it was built with.
  Built in the Debian 13 devcontainer that is 2.38, which the packages declare.
  To support older systems, build on one of them and check the number again.
