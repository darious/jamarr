#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

GRADLE_USER_HOME="${GRADLE_USER_HOME:-/tmp/gradle-cache}"
export GRADLE_USER_HOME

if [[ -z "${ANDROID_HOME:-}" && -d /opt/android-sdk ]]; then
  export ANDROID_HOME=/opt/android-sdk
fi

# On low-memory boxes the default 2 GiB gradle heap plus the kotlin compile
# daemon gets the JVM OOM-killed; cap heaps and parallelism when available
# memory is under 4 GiB. Explicit flags passed to this script still win.
low_mem_args=()
mem_available_mb="$(awk '/MemAvailable/ { print int($2 / 1024) }' /proc/meminfo 2>/dev/null || echo 0)"
if [[ "$mem_available_mb" -gt 0 && "$mem_available_mb" -lt 4096 ]]; then
  echo "Low memory (${mem_available_mb} MiB available); capping gradle/kotlin heaps and workers."
  low_mem_args=(
    "-Dorg.gradle.jvmargs=-Xmx1280m"
    "-Dkotlin.daemon.jvmargs=-Xmx1024m"
    "--max-workers=2"
  )
fi

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

./gradlew --no-daemon --stacktrace "${low_mem_args[@]}" "${tasks[@]}" "$@"
