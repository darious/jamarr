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

run_css() {
    echo "🔍 Running CSS Lint..."
    if docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T jamarr_web npm run lint:css; then
        echo "✅ CSS Lint Passed"
    else
        echo "❌ CSS Lint Failed"
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
elif [[ "$MODE" == "css" ]]; then
    run_css || EXIT_CODE=1
elif [[ "$MODE" == "python" ]]; then
    run_python || EXIT_CODE=1
else
    # Run all
    run_svelte || EXIT_CODE=1
    echo ""
    run_css || EXIT_CODE=1
    echo ""
    run_python || EXIT_CODE=1
fi

exit $EXIT_CODE
