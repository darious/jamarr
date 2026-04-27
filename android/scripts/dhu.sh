#!/usr/bin/env bash
# Run the Jamarr Android Auto build against the Desktop Head Unit.
#
# Prerequisites:
#   - Android SDK installed; ANDROID_SDK_ROOT or ANDROID_HOME set, or default
#     ~/Android/Sdk used.
#   - DHU package installed via SDK Manager: "Android Auto Desktop Head Unit".
#   - Phone connected over USB with adb authorised.
#   - Phone has Android Auto app installed and Developer Mode enabled
#     (Android Auto > settings > version banner tapped 10x > head-unit-server).
#
# What it does:
#   1. Verifies adb sees a device.
#   2. Forwards tcp:5277 (the DHU socket).
#   3. Starts the head-unit-server intent on the phone.
#   4. Launches the desktop-head-unit binary.
#   5. On Ctrl-C, kills the head-unit-server intent and removes the forward.

set -euo pipefail

SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Android/Sdk}}"
DHU_BIN="$SDK_ROOT/extras/google/auto/desktop-head-unit"

if ! command -v adb >/dev/null 2>&1; then
    echo "error: adb not found in PATH" >&2
    exit 1
fi
if [ ! -x "$DHU_BIN" ]; then
    echo "error: DHU binary not found at $DHU_BIN" >&2
    echo "       install via Android Studio > SDK Manager > SDK Tools >" >&2
    echo "       'Android Auto Desktop Head Unit'." >&2
    exit 1
fi

DEVICE_COUNT="$(adb devices | awk 'NR>1 && $2=="device"' | wc -l)"
if [ "$DEVICE_COUNT" -eq 0 ]; then
    echo "error: no adb devices attached" >&2
    exit 1
fi

cleanup() {
    echo
    adb forward --remove tcp:5277 >/dev/null 2>&1 || true
}
trap cleanup EXIT

adb forward tcp:5277 tcp:5277

# Try a few known component paths for the head-unit server. The class name has
# moved between AA versions, so we try each in turn and accept the first that
# launches without "Activity class ... does not exist".
CANDIDATES=(
    "com.google.android.projection.gearhead/com.google.android.projection.gearhead.companion.headunitserver.HeadUnitServerService"
    "com.google.android.projection.gearhead/.companion.headunitserver.HeadUnitServerService"
    "com.google.android.projection.gearhead/com.google.android.gearhead.companion.headunitserver.HeadUnitServerService"
)

started=0
for component in "${CANDIDATES[@]}"; do
    out="$(adb shell am start-foreground-service -n "$component" 2>&1 || true)"
    if ! grep -qiE "does not exist|not found|error type" <<<"$out"; then
        echo "head-unit-server started ($component)"
        started=1
        break
    fi
done

if [ "$started" -eq 0 ]; then
    cat >&2 <<'EOF'
warning: could not auto-start head-unit-server. Start it manually on the phone:

  Android Auto -> ⋮ menu -> Developer settings -> "Start head unit server"

  (If you don't see Developer settings, scroll to the bottom of Android Auto
  settings and tap the version banner 10 times to unlock it.)

Press Enter once it's running...
EOF
    read -r _
fi

sleep 1
echo "launching DHU..."
exec "$DHU_BIN"
