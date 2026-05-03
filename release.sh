#!/usr/bin/env bash
# Tag main, wait for the Android release workflow to publish the APK, then
# rename the GitHub release. Usage: ./release.sh v1.2.3 "Release title"
set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
    shift
fi

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 [--dry-run] <version> <name>" >&2
    echo "Example: $0 v1.2.3 \"Cosmic Cassette\"" >&2
    echo "  --dry-run: validate, create local tag, poll for an EXISTING release," >&2
    echo "             skip pushing the tag and editing the release title." >&2
    exit 64
fi

VERSION="$1"
NAME="$2"

if ! [[ "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
    echo "Version must look like vMAJOR.MINOR.PATCH (got: $VERSION)" >&2
    exit 64
fi

if ! command -v gh >/dev/null 2>&1; then
    echo "gh CLI is required" >&2
    exit 69
fi

cd "$(dirname "$0")"

# 1. Working tree must be clean (skip in dry-run so the script itself can
#    be exercised before it has been committed).
if (( DRY_RUN == 0 )) && [[ -n "$(git status --porcelain)" ]]; then
    echo "Working tree has uncommitted changes. Commit or stash first." >&2
    exit 1
fi

# 2. Tag must not already exist locally or on the remote (real run only).
git fetch origin --tags --force --prune-tags --quiet || true
if (( DRY_RUN == 0 )); then
    if git rev-parse -q --verify "refs/tags/$VERSION" >/dev/null \
        || git ls-remote --exit-code --tags origin "$VERSION" >/dev/null 2>&1; then
        echo "Tag $VERSION already exists." >&2
        exit 1
    fi
fi

# 3. Switch to main and pull (skip in dry-run so the script can be tested
#    from any branch).
if (( DRY_RUN == 0 )); then
    git checkout main
    git pull --ff-only origin main
fi

COMMIT_SHA="$(git rev-parse HEAD)"
echo "Tagging $COMMIT_SHA as $VERSION (annotated, message=\"$NAME\")"

# 4. Annotated tag + push
if (( DRY_RUN )); then
    if ! git rev-parse -q --verify "refs/tags/$VERSION" >/dev/null; then
        git tag -a "$VERSION" -m "$NAME"
        echo "[dry-run] created local tag $VERSION (delete with: git tag -d $VERSION)"
    else
        echo "[dry-run] local tag $VERSION already present, leaving it alone"
    fi
    echo "[dry-run] would push: git push origin $VERSION"
else
    git tag -a "$VERSION" -m "$NAME"
    git push origin "$VERSION"
fi

REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
RUN_URL="https://github.com/$REPO/actions/workflows/android_release.yml"
echo "Pushed. Release workflow: $RUN_URL"

# 5. Poll until the release exists and the APK asset is attached.
# android_release.yml has a 15 min job timeout; allow 25 min wall-clock.
if (( DRY_RUN )); then
    echo "[dry-run] would poll: gh release view $VERSION (up to 25 min) until jamarr.apk attached"
else
    DEADLINE=$(( $(date +%s) + 1500 ))
    SLEEP_SECONDS=20
    echo "Waiting for release $VERSION with jamarr.apk asset..."
    while :; do
        if [[ $(date +%s) -gt $DEADLINE ]]; then
            echo "Timed out waiting for release. Check $RUN_URL" >&2
            exit 75
        fi

        if assets_json=$(gh release view "$VERSION" --json assets --jq '.assets[].name' 2>/dev/null); then
            if grep -qx 'jamarr.apk' <<<"$assets_json"; then
                break
            fi
            printf '.'
        else
            printf '.'
        fi
        sleep "$SLEEP_SECONDS"
    done
    echo
    echo "APK attached. Renaming release to: $NAME"
fi

# 6. Set the human-readable name. The workflow seeds title=tag, but it can
# get overwritten or shown as just the tag in some UIs; force it here.
if (( DRY_RUN )); then
    echo "[dry-run] would run: gh release edit $VERSION --title \"$NAME\""
else
    gh release edit "$VERSION" --title "$NAME"
fi

echo "Done."
if (( DRY_RUN )); then
    echo "[dry-run] complete. No tag pushed, no release edited."
else
    gh release view "$VERSION" --json tagName,name,url --jq '"Tag:  \(.tagName)\nName: \(.name)\nURL:  \(.url)"'
fi
