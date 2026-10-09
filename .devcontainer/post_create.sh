#!/bin/bash

# Install dependency managers
pipx install uv

# install all dependencies
uv sync --all-extras

source "${UV_PROJECT_ENVIRONMENT:-.venv}/bin/activate"

# System libraries Qt WebEngine needs to open a window. The list lives in
# phone_webcam/deps.py, so the app's gate and the container stay in sync.
sudo apt-get update -qq
sudo apt-get install -y -qq $(uv run python -c \
  "from phone_webcam import deps; print(' '.join(deps.PACKAGES['qt_libs']['debian']))")

# run setup script

./scripts/setup_settings.sh
