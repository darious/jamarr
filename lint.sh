#!/bin/bash
set -e

MODE=${1:-all}
CI=${CI:-false}

FRONTEND_COMPOSE_FILE="docker-compose.ci.yml"
FRONTEND_SERVICE="jamarr_web_ci"

SVELTE_PASS=0
SVELTE_FAIL=0
CSS_PASS=0
CSS_FAIL=0
PYTHON_PASS=0
PYTHON_FAIL=0

install_frontend_deps() {
    local install_cmd="npm install"
    if [[ "$CI" == "true" ]]; then
        install_cmd="npm ci"
    fi
    # Chain svelte-kit sync to generate .svelte-kit/tsconfig.json
    local full_cmd="${install_cmd} && npx svelte-kit sync"
    
    echo "📦 Installing frontend dependencies (${full_cmd})..."
    if docker compose -f "${FRONTEND_COMPOSE_FILE}" run --rm "${FRONTEND_SERVICE}" /bin/sh -c "${full_cmd}"; then
        echo "✅ Frontend dependencies installed"
    else
        echo "❌ Frontend dependency install failed"
        return 1
    fi
}

run_svelte() {
    echo "🔍 Running Svelte Check..."
    if docker compose -f "${FRONTEND_COMPOSE_FILE}" run --rm "${FRONTEND_SERVICE}" npm run check; then
        echo "✅ Svelte Check Passed"
        SVELTE_PASS=$((SVELTE_PASS + 1))
    else
        echo "❌ Svelte Check Failed"
        SVELTE_FAIL=$((SVELTE_FAIL + 1))
        return 1
    fi
}

run_css() {
    echo "🔍 Running CSS Lint..."
    if docker compose -f "${FRONTEND_COMPOSE_FILE}" run --rm "${FRONTEND_SERVICE}" npm run lint:css; then
        echo "✅ CSS Lint Passed"
        CSS_PASS=$((CSS_PASS + 1))
    else
        echo "❌ CSS Lint Failed"
        CSS_FAIL=$((CSS_FAIL + 1))
        return 1
    fi
}

run_python() {
    echo "🔍 Running Python Check (ruff)..."
    if uv run ruff check .; then
        echo "✅ Python Check Passed"
        PYTHON_PASS=$((PYTHON_PASS + 1))
    else
        echo "❌ Python Check Failed"
        PYTHON_FAIL=$((PYTHON_FAIL + 1))
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

echo ""
echo "📋 Lint Summary"
echo "Svelte: pass ${SVELTE_PASS} fail ${SVELTE_FAIL}"
echo "CSS: pass ${CSS_PASS} fail ${CSS_FAIL}"
echo "Python: pass ${PYTHON_PASS} fail ${PYTHON_FAIL}"

exit $EXIT_CODE
