#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_SOURCE="${REPO_DIR}/systemd/posterpulse-journald.conf"
CONFIG_TARGET="/etc/systemd/journald.conf.d/posterpulse.conf"

install -d /var/log/journal /etc/systemd/journald.conf.d
if ! cmp -s "${CONFIG_SOURCE}" "${CONFIG_TARGET}"; then
    install -m 0644 "${CONFIG_SOURCE}" "${CONFIG_TARGET}"
    systemctl restart systemd-journald.service
fi
journalctl --flush
echo "Persistent system journal configured (100 MB size limit)."
