#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

GRADLE_USER_HOME="${GRADLE_USER_HOME:-/tmp/gradle-cache}"
export GRADLE_USER_HOME

if ! command -v adb >/dev/null 2>&1; then
  echo "adb is not installed or is not on PATH." >&2
  exit 1
fi

device_count="$(
  adb devices |
    awk 'NR > 1 && $2 == "device" { count++ } END { print count + 0 }'
)"

if [ "$device_count" -eq 0 ]; then
  echo "No authorized Android device found." >&2
  echo "Connect a phone, enable USB debugging, and accept the authorization prompt." >&2
  adb devices -l >&2
  exit 1
fi

if [ "$device_count" -gt 1 ]; then
  echo "Multiple Android devices are connected. Set ANDROID_SERIAL and retry." >&2
  adb devices -l >&2
  exit 1
fi

./gradlew :app:installDebug "$@"
