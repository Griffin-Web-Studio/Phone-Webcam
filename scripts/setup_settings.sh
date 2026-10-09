#!/bin/bash
set -e

# Install precommit hooks
pre-commit install
pre-commit install --hook-type commit-msg
