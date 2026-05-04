#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

GRADLE_USER_HOME="${GRADLE_USER_HOME:-/tmp/gradle-cache}"
export GRADLE_USER_HOME

if [ -z "${JAVA_HOME:-}" ]; then
  if command -v java >/dev/null 2>&1; then
    JAVA_HOME="$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")"
  fi
fi
export JAVA_HOME

if [ $# -gt 0 ]; then
  ./gradlew "$@"
  exit 0
fi

has_device=false
if command -v adb >/dev/null 2>&1; then
  device_count="$(
    adb devices 2>/dev/null |
      awk 'NR > 1 && $2 == "device" { count++ } END { print count + 0 }'
  )"
  if [ "$device_count" -gt 0 ]; then
    has_device=true
    if [ "$device_count" -gt 1 ]; then
      echo "Multiple Android devices connected. Set ANDROID_SERIAL and retry." >&2
      adb devices -l >&2
      exit 1
    fi
  fi
fi

if $has_device; then
  ./gradlew :app:installDebug
else
  echo "No device connected — running assembleDebug (build only)." >&2
  ./gradlew :app:assembleDebug
fi
