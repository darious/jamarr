#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

GRADLE_USER_HOME="${GRADLE_USER_HOME:-/tmp/gradle-cache}"
export GRADLE_USER_HOME

# SDK and JDK live in different places depending on how the box was set up
# (system package vs. a user-local unpack), so probe the known locations rather
# than hard-coding one. An already-exported value always wins.
if [[ -z "${ANDROID_HOME:-}" ]]; then
  for candidate in "$HOME/Android/Sdk" /opt/android-sdk "$HOME/Android/sdk"; do
    if [[ -d "$candidate" ]]; then
      export ANDROID_HOME="$candidate"
      break
    fi
  done
fi
if [[ -z "${ANDROID_HOME:-}" ]]; then
  echo "No Android SDK found. Set ANDROID_HOME, or install one under ~/Android/Sdk." >&2
  exit 1
fi

# Gradle only reads JAVA_HOME; it will not fall back to a JDK that is merely on
# PATH-adjacent disk. AGP 9 / Gradle 9 need JDK 17+.
if [[ -z "${JAVA_HOME:-}" ]] && ! command -v java >/dev/null 2>&1; then
  for candidate in "$HOME/Android/jdk" /usr/lib/jvm/java-21-openjdk /usr/lib/jvm/java-17-openjdk; do
    if [[ -x "$candidate/bin/java" ]]; then
      export JAVA_HOME="$candidate"
      break
    fi
  done
fi
if [[ -z "${JAVA_HOME:-}" ]] && ! command -v java >/dev/null 2>&1; then
  echo "No JDK found. Set JAVA_HOME to a JDK 17+ install (see AGENTS.md)." >&2
  exit 1
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

# The SDK's adb is usually not on PATH, and falling back to "no device" there
# silently skips the instrumentation tests, so prefer the SDK copy.
adb_bin="$ANDROID_HOME/platform-tools/adb"
if [[ ! -x "$adb_bin" ]]; then
  adb_bin="$(command -v adb || true)"
fi

should_run_instrumentation=false
if [[ "${RUN_ANDROID_INSTRUMENTATION:-}" == "1" ]]; then
  should_run_instrumentation=true
elif [[ -n "$adb_bin" ]]; then
  device_count="$(
    "$adb_bin" devices |
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
