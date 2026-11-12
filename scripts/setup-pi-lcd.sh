#!/usr/bin/env bash
# ==============================================================================
# PosterPulse setup for Raspberry Pi OS with an LCD/HDMI display.
# Usage from a development computer:
#   bash scripts/setup-pi-lcd.sh -ip=10.0.0.119 -user=matt
#
# Usage locally on the Pi:
#   sudo bash scripts/setup-pi-lcd.sh --local
# ==============================================================================

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
    bash scripts/setup-pi-lcd.sh -ip=<PI_IP_ADDRESS> [-user=pi] [-port=22]

  Local setup directly on a Raspberry Pi with a desktop environment:
    sudo bash scripts/setup-pi-lcd.sh --local

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
    echo "=========================================================="
    echo "  PosterPulse: Remote Deployment for LCD/HDMI Display"
    echo "=========================================================="
    echo "Target Host: ${REMOTE_USER}@${TARGET_IP} (Port: ${SSH_PORT})"
    echo "Source Path: ${REPO_DIR}"
    echo ""
    echo "==> [1/3] Testing SSH connection to ${REMOTE_USER}@${TARGET_IP}..."
    SSH_CONTROL_DIR="$(mktemp -d /tmp/posterpulse-ssh.XXXXXX)"
    SSH_OPTIONS=(-o "ControlPath=${SSH_CONTROL_DIR}/control" -o ControlMaster=no \
        -o BatchMode=yes -o ConnectTimeout=10)
    cleanup_ssh() {
        # Cleanup must not hide a deployment failure if the connection already closed.
        ssh "${SSH_OPTIONS[@]}" -p "$SSH_PORT" -O exit \
            "${REMOTE_USER}@${TARGET_IP}" >/dev/null 2>&1 || true
        rm -rf "$SSH_CONTROL_DIR"
    }
    trap cleanup_ssh EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    if ! ssh -o BatchMode=no -o ControlMaster=yes \
        -o "ControlPath=${SSH_CONTROL_DIR}/control" -o ControlPersist=no \
        -o ConnectTimeout=10 -fN -p "$SSH_PORT" "${REMOTE_USER}@${TARGET_IP}"; then
        echo "Could not connect to ${REMOTE_USER}@${TARGET_IP}. Check SSH and the username." >&2
        exit 1
    fi
    echo "Connection OK"

    echo "==> [2/3] Transferring PosterPulse project files to ~/PosterPulse..."
    ssh "${SSH_OPTIONS[@]}" -p "$SSH_PORT" "${REMOTE_USER}@${TARGET_IP}" "mkdir -p ~/PosterPulse"
    tar --exclude='.git' --exclude='.venv' --exclude='venv' \
        --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
        --exclude='.mypy_cache' --exclude='.ruff_cache' \
        --exclude='poster_cache' --exclude='*.png' \
        -czf - -C "$REPO_DIR" . |
        ssh "${SSH_OPTIONS[@]}" -p "$SSH_PORT" "${REMOTE_USER}@${TARGET_IP}" "tar -xzf - -C ~/PosterPulse"

    if [[ -f "${REPO_DIR}/.env" ]]; then
        echo "Syncing local .env file to ~/PosterPulse/.env..."
        scp "${SSH_OPTIONS[@]}" -P "$SSH_PORT" "${REPO_DIR}/.env" \
            "${REMOTE_USER}@${TARGET_IP}:~/PosterPulse/.env"
    fi

    echo "==> [3/3] Running setup on remote Raspberry Pi..."
    ssh "${SSH_OPTIONS[@]}" -t -p "$SSH_PORT" "${REMOTE_USER}@${TARGET_IP}" \
        "cd ~/PosterPulse && sudo bash scripts/setup-pi-lcd.sh --local -user=${REMOTE_USER}"
    echo ""
    echo "=========================================================="
    echo "  Remote Deployment Complete!"
    echo "=========================================================="
    echo "You can now connect to your Pi anytime using:"
    echo "  ssh -p ${SSH_PORT} ${REMOTE_USER}@${TARGET_IP}"
    echo "To monitor logs from the LCD app launched during setup:"
    echo "  ssh -p ${SSH_PORT} ${REMOTE_USER}@${TARGET_IP} 'tail -f ~/.local/state/posterpulse/regular.log'"
    echo "LCD mode starts in the desktop session, not as a systemd service."
    echo "=========================================================="
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

echo "=========================================================="
echo "  PosterPulse Local Setup: Raspberry Pi + LCD/HDMI Display"
echo "=========================================================="
echo "Target User:     ${CURRENT_USER}"
echo "Repository Path: ${REPO_DIR}"
echo ""

echo "==> [1/5] Installing required system packages..."
apt-get update -y
apt-get install -y --no-install-recommends \
    python3-dev python3-venv python3-pip python3-tk \
    python3-pil python3-pil.imagetk

echo "==> [2/5] Setting up Python virtual environment..."
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    sudo -u "$CURRENT_USER" python3 -m venv --system-site-packages "$VENV_DIR"
fi
sudo -u "$CURRENT_USER" "${VENV_DIR}/bin/pip" install --upgrade pip
sudo -u "$CURRENT_USER" "${VENV_DIR}/bin/pip" install -r "${REPO_DIR}/requirements.txt"
sudo -u "$CURRENT_USER" "${VENV_DIR}/bin/python" -c \
    'import tkinter; from PIL import Image, ImageTk; print("Tkinter and Pillow ImageTk are ready")'

echo "==> [3/5] Configuring .env for LCD display..."
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

bash "${SCRIPT_DIR}/setup-pi-wifi.sh"

# The e-ink service is headless; regular mode must run inside the desktop session.
echo "==> [4/5] Installing desktop autostart..."
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

echo "==> [5/5] Checking the graphical session and starting PosterPulse..."
if [[ -S /tmp/.X11-unix/X0 ]] &&
    grep -Eq '^JELLYFIN_URL=[^[:space:]]' "$ENV_FILE" &&
    grep -Eq '^JELLYFIN_API_TOKEN=[^[:space:]]' "$ENV_FILE"; then
    while IFS= read -r pid; do
        kill "$pid"
    done < <(pgrep -u "$CURRENT_USER" -f "^${VENV_DIR}/bin/python ${REPO_DIR}/main.py$" || test "$?" -eq 1)
    LOG_DIR="${USER_HOME}/.local/state/posterpulse"
    LOG_FILE="${LOG_DIR}/regular.log"
    install -d -o "$CURRENT_USER" -g "$CURRENT_GROUP" "$LOG_DIR"
    # Open the log as the desktop user, not as the privileged setup process.
    runuser -u "$CURRENT_USER" -- sh -c '
        set -eu
        export DISPLAY=:0
        cd "$1"
        : >> "$4"
        nohup "$2" "$3" >"$4" 2>&1 </dev/null &
        pid=$!
        sleep 2
        if ! kill -0 "$pid" 2>/dev/null; then
            echo "Error: PosterPulse exited during startup. See $4" >&2
            cat "$4" >&2
            exit 1
        fi
    ' sh "$REPO_DIR" "${VENV_DIR}/bin/python" "${REPO_DIR}/main.py" "$LOG_FILE"
    echo "Started PosterPulse in the current graphical session. Log: ${LOG_FILE}"
elif [[ ! -S /tmp/.X11-unix/X0 ]]; then
    echo "Desktop autostart is installed. Log into the LCD desktop to start PosterPulse."
else
    echo "Jellyfin credentials are not configured; skipping the immediate launch."
fi

echo ""
echo "=========================================================="
echo "  Setup Completed Successfully!"
echo "=========================================================="
echo ""
echo "DISPLAY_TYPE=regular; idle poster rotation defaults to 30 minutes."
echo ""
echo "Next Steps:"
echo "1. Edit ${ENV_FILE} to set your Jellyfin credentials:"
echo "   nano ${ENV_FILE}"
echo "   - JELLYFIN_URL=http://<your-jellyfin-ip>:8096"
echo "   - JELLYFIN_API_TOKEN=<your-jellyfin-token>"
echo ""
echo "2. Log into the Pi's LCD desktop to start PosterPulse automatically."
echo "   After changing settings, rerun setup or log out and back in."
echo "   Desktop autostart: ${AUTOSTART_FILE}"
echo ""
echo "3. To view logs from the LCD app launched during setup:"
echo "   tail -f ${USER_HOME}/.local/state/posterpulse/regular.log"
echo "   This log is created when setup launches the app in an active desktop session."
echo "   LCD mode uses desktop autostart, not the e-ink systemd service."
echo ""
