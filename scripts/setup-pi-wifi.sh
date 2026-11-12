#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if ! command -v nmcli >/dev/null 2>&1 || ! systemctl is-active --quiet NetworkManager; then
    echo "Warning: Wi-Fi recovery not installed; an active NetworkManager is required." >&2
    exit 0
fi
install -d /usr/local/libexec
install -m 0755 "${SCRIPT_DIR}/pi-wifi-watchdog.sh" /usr/local/libexec/posterpulse-wifi-watchdog
install -m 0644 "${REPO_DIR}/systemd/posterpulse-wifi.service" /etc/systemd/system/posterpulse-wifi.service
install -m 0644 "${REPO_DIR}/systemd/posterpulse-wifi.timer" /etc/systemd/system/posterpulse-wifi.timer
systemctl daemon-reload
systemctl enable --now posterpulse-wifi.timer
echo "Wi-Fi recovery enabled: cycle the radio after five minutes disconnected."
