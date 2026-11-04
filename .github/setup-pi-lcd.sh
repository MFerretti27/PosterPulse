#!/usr/bin/env bash
# PosterPulse setup for Raspberry Pi OS with an LCD/HDMI display.
# Usage from a development computer:
#   bash .github/setup-pi-lcd.sh -ip=10.0.0.119 -user=matt
# Usage locally on the Pi:
#   sudo bash .github/setup-pi-lcd.sh --local

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_IP=""
REMOTE_USER="pi"
SSH_PORT="22"
LOCAL_MODE=false

show_help() {
    cat <<EOF
Usage:
  Remote setup from a Mac/Linux computer:
    bash .github/setup-pi-lcd.sh -ip=<PI_IP_ADDRESS> [-user=pi] [-port=22]

  Local setup directly on a Raspberry Pi with a desktop environment:
    sudo bash .github/setup-pi-lcd.sh --local

Options:
  -ip=IP, --ip=IP, -ip IP       Target Pi IP address or hostname
  -user=USER, -u=USER           SSH username (default: pi)
  -port=PORT, -p=PORT           SSH port (default: 22)
  --local, -l                   Configure this Pi directly
  -h, --help                    Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -ip=*|--ip=*) TARGET_IP="${1#*=}"; shift ;;
        -ip|--ip)
            [[ $# -ge 2 && ! "$2" =~ ^- ]] || { echo "Error: -ip requires an address." >&2; exit 1; }
            TARGET_IP="$2"; shift 2 ;;
        -user=*|--user=*|-u=*|--u=*) REMOTE_USER="${1#*=}"; shift ;;
        -user|--user|-u)
            [[ $# -ge 2 && ! "$2" =~ ^- ]] || { echo "Error: -user requires a username." >&2; exit 1; }
            REMOTE_USER="$2"; shift 2 ;;
        -port=*|--port=*|-p=*|--p=*) SSH_PORT="${1#*=}"; shift ;;
        -port|--port|-p)
            [[ $# -ge 2 && ! "$2" =~ ^- ]] || { echo "Error: -port requires a number." >&2; exit 1; }
            SSH_PORT="$2"; shift 2 ;;
        --local|-l) LOCAL_MODE=true; shift ;;
        -h|--help) show_help; exit 0 ;;
        *) echo "Error: Unknown argument: $1" >&2; show_help; exit 1 ;;
    esac
done

if [[ -n "$TARGET_IP" ]]; then
    echo "Deploying PosterPulse LCD setup to ${REMOTE_USER}@${TARGET_IP}:${SSH_PORT}"
    if ! ssh -o BatchMode=no -o ConnectTimeout=10 -p "$SSH_PORT" \
        "${REMOTE_USER}@${TARGET_IP}" "echo Connection OK"; then
        echo "Could not connect to ${REMOTE_USER}@${TARGET_IP}. Check SSH and the username." >&2
        exit 1
    fi

    ssh -p "$SSH_PORT" "${REMOTE_USER}@${TARGET_IP}" "mkdir -p ~/PosterPulse"
    tar --exclude='.git' --exclude='.venv' --exclude='venv' \
        --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
        --exclude='.mypy_cache' --exclude='.ruff_cache' --exclude='*.png' \
        -czf - -C "$REPO_DIR" . |
        ssh -p "$SSH_PORT" "${REMOTE_USER}@${TARGET_IP}" "tar -xzf - -C ~/PosterPulse"

    if [[ -f "${REPO_DIR}/.env" ]]; then
        scp -P "$SSH_PORT" "${REPO_DIR}/.env" \
            "${REMOTE_USER}@${TARGET_IP}:~/PosterPulse/.env"
    fi

    ssh -t -p "$SSH_PORT" "${REMOTE_USER}@${TARGET_IP}" \
        "cd ~/PosterPulse && sudo bash .github/setup-pi-lcd.sh --local -user=${REMOTE_USER}"
    exit 0
fi

if [[ "$LOCAL_MODE" != true || "$EUID" -ne 0 ]]; then
    show_help
    echo "Run local setup with sudo, or provide -ip for remote setup." >&2
    exit 1
fi

CURRENT_USER="${SUDO_USER:-}"
if [[ -n "$REMOTE_USER" && "$REMOTE_USER" != "pi" ]] && id "$REMOTE_USER" >/dev/null 2>&1; then
    CURRENT_USER="$REMOTE_USER"
fi
if [[ -z "$CURRENT_USER" || "$CURRENT_USER" == "root" ]]; then
    CURRENT_USER="$(stat -c '%U' "$REPO_DIR" 2>/dev/null || echo pi)"
fi
id "$CURRENT_USER" >/dev/null 2>&1 || { echo "Error: user '$CURRENT_USER' does not exist." >&2; exit 1; }
CURRENT_GROUP="$(id -gn "$CURRENT_USER")"
USER_HOME="$(getent passwd "$CURRENT_USER" | cut -d: -f6)"
VENV_DIR="${REPO_DIR}/.venv"

if ! command -v apt-get >/dev/null 2>&1; then
    echo "Error: This LCD setup script requires Raspberry Pi OS or Debian." >&2
    exit 1
fi

printf 'Configuring PosterPulse for LCD under user %s\n' "$CURRENT_USER"

apt-get update -y
apt-get install -y --no-install-recommends \
    python3-dev python3-venv python3-pip python3-tk \
    python3-pil python3-pil.imagetk

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    sudo -u "$CURRENT_USER" python3 -m venv --system-site-packages "$VENV_DIR"
fi
sudo -u "$CURRENT_USER" "${VENV_DIR}/bin/pip" install --upgrade pip
sudo -u "$CURRENT_USER" "${VENV_DIR}/bin/pip" install -r "${REPO_DIR}/requirements.txt"
sudo -u "$CURRENT_USER" "${VENV_DIR}/bin/python" -c \
    'import tkinter; from PIL import Image, ImageTk; print("Tkinter and Pillow ImageTk are ready")'

ENV_FILE="${REPO_DIR}/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    sudo -u "$CURRENT_USER" cp "${REPO_DIR}/.env.example" "$ENV_FILE"
fi

set_env_if_missing() {
    local key="$1" value="$2"
    if ! grep -q "^${key}=" "$ENV_FILE"; then
        printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
    fi
}
set_env_value() {
    local key="$1" value="$2"
    if grep -q "^${key}=" "$ENV_FILE"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
    else
        printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
    fi
}

set_env_value "DISPLAY_TYPE" "regular"
set_env_if_missing "FULLSCREEN" "true"
set_env_if_missing "REFRESH_SECONDS" "15"
set_env_if_missing "IDLE_REFRESH_MINUTES" "30"
set_env_if_missing "FADE_SPEED" "8"
chown "${CURRENT_USER}:${CURRENT_GROUP}" "$ENV_FILE"

# The e-ink service is headless; regular mode must run inside the desktop session.
systemctl disable --now posterpulse.service >/dev/null 2>&1 || true
AUTOSTART_DIR="${USER_HOME}/.config/autostart"
AUTOSTART_FILE="${AUTOSTART_DIR}/posterpulse.desktop"
install -d -o "$CURRENT_USER" -g "$CURRENT_GROUP" "$AUTOSTART_DIR"
cat > "$AUTOSTART_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=PosterPulse
Comment=Jellyfin poster display
Exec=/usr/bin/env DISPLAY=:0 ${VENV_DIR}/bin/python ${REPO_DIR}/main.py
Path=${REPO_DIR}
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
chown "${CURRENT_USER}:${CURRENT_GROUP}" "$AUTOSTART_FILE"

if [[ -S /tmp/.X11-unix/X0 ]]; then
    pkill -u "$CURRENT_USER" -f "^${VENV_DIR}/bin/python ${REPO_DIR}/main.py$" 2>/dev/null || true
    runuser -u "$CURRENT_USER" -- env DISPLAY=:0 nohup \
        "${VENV_DIR}/bin/python" "${REPO_DIR}/main.py" \
        >/tmp/posterpulse-regular.log 2>&1 </dev/null &
    echo "Started PosterPulse in the current graphical session."
else
    echo "Desktop autostart is installed. Log into the LCD desktop to start PosterPulse."
fi

echo "LCD setup complete. DISPLAY_TYPE=regular; idle poster rotation defaults to 30 minutes."
