#!/usr/bin/env bash
# Boot (or stop) the headless emulator the instrumentation tests run on.
#
#   ./scripts/emulator.sh start    boot and wait for sys.boot_completed
#   ./scripts/emulator.sh stop     kill the AVD this script started
#   ./scripts/emulator.sh status   exit 0 if a device is attached
#
# The dev box has no DISPLAY, so the AVD runs with -no-window and software GL.
# The AVD is created on first use; the config avdmanager writes needs three
# fixes before it will boot usefully, which are applied here rather than left
# as a manual step.
set -euo pipefail

cd "$(dirname "$0")/.."

AVD_NAME="${AVD_NAME:-jamarr36}"
SYSTEM_IMAGE="${SYSTEM_IMAGE:-system-images;android-36;google_apis;x86_64}"
DEVICE_PROFILE="${DEVICE_PROFILE:-pixel_6}"
BOOT_TIMEOUT_SECONDS="${BOOT_TIMEOUT_SECONDS:-300}"

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

# The SDK's adb is normally not on PATH; prefer it over anything that is.
ADB="$ANDROID_HOME/platform-tools/adb"
[[ -x "$ADB" ]] || ADB="$(command -v adb || true)"
if [[ -z "$ADB" ]]; then
  echo "No adb found under $ANDROID_HOME/platform-tools or on PATH." >&2
  exit 1
fi

EMULATOR_BIN="$ANDROID_HOME/emulator/emulator"
AVDMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager"
PID_FILE="${TMPDIR:-/tmp}/jamarr-emulator-$AVD_NAME.pid"
LOG_FILE="${TMPDIR:-/tmp}/jamarr-emulator-$AVD_NAME.log"

device_attached() {
  "$ADB" devices | awk 'NR > 1 && $2 == "device" { found = 1 } END { exit !found }'
}

create_avd() {
  if "$EMULATOR_BIN" -list-avds 2>/dev/null | grep -qx "$AVD_NAME"; then
    return 0
  fi
  if [[ ! -x "$AVDMANAGER" ]]; then
    echo "AVD '$AVD_NAME' is missing and avdmanager was not found at $AVDMANAGER." >&2
    echo "Install cmdline-tools and the $SYSTEM_IMAGE package (see AGENTS.md)." >&2
    exit 1
  fi
  echo "Creating AVD $AVD_NAME ($SYSTEM_IMAGE, $DEVICE_PROFILE)…"
  # Prints a harmless "Could not load devices from devices.xml" and still
  # applies the profile.
  echo no | "$AVDMANAGER" create avd \
    -n "$AVD_NAME" -k "$SYSTEM_IMAGE" -d "$DEVICE_PROFILE" >/dev/null || true

  local config="$HOME/.android/avd/$AVD_NAME.avd/config.ini"
  if [[ ! -f "$config" ]]; then
    echo "AVD creation did not produce $config." >&2
    exit 1
  fi
  # avdmanager writes the literal "<build>" for the id/name and leaves the GPU
  # off, and `adb shell input text` needs a hardware keyboard.
  python3 - "$config" "$AVD_NAME" <<'PY'
import sys

path, name = sys.argv[1], sys.argv[2]
overrides = {
    "avd.id": name,
    "avd.name": name,
    "hw.gpu.enabled": "yes",
    "hw.gpu.mode": "swiftshader_indirect",
    "hw.keyboard": "yes",
}
lines, seen = [], set()
with open(path) as handle:
    for line in handle:
        key = line.split("=", 1)[0].strip()
        if key in overrides:
            lines.append(f"{key}={overrides[key]}\n")
            seen.add(key)
        else:
            lines.append(line)
lines.extend(f"{k}={v}\n" for k, v in overrides.items() if k not in seen)
with open(path, "w") as handle:
    handle.writelines(lines)
PY
}

start() {
  if device_attached; then
    echo "A device is already attached; leaving it alone."
    return 0
  fi
  if [[ ! -x "$EMULATOR_BIN" ]]; then
    echo "No emulator binary at $EMULATOR_BIN. Install the SDK 'emulator' package." >&2
    exit 1
  fi
  create_avd

  # KVM is granted through a POSIX ACL on this box rather than group
  # membership, so check access directly rather than via `id`.
  if [[ ! -r /dev/kvm || ! -w /dev/kvm ]]; then
    echo "Warning: /dev/kvm is not accessible; the emulator will be very slow." >&2
  fi

  echo "Booting $AVD_NAME headless (log: $LOG_FILE)…"
  "$EMULATOR_BIN" -avd "$AVD_NAME" -no-window -no-audio -no-boot-anim \
    -gpu swiftshader_indirect >"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"

  "$ADB" start-server >/dev/null 2>&1 || true
  local waited=0
  until [[ "$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; do
    if [[ "$waited" -ge "$BOOT_TIMEOUT_SECONDS" ]]; then
      echo "Emulator did not finish booting within ${BOOT_TIMEOUT_SECONDS}s. Tail of $LOG_FILE:" >&2
      tail -20 "$LOG_FILE" >&2 || true
      exit 1
    fi
    sleep 5
    waited=$((waited + 5))
  done
  echo "Emulator ready after ${waited}s."
}

stop() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "Stopping emulator (pid $pid)…"
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
  else
    "$ADB" emu kill >/dev/null 2>&1 || true
  fi
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  status) device_attached && echo "device attached" || { echo "no device"; exit 1; } ;;
  *)
    echo "usage: $0 [start|stop|status]" >&2
    exit 2
    ;;
esac
