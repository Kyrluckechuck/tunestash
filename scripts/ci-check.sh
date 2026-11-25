#!/usr/bin/env bash
# Reproduce the CI "Backend (lint + tests)" job locally, on a clean copy of the
# committed tree, so failures show up before pushing.
#
#   scripts/ci-check.sh               check HEAD (what CI will see after a push)
#   scripts/ci-check.sh --worktree    check the working tree (tracked changes plus
#                                     untracked, non-ignored files) without
#                                     committing or touching your index
#   scripts/ci-check.sh --frontend    also run frontend lint + tests in node:24
#
# Why a clean copy: isort decides which packages are first-party from the
# directory layout. Running it inside the live /app mount (or with the root
# pyproject.toml) disagrees with CI, so the tree is exported with `git archive`
# into a fresh temp dir inside the running `web` container.
#
# CI has no Valkey/Redis, so the `valkey` host does not resolve there. The Celery
# broker is pointed at an unresolvable host so tests that accidentally need a
# broker fail here too, with the same error as in CI.
#
# Exits non-zero if any step fails.
set -uo pipefail

MODE="HEAD"
FRONTEND=0
for arg in "$@"; do
    case "$arg" in
        --worktree) MODE="worktree" ;;
        --frontend) FRONTEND=1 ;;
        -h | --help)
            sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "unknown argument: $arg (see --help)" >&2
            exit 2
            ;;
    esac
done

ROOT=$(git rev-parse --show-toplevel) || exit 2
cd "$ROOT" || exit 2

if ! docker compose ps --status running --services 2>/dev/null | grep -qx web; then
    echo "The 'web' container is not running. Start it with: make dev-container" >&2
    exit 2
fi
dc() { docker compose exec -T web "$@"; }

TMP_INDEX=""
REMOTE_DIR=""
FE_DIR=""
LOG_DIR=$(mktemp -d)
cleanup() {
    [ -n "$REMOTE_DIR" ] && dc rm -rf "$REMOTE_DIR" >/dev/null 2>&1
    [ -n "$FE_DIR" ] && rm -rf "$FE_DIR"
    [ -n "$TMP_INDEX" ] && rm -f "$TMP_INDEX"
    rm -rf "$LOG_DIR"
}
trap cleanup EXIT

if [ "$MODE" = "worktree" ]; then
    # A throwaway index lets untracked files be included without staging them.
    TMP_INDEX=$(mktemp -u)
    GIT_INDEX_FILE="$TMP_INDEX" git read-tree HEAD
    GIT_INDEX_FILE="$TMP_INDEX" git add -A
    TREE=$(GIT_INDEX_FILE="$TMP_INDEX" git write-tree)
    LABEL="working tree (tree $(echo "$TREE" | cut -c1-10))"
else
    TREE=$(git rev-parse HEAD)
    LABEL="HEAD ($(git rev-parse --short HEAD))"
fi
echo "=== ci-check: $LABEL ==="

RESULTS=()
FAILED=0
record() { # name status seconds
    RESULTS+=("$(printf '%-16s %-5s %4ss' "$1" "$2" "$3")")
    [ "$2" = "FAIL" ] && FAILED=1
}

REMOTE_DIR=$(git archive "$TREE" -- . ':!frontend' ':!queuetip-frontend' |
    dc bash -c 'd=$(mktemp -d /tmp/ci-check.XXXXXX) && tar -x -C "$d" && echo "$d"')
if [ -z "$REMOTE_DIR" ]; then
    echo "Failed to export the tree into the web container" >&2
    exit 2
fi

# Same commands as `make lint-api`; the Makefile recipe also runs them in
# parallel. bandit is informational there (its failure is ignored).
read -r -d '' LINT <<'EOF'
cd "$1" || exit 2
export NO_COLOR=1 TERM=dumb
mkdir -p .lint-tmp reports
declare -A pid
start() { local n=$1; shift; ( "$@" ) >".lint-tmp/$n.log" 2>&1 & pid[$n]=$!; }
start flake8 bash -c 'cd api && python -m flake8'
start black bash -c 'cd api && python -m black --check --diff .'
start isort bash -c 'cd api && python -m isort --check-only --diff .'
start mypy bash -c 'cd api && python -m mypy src/ --config-file ../pyproject.toml'
start bandit bash -c 'cd api && python -m bandit -q -r src/ library_manager/ -f json -o ../reports/bandit-report.json'
start pylint bash -c 'cd api && python -m pylint src/ library_manager/ --rcfile ../pyproject.toml'
fail=0
for n in flake8 black isort mypy bandit pylint; do
    wait "${pid[$n]}"; rc=$?
    if [ "$n" = bandit ] || [ $rc -eq 0 ]; then
        echo "lint:$n ok"
    else
        echo "lint:$n FAILED"; cat ".lint-tmp/$n.log"; fail=$((fail + 1))
    fi
done
exit $fail
EOF

# Same command as `make test-api` with CI's env. TMPDIR/HOME mirror ci.yml; the
# broker URL is deliberately unreachable.
read -r -d '' TESTS <<'EOF'
cd "$1/api" || exit 2
mkdir -p /tmp/pytest-ci /tmp/pytest-ci-home
export DJANGO_SETTINGS_MODULE=test_settings TMPDIR=/tmp/pytest-ci HOME=/tmp/pytest-ci-home
export CELERY_BROKER_URL=redis://valkey.invalid:6379/0
python -m pytest tests/ src/tests/ -v -n 2 --cov=src --cov=library_manager --cov-report=term-missing
EOF

step() { # name logfile -- command...
    local name=$1 log=$2 start rc
    shift 2
    start=$(date +%s)
    "$@" >"$log" 2>&1
    rc=$?
    if [ $rc -eq 0 ]; then
        record "$name" PASS $(($(date +%s) - start))
    else
        record "$name" FAIL $(($(date +%s) - start))
        echo "----- $name output (tail) -----"
        tail -n 120 "$log"
    fi
}

echo "Running backend lint (flake8, black, isort, mypy, bandit, pylint)..."
step "backend lint" "$LOG_DIR/lint.log" dc env -u PYTHONPATH bash -c "$LINT" _ "$REMOTE_DIR"
grep -E '^lint:' "$LOG_DIR/lint.log" | sed 's/^/  /'

echo "Running backend tests (broker unreachable, like CI)..."
step "backend tests" "$LOG_DIR/tests.log" dc env -u PYTHONPATH bash -c "$TESTS" _ "$REMOTE_DIR"
grep -E '^(=+ .*(passed|failed|error).*=+|TOTAL )' "$LOG_DIR/tests.log" | sed 's/^/  /'

if [ "$FRONTEND" -eq 1 ]; then
    FE_DIR=$(mktemp -d)
    git archive "$TREE" frontend | tar -x -C "$FE_DIR"
    echo "Running frontend lint + tests (node:24)..."
    step "frontend" "$LOG_DIR/frontend.log" docker run --rm --user "$(id -u):$(id -g)" \
        -e HOME=/tmp -e CI=1 -v "$FE_DIR/frontend:/work" -w /work node:24 \
        sh -c 'yarn install --frozen-lockfile && yarn lint && yarn test:run'
fi

echo
echo "=== ci-check summary: $LABEL ==="
printf '%s\n' "${RESULTS[@]}"
if [ "$FAILED" -ne 0 ]; then
    echo "RESULT: FAIL"
    exit 1
fi
echo "RESULT: PASS"
