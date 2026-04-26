#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

GRADLE_USER_HOME="${GRADLE_USER_HOME:-/tmp/gradle-cache}"
export GRADLE_USER_HOME

tasks=(
  ":app:lintDebug"
  ":app:testDebugUnitTest"
  ":app:assembleDebugAndroidTest"
  ":app:assembleDebug"
)

should_run_instrumentation=false
if [[ "${RUN_ANDROID_INSTRUMENTATION:-}" == "1" ]]; then
  should_run_instrumentation=true
elif command -v adb >/dev/null 2>&1; then
  device_count="$(
    adb devices |
      awk 'NR > 1 && $2 == "device" { count++ } END { print count + 0 }'
  )"
  if [[ "$device_count" -gt 0 ]]; then
    should_run_instrumentation=true
  fi
fi

if [[ "$should_run_instrumentation" == "true" ]]; then
  tasks+=(":app:connectedDebugAndroidTest")
else
  echo "No Android device/emulator detected; compiled instrumentation tests but skipped connectedDebugAndroidTest."
  echo "Set RUN_ANDROID_INSTRUMENTATION=1 when an emulator/device is available to require UI/integration tests."
fi

./gradlew --no-daemon --stacktrace "${tasks[@]}" "$@"
