#!/bin/bash
set -e

# Sync configuration and tests
docker cp pyproject.toml jamarr:/app/pyproject.toml
docker cp tests jamarr:/app

# Run pytest inside the container
# Pass all arguments to the script through to pytest
docker compose exec jamarr env PYTHONPATH=/app uv run pytest "$@"
