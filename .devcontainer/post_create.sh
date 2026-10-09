#!/bin/bash

# Install dependency managers
pipx install uv

# install all dependencies
uv sync --all-extras

source .venv/bin/activate

# run setup script

./scripts/setup_settings.sh
