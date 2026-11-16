#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

STATE_DIR="${STATE_DIR:-/run/posterpulse-wifi}"
RECOVERY_DIR="${RECOVERY_DIR:-/var/lib/posterpulse-wifi}"
STATE_FILE="${STATE_DIR}/disconnected"
STATUS_FILE="${STATE_DIR}/status"
RESTORE_FILE="${RECOVERY_DIR}/restore-pending"
mkdir -p "${STATE_DIR}" "${RECOVERY_DIR}"

report_status() {
    local status="$1" message="$2" previous=""
    if [[ -f "${STATUS_FILE}" ]]; then
        read -r previous < "${STATUS_FILE}" || true
    fi
    if [[ "${previous}" != "${status}" ]]; then
        echo "${message}"
        printf '%s\n' "${status}" > "${STATUS_FILE}"
    fi
}

enable_wifi() {
    nmcli --wait 10 radio wifi on
    local restored_radio
    restored_radio="$(nmcli --wait 10 radio wifi)"
    if [[ "${restored_radio}" != "enabled" ]]; then
        echo "Wi-Fi radio is still disabled; restoration remains pending." >&2
        return 1
    fi
    rm -f "${RESTORE_FILE}"
}

if [[ -f "${RESTORE_FILE}" ]]; then
    echo "Retrying pending Wi-Fi radio restoration."
    enable_wifi
fi

if ! radio="$(nmcli --wait 10 radio wifi)"; then
    rm -f "${STATE_FILE}"
    report_status "radio-error" "Could not read Wi-Fi radio state; no recovery attempted." >&2
    exit 1
fi
if [[ "${radio}" != "enabled" ]]; then
    rm -f "${STATE_FILE}"
    report_status "radio-disabled" "Wi-Fi radio is disabled; recovery skipped."
    exit 0
fi

if ! devices="$(nmcli --wait 10 -t -f DEVICE,TYPE,STATE device status)"; then
    rm -f "${STATE_FILE}"
    report_status "device-error" "Could not read Wi-Fi device state; no recovery attempted." >&2
    exit 1
fi
has_wifi=false
while IFS=: read -r device type state; do
    [[ "${type}" == "wifi" ]] || continue
    if [[ "${state}" == connected* ]]; then
        rm -f "${STATE_FILE}"
        report_status "connected" "Wi-Fi is connected."
        exit 0
    fi
    if [[ "${state}" != "unmanaged" ]]; then
        has_wifi=true
    fi
done <<< "${devices}"
if [[ "${has_wifi}" != true ]]; then
    rm -f "${STATE_FILE}"
    report_status "no-managed-wifi" "No managed Wi-Fi device found; recovery skipped."
    exit 0
fi

report_status "disconnected" "Wi-Fi is disconnected; waiting five minutes before recovery."

# Uptime avoids clock corrections; a missed monitoring interval restarts the wait.
read -r uptime _ < /proc/uptime
now="${uptime%%.*}"
started="${now}"
if [[ -f "${STATE_FILE}" ]]; then
    if read -r previous_started previous_check < "${STATE_FILE}" \
        && [[ "${previous_started}" =~ ^[0-9]+$ && "${previous_check}" =~ ^[0-9]+$ ]] \
        && (( previous_started <= previous_check && previous_check <= now && now - previous_check <= 90 )); then
        started="${previous_started}"
    else
        echo "Wi-Fi monitoring state is stale or invalid; restarting the five-minute wait."
    fi
fi
printf '%s %s\n' "${started}" "${now}" > "${STATE_FILE}"
if (( now - started < 300 )); then
    exit 0
fi

# Restore the radio even if disabling it or the intervening wait fails.
restore_needed=true
restore_wifi() {
    if [[ "${restore_needed}" == true ]]; then
        echo "Restoring Wi-Fi radio after interrupted recovery."
        enable_wifi
    fi
}
trap restore_wifi EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
echo "Wi-Fi disconnected for five minutes; cycling the radio to reconnect."
printf '%s %s\n' "${now}" "${now}" > "${STATE_FILE}"
touch "${RESTORE_FILE}"
nmcli --wait 10 radio wifi off
sleep 5
enable_wifi
restore_needed=false
rm -f "${STATE_FILE}"
echo "Wi-Fi radio enabled; NetworkManager will reconnect saved autoconnect networks."
