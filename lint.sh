#!/bin/bash
set -e

MODE=${1:-all}
CI=${CI:-false}

FRONTEND_COMPOSE_FILE="docker-compose.ci.yml"
FRONTEND_SERVICE="jamarr_web_ci"

install_frontend_deps() {
    local install_cmd="npm install"
    if [[ "$CI" == "true" ]]; then
        install_cmd="npm ci"
    fi
    # Chain svelte-kit sync to generate .svelte-kit/tsconfig.json
    local full_cmd="${install_cmd} && npx svelte-kit sync"
    
    echo "📦 Installing frontend dependencies (${full_cmd})..."
    docker compose -f "${FRONTEND_COMPOSE_FILE}" run --rm "${FRONTEND_SERVICE}" /bin/sh -c "${full_cmd}"
}

run_svelte() {
    echo "🔍 Running Svelte Check..."
    if docker compose -f "${FRONTEND_COMPOSE_FILE}" run --rm "${FRONTEND_SERVICE}" npm run check; then
        echo "✅ Svelte Check Passed"
    else
        echo "❌ Svelte Check Failed"
        return 1
    fi
}

run_css() {
    echo "🔍 Running CSS Lint..."
    if docker compose -f "${FRONTEND_COMPOSE_FILE}" run --rm "${FRONTEND_SERVICE}" npm run lint:css; then
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
    install_frontend_deps || EXIT_CODE=1
    run_svelte || EXIT_CODE=1
elif [[ "$MODE" == "css" ]]; then
    install_frontend_deps || EXIT_CODE=1
    run_css || EXIT_CODE=1
elif [[ "$MODE" == "python" ]]; then
    run_python || EXIT_CODE=1
else
    # Run all
    install_frontend_deps || EXIT_CODE=1
    run_svelte || EXIT_CODE=1
    echo ""
    run_css || EXIT_CODE=1
    echo ""
    run_python || EXIT_CODE=1
fi

exit $EXIT_CODE
