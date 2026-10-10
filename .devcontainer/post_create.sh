#!/bin/bash

# Install dependency managers
pipx install uv

# install all dependencies
uv sync --all-extras

source "${UV_PROJECT_ENVIRONMENT:-.venv}/bin/activate"

# System packages: the libraries Qt WebEngine needs to open a window, and the
# phone and webcam tools. The lists live in phone_webcam/deps.py, so the app's
# gates and the container stay in sync. adb comes with scrcpy below, and
# v4l2loopback is left out on purpose, it is a kernel module and the container
# uses the host's.
PACKAGES=$(uv run python -c "
from phone_webcam import deps
keys = ['qt_libs', 'v4l2_ctl', 'v4l2loopback_ctl', 'ffmpeg', 'pkexec', 'modprobe']
print(' '.join(deps.packages_for(keys, 'debian')))
")
sudo apt-get update -qq
sudo apt-get install -y -qq $PACKAGES

# Tools for building the binary (scripts/build.sh) and the .deb and .rpm
# packages from it (scripts/build-deb.sh, scripts/build-rpm.sh). They are not
# needed to run or develop the app.
sudo apt-get install -y -qq patchelf ccache rpm rpmlint lintian \
  desktop-file-utils appstream

.devcontainer/install_scrcpy.sh

# run setup script

./scripts/setup_settings.sh
