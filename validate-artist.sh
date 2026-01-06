#!/bin/bash
# Helper script to run the pipeline validation tool
#
# Usage:
#   ./validate-artist.sh <mbid> [options]
#
# Examples:
#   ./validate-artist.sh b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d --all
#   ./validate-artist.sh b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d --all --missing-only
#   ./validate-artist.sh <mbid> --metadata --artwork --bio

set -e

# Load .env file if it exists
if [ -f .env ]; then
    echo "Loading environment variables from .env..."
    export $(grep -v '^#' .env | xargs)
fi

# Set PYTHONPATH
export PYTHONPATH=/root/code/jamarr

# Run validation
uv run python -m app.scanner.pipeline.validate_artist "$@"
