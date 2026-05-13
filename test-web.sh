#!/bin/bash
# Frontend test runner for /web (Svelte + Vite + Vitest).
#
# Modes (positional arg):
#   all     — install + check + lint + unit + build (default)
#   unit    — vitest run (extra args forwarded to vitest)
#   check   — svelte-check only
#   lint    — stylelint only
#   build   — vite build only
#   deps    — install deps and svelte-kit sync, then exit
#
# Env:
#   CI=true       use `npm ci` instead of `npm install`
#   LOCAL=true    run directly on host (no Docker; requires node 22+)
set -e

MODE=${1:-all}
shift || true
EXTRA_ARGS=("$@")

CI=${CI:-false}
LOCAL=${LOCAL:-false}

FRONTEND_COMPOSE_FILE="docker-compose.ci.yml"
FRONTEND_SERVICE="jamarr_web_ci"

DEPS_PASS=0
DEPS_FAIL=0
CHECK_PASS=0
CHECK_FAIL=0
LINT_PASS=0
LINT_FAIL=0
UNIT_PASS=0
UNIT_FAIL=0
BUILD_PASS=0
BUILD_FAIL=0

run_in_env() {
    if [[ "$LOCAL" == "true" ]]; then
        ( cd web && "$@" )
    else
        docker compose -f "${FRONTEND_COMPOSE_FILE}" run --rm "${FRONTEND_SERVICE}" "$@"
    fi
}

install_deps() {
    local install_cmd="npm install"
    if [[ "$CI" == "true" ]]; then
        install_cmd="npm ci"
    fi
    echo "📦 Installing frontend dependencies (${install_cmd} + svelte-kit sync)..."
    if [[ "$LOCAL" == "true" ]]; then
        if ( cd web && $install_cmd && npx svelte-kit sync ); then
            echo "✅ Dependencies installed"
            DEPS_PASS=$((DEPS_PASS + 1))
        else
            echo "❌ Dependency install failed"
            DEPS_FAIL=$((DEPS_FAIL + 1))
            return 1
        fi
    else
        if docker compose -f "${FRONTEND_COMPOSE_FILE}" run --rm "${FRONTEND_SERVICE}" \
                /bin/sh -c "${install_cmd} && npx svelte-kit sync"; then
            echo "✅ Dependencies installed"
            DEPS_PASS=$((DEPS_PASS + 1))
        else
            echo "❌ Dependency install failed"
            DEPS_FAIL=$((DEPS_FAIL + 1))
            return 1
        fi
    fi
}

run_check() {
    echo "🔍 Running svelte-check..."
    if run_in_env npm run check; then
        echo "✅ svelte-check passed"
        CHECK_PASS=$((CHECK_PASS + 1))
    else
        echo "❌ svelte-check failed"
        CHECK_FAIL=$((CHECK_FAIL + 1))
        return 1
    fi
}

run_lint() {
    echo "🔍 Running stylelint..."
    if run_in_env npm run lint:css; then
        echo "✅ stylelint passed"
        LINT_PASS=$((LINT_PASS + 1))
    else
        echo "❌ stylelint failed"
        LINT_FAIL=$((LINT_FAIL + 1))
        return 1
    fi
}

run_unit() {
    echo "🧪 Running vitest..."
    set +e
    if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
        run_in_env npx vitest run "${EXTRA_ARGS[@]}"
    else
        run_in_env npm test
    fi
    local rc=$?
    set -e
    if [[ $rc -eq 0 ]]; then
        echo "✅ vitest passed"
        UNIT_PASS=$((UNIT_PASS + 1))
    else
        echo "❌ vitest failed"
        UNIT_FAIL=$((UNIT_FAIL + 1))
        return 1
    fi
}

run_build() {
    echo "🏗️  Running vite build..."
    if run_in_env npm run build; then
        echo "✅ vite build passed"
        BUILD_PASS=$((BUILD_PASS + 1))
    else
        echo "❌ vite build failed"
        BUILD_FAIL=$((BUILD_FAIL + 1))
        return 1
    fi
}

EXIT_CODE=0

case "$MODE" in
    deps)
        install_deps || EXIT_CODE=1
        ;;
    check)
        install_deps || EXIT_CODE=1
        run_check || EXIT_CODE=1
        ;;
    lint)
        install_deps || EXIT_CODE=1
        run_lint || EXIT_CODE=1
        ;;
    unit)
        install_deps || EXIT_CODE=1
        run_unit || EXIT_CODE=1
        ;;
    build)
        install_deps || EXIT_CODE=1
        run_build || EXIT_CODE=1
        ;;
    all|"")
        install_deps || EXIT_CODE=1
        echo ""
        run_check  || EXIT_CODE=1
        echo ""
        run_lint   || EXIT_CODE=1
        echo ""
        run_unit   || EXIT_CODE=1
        echo ""
        run_build  || EXIT_CODE=1
        ;;
    *)
        echo "Unknown mode: $MODE"
        echo "Usage: $0 [all|unit|check|lint|build|deps] [-- vitest-args]"
        exit 2
        ;;
esac

echo ""
echo "📋 Frontend Test Summary"
echo "Deps:        pass ${DEPS_PASS}  fail ${DEPS_FAIL}"
echo "svelte-check: pass ${CHECK_PASS}  fail ${CHECK_FAIL}"
echo "stylelint:   pass ${LINT_PASS}  fail ${LINT_FAIL}"
echo "vitest:      pass ${UNIT_PASS}  fail ${UNIT_FAIL}"
echo "vite build:  pass ${BUILD_PASS}  fail ${BUILD_FAIL}"

if [[ $EXIT_CODE -eq 0 ]]; then
    echo ""
    echo "✅ Frontend Tests Passed!"
else
    echo ""
    echo "❌ Frontend Tests Failed!"
fi

exit $EXIT_CODE
