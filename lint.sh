#!/bin/bash
set -e

MODE=${1:-all}

run_svelte() {
    echo "🔍 Running Svelte Check..."
    if docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T jamarr_web npm run check; then
        echo "✅ Svelte Check Passed"
    else
        echo "❌ Svelte Check Failed"
        return 1
    fi
}

run_python() {
    echo "🔍 Running Python Check (ruff)..."
    if uv run ruff check .; then
        echo "✅ Python Check Passed"
    else
        echo "❌ Python Check Failed"
        return 1
    fi
}

EXIT_CODE=0

if [[ "$MODE" == "svelte" ]]; then
    run_svelte || EXIT_CODE=1
elif [[ "$MODE" == "python" ]]; then
    run_python || EXIT_CODE=1
else
    # Run both, but don't exit immediately on failure so we run both
    run_svelte || EXIT_CODE=1
    echo ""
    run_python || EXIT_CODE=1
fi

exit $EXIT_CODE
