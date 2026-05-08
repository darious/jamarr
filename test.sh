#!/bin/bash
set -euo pipefail

# Use a dedicated compose project to avoid clashing with dev/prod containers
export COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-jamarr-test}
CI=${CI:-false}
PYTEST_MARK_EXPR=${PYTEST_MARK_EXPR:-"not slow"}
RUN_BACKEND_TESTS=true
RUN_TUI_TESTS=false
BACKEND_ARGS=("$@")
TUI_PASS=0
TUI_FAIL=0

if [ "$#" -eq 0 ]; then
    RUN_TUI_TESTS=true
else
    RUN_BACKEND_TESTS=false
    BACKEND_ARGS=()
    for arg in "$@"; do
        case "$arg" in
            tui|tui/*)
                RUN_TUI_TESTS=true
                ;;
            *)
                RUN_BACKEND_TESTS=true
                BACKEND_ARGS+=("$arg")
                ;;
        esac
    done
fi

cleanup() {
    local status=$?
    if [[ "$RUN_BACKEND_TESTS" != "true" ]]; then
        exit "$status"
    elif [[ "$CI" == "true" || "$status" -eq 0 ]]; then
        echo "🧹 Cleaning up test stack..."
        docker compose -f docker-compose.test.yml down --remove-orphans >/dev/null 2>&1 || true
        docker rm -f jamarr_test_db jamarr_test_runner >/dev/null 2>&1 || true
    else
        echo "⚠️  Test stack left running for debugging."
    fi
    exit "$status"
}
trap cleanup EXIT

if [[ "$RUN_BACKEND_TESTS" == "true" ]]; then
    echo "🧹 Cleaning up any existing test stack..."
    docker compose -f docker-compose.test.yml down --remove-orphans >/dev/null 2>&1 || true
    docker rm -f jamarr_test_db jamarr_test_runner >/dev/null 2>&1 || true

    # Build test runner image (shares main image)
    echo "🔨 Building test runner image..."
    docker compose -f docker-compose.test.yml build jamarr_test_runner

    echo "🚀 Starting Test Database on port 8109..."
    docker compose -f docker-compose.test.yml up -d jamarr_test_db

    # Wait for DB to be ready
    echo "⏳ Waiting for Test Database to be ready..."
    # Small grace period before first check
    sleep 1

    # Retrying for up to 30 seconds using pg_isready from the DB container
    DB_READY=0
    for i in {1..30}; do
        if docker compose -f docker-compose.test.yml exec -T jamarr_test_db pg_isready -h 127.0.0.1 -p 5432 -U jamarr_test >/dev/null 2>&1; then
            echo "✅ Test Database is ready!"
            DB_READY=1
            break
        fi
        echo "..."
        sleep 1
    done

    if [ "$DB_READY" -ne 1 ]; then
        echo "❌ Test Database did not become ready on port 8109."
        exit 1
    fi

    echo "🧪 Running backend tests..."
    # Run pytest inside the container with Test DB environment variables
    # We use set +e to capture the exit code
    set +e
    docker compose -f docker-compose.test.yml run --rm jamarr_test_runner \
        env PYTHONPATH=/app uv run pytest -m "$PYTEST_MARK_EXPR" "${BACKEND_ARGS[@]}"
    BACKEND_EXIT_CODE=$?
    set -e
else
    echo "⏭️  Skipping backend tests."
    BACKEND_EXIT_CODE=0
fi

TUI_EXIT_CODE=0
if [[ "$RUN_TUI_TESTS" == "true" ]]; then
    echo ""
    echo "🧪 Running TUI tests..."
    set +e
    UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/uv-cache} uv run --all-packages pytest tui/tests
    TUI_EXIT_CODE=$?
    set -e
    if [ "$TUI_EXIT_CODE" -eq 0 ]; then
        TUI_PASS=$((TUI_PASS + 1))
    else
        TUI_FAIL=$((TUI_FAIL + 1))
    fi
else
    echo "⏭️  Skipping TUI tests."
fi

if [ "$BACKEND_EXIT_CODE" -ne 0 ] || [ "$TUI_EXIT_CODE" -ne 0 ]; then
    EXIT_CODE=1
else
    EXIT_CODE=0
fi

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "✅ Tests Passed!"
    echo "TUI: pass ${TUI_PASS} fail ${TUI_FAIL}"
    exit 0
else
    echo ""
    echo "❌ Tests Failed!"
    echo "TUI: pass ${TUI_PASS} fail ${TUI_FAIL}"
    if [[ "$CI" != "true" ]]; then
        echo "⚠️  Test Database (jamarr_test_db) is LEFT RUNNING on port 8109 for debugging."
        echo "   You can inspect it with: docker compose -f docker-compose.test.yml logs"
        echo "   Or connect via: psql -h localhost -p 8109 -U jamarr_test -d jamarr_test"
    fi
    exit $EXIT_CODE
fi
