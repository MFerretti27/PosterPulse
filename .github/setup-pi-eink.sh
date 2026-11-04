#!/usr/bin/env bash
# ==============================================================================
# PosterPulse - Automated Setup Script for Raspberry Pi Zero 2 W with Waveshare
# 7.3" PhotoPainter E-Ink Display (epd7in3e)
#
# Supports:
#   1. Remote setup from Mac/PC over SSH:
#      .github/setup-pi-eink.sh -ip=10.0.0.27 [-user=pi] [-port=22]
#
#   2. Local setup directly on the Raspberry Pi:
#      sudo .github/setup-pi-eink.sh --local
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVICE_NAME="posterpulse.service"

TARGET_IP=""
REMOTE_USER="pi"
SSH_PORT="22"
LOCAL_MODE=false

show_help() {
    cat <<EOF
Usage:
  Remote setup (from your computer to Raspberry Pi):
    .github/setup-pi-eink.sh -ip=<PI_IP_ADDRESS> [-user=pi] [-port=22]

  Local setup (running directly on the Raspberry Pi):
    sudo .github/setup-pi-eink.sh --local

Options:
  -ip=IP, --ip=IP, -ip IP       Target IP address or hostname of the Raspberry Pi
  -user=USER, -u=USER           SSH username for the Pi (default: pi)
  -port=PORT, -p=PORT           SSH port (default: 22)
  --local, -l                   Execute local installation directly on this machine
  -h, --help                    Show this help message

Examples:
  .github/setup-pi-eink.sh -ip=10.0.0.27
  .github/setup-pi-eink.sh -ip=10.0.0.27 -user=pi
EOF
}

# ------------------------------------------------------------------------------
# Argument Parsing
# ------------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        -ip=*|--ip=*)
            TARGET_IP="${1#*=}"
            shift
            ;;
        -ip|--ip)
            if [[ $# -lt 2 || "$2" =~ ^- ]]; then
                echo "Error: -ip requires an IP address argument." >&2
                exit 1
            fi
            TARGET_IP="$2"
            shift 2
            ;;
        -user=*|--user=*|-u=*|--u=*)
            REMOTE_USER="${1#*=}"
            shift
            ;;
        -user|--user|-u)
            if [[ $# -lt 2 || "$2" =~ ^- ]]; then
                echo "Error: -user requires a username argument." >&2
                exit 1
            fi
            REMOTE_USER="$2"
            shift 2
            ;;
        -port=*|--port=*|-p=*|--p=*)
            SSH_PORT="${1#*=}"
            shift
            ;;
        -port|--port|-p)
            if [[ $# -lt 2 || "$2" =~ ^- ]]; then
                echo "Error: -port requires a port number argument." >&2
                exit 1
            fi
            SSH_PORT="$2"
            shift 2
            ;;
        --local|-l)
            LOCAL_MODE=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "Error: Unknown argument: $1" >&2
            show_help
            exit 1
            ;;
    esac
done

# ------------------------------------------------------------------------------
# Mode A: Remote Deployment over SSH
# ------------------------------------------------------------------------------
if [[ -n "${TARGET_IP}" ]]; then
    echo "=========================================================="
    echo "  PosterPulse: Remote Deployment to Raspberry Pi Zero 2 W"
    echo "=========================================================="
    echo "Target Host: ${REMOTE_USER}@${TARGET_IP} (Port: ${SSH_PORT})"
    echo "Source Path: ${REPO_DIR}"
    echo ""

    if ! command -v ssh &>/dev/null; then
        echo "Error: 'ssh' client not found on this system." >&2
        exit 1
    fi

    echo "==> [1/3] Testing SSH connection to ${REMOTE_USER}@${TARGET_IP}..."
    if ! ssh -o BatchMode=no -o ConnectTimeout=10 -p "${SSH_PORT}" "${REMOTE_USER}@${TARGET_IP}" "echo Connection OK" 2>/dev/null; then
        echo ""
        echo "Failed to connect to ${REMOTE_USER}@${TARGET_IP}:${SSH_PORT}."
        echo "Please verify:"
        echo "  1. The Raspberry Pi is powered on and connected to your network (IP: ${TARGET_IP})."
        echo "  2. SSH is enabled on the Pi."
        echo "  3. The username '${REMOTE_USER}' is correct (change with -user=<username>)."
        exit 1
    fi

    echo "==> [2/3] Transferring PosterPulse project files to ~/PosterPulse..."
    ssh -p "${SSH_PORT}" "${REMOTE_USER}@${TARGET_IP}" "mkdir -p ~/PosterPulse"

    # Stream repository files excluding virtualenvs and temporary build caches
    tar --exclude='.git' \
        --exclude='.venv' \
        --exclude='venv' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='.DS_Store' \
        --exclude='.mypy_cache' \
        --exclude='.ruff_cache' \
        --exclude='*.png' \
        -czf - -C "${REPO_DIR}" . | ssh -p "${SSH_PORT}" "${REMOTE_USER}@${TARGET_IP}" "tar -xzf - -C ~/PosterPulse"

    # If local .env exists, copy it to the remote device as well
    if [[ -f "${REPO_DIR}/.env" ]]; then
        echo "Syncing local .env file to ~/PosterPulse/.env..."
        scp -P "${SSH_PORT}" "${REPO_DIR}/.env" "${REMOTE_USER}@${TARGET_IP}:~/PosterPulse/.env" 2>/dev/null || true
    fi

    echo "==> [3/3] Running setup on remote Raspberry Pi..."
    ssh -t -p "${SSH_PORT}" "${REMOTE_USER}@${TARGET_IP}" "cd ~/PosterPulse && sudo bash .github/setup-pi-eink.sh --local -user=${REMOTE_USER}"

    echo ""
    echo "=========================================================="
    echo "  Remote Deployment Complete!"
    echo "=========================================================="
    echo "You can now connect to your Pi anytime using:"
    echo "  ssh ${REMOTE_USER}@${TARGET_IP}"
    echo "To monitor the PosterPulse service:"
    echo "  ssh ${REMOTE_USER}@${TARGET_IP} 'journalctl -u posterpulse -f'"
    echo "=========================================================="
    exit 0
fi

# ------------------------------------------------------------------------------
# Mode B: Local Setup on Raspberry Pi
# ------------------------------------------------------------------------------
if [[ "${LOCAL_MODE}" != "true" && $EUID -ne 0 ]]; then
    show_help
    exit 1
fi

if [[ $EUID -ne 0 ]]; then
    echo "Error: Local setup must be run with root privileges (sudo)." >&2
    echo "Usage: sudo .github/setup-pi-eink.sh --local" >&2
    exit 1
fi

CURRENT_USER="${SUDO_USER:-}"
if [[ -z "${CURRENT_USER}" || "${CURRENT_USER}" == "root" ]]; then
    if [[ -n "${REMOTE_USER}" && "${REMOTE_USER}" != "root" ]] && id "${REMOTE_USER}" &>/dev/null; then
        CURRENT_USER="${REMOTE_USER}"
    else
        DIR_OWNER="$(stat -c '%U' "${REPO_DIR}" 2>/dev/null || stat -f '%Su' "${REPO_DIR}" 2>/dev/null || echo "pi")"
        if [[ "${DIR_OWNER}" != "root" ]] && id "${DIR_OWNER}" &>/dev/null; then
            CURRENT_USER="${DIR_OWNER}"
        elif id "pi" &>/dev/null; then
            CURRENT_USER="pi"
        else
            CURRENT_USER="$(id -un)"
        fi
    fi
fi

VENV_DIR="${REPO_DIR}/.venv"

echo "=========================================================="
echo "  PosterPulse Local Setup: Pi Zero 2 W + E-Ink Display"
echo "=========================================================="
echo "Target User:     ${CURRENT_USER}"
echo "Repository Path: ${REPO_DIR}"
echo ""

# 1. Update apt and install required system packages
echo "==> [1/6] Installing required system packages..."
apt-get update -y
apt-get install -y --no-install-recommends \
    python3-dev \
    python3-venv \
    python3-pip \
    python3-pil \
    python3-numpy \
    python3-spidev \
    python3-gpiozero \
    libopenjp2-7 \
    libtiff6 \
    libjpeg62-turbo \
    raspi-config

# 2. Enable SPI & I2C hardware interfaces
echo "==> [2/6] Enabling SPI and I2C hardware interfaces..."
raspi-config nonint do_spi 0 || true
raspi-config nonint do_i2c 0 || true

BOOT_CONFIG="/boot/config.txt"
if [[ -f "/boot/firmware/config.txt" ]]; then
    BOOT_CONFIG="/boot/firmware/config.txt"
fi

if ! grep -q "^dtparam=spi=on" "${BOOT_CONFIG}" 2>/dev/null; then
    echo "Adding dtparam=spi=on to ${BOOT_CONFIG}..."
    echo "dtparam=spi=on" >> "${BOOT_CONFIG}"
fi

# 3. Set up Python virtual environment and dependencies
echo "==> [3/6] Setting up Python virtual environment..."
if [[ ! -d "${VENV_DIR}" ]]; then
    sudo -u "${CURRENT_USER}" python3 -m venv --system-site-packages "${VENV_DIR}"
fi

echo "Installing Python dependencies from requirements.txt..."
sudo -u "${CURRENT_USER}" "${VENV_DIR}/bin/pip" install --upgrade pip
sudo -u "${CURRENT_USER}" "${VENV_DIR}/bin/pip" install -r "${REPO_DIR}/requirements.txt"

# 4. Ensure user is in spi and gpio groups
echo "==> [4/6] Configuring hardware permissions for user '${CURRENT_USER}'..."
usermod -aG spi,gpio,i2c "${CURRENT_USER}" || true

# 5. Initialize .env file configured for Waveshare PhotoPainter E-Ink
echo "==> [5/6] Configuring .env for E-Ink display..."
ENV_FILE="${REPO_DIR}/.env"
if [[ ! -f "${ENV_FILE}" ]]; then
    if [[ -f "${REPO_DIR}/.env.example" ]]; then
        sudo -u "${CURRENT_USER}" cp "${REPO_DIR}/.env.example" "${ENV_FILE}"
        echo "Created .env from .env.example"
    else
        sudo -u "${CURRENT_USER}" touch "${ENV_FILE}"
    fi
fi

ensure_env_var() {
    local key="$1"
    local value="$2"
    if grep -q "^${key}=" "${ENV_FILE}"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}"
    else
        echo "${key}=${value}" >> "${ENV_FILE}"
    fi
}

ensure_env_var "DISPLAY_TYPE" "eink"
ensure_env_var "EINK_WIDTH" "800"
ensure_env_var "EINK_HEIGHT" "480"
ensure_env_var "EINK_PWR_PIN" "27"
ensure_env_var "REFRESH_SECONDS" "15"
ensure_env_var "IDLE_REFRESH_MINUTES" "30"

chown "${CURRENT_USER}:${CURRENT_USER}" "${ENV_FILE}"

# 6. Create and enable systemd service for headless startup
echo "==> [6/6] Installing systemd service (${SERVICE_NAME})..."
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"

cat > "${SERVICE_PATH}" <<EOF
[Unit]
Description=PosterPulse Jellyfin E-Ink Display
After=network-online.target time-sync.target
Wants=network-online.target

[Service]
Type=simple
User=${CURRENT_USER}
Group=${CURRENT_USER}
WorkingDirectory=${REPO_DIR}
EnvironmentFile=-${REPO_DIR}/.env
ExecStart=${VENV_DIR}/bin/python main.py
Restart=always
RestartSec=15
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"

# If JELLYFIN_URL is set, restart the service automatically
JELLYFIN_SET=$(grep -E "^JELLYFIN_URL=https?://" "${ENV_FILE}" || true)
if [[ -n "${JELLYFIN_SET}" ]]; then
    echo "Found configured JELLYFIN_URL in .env, starting ${SERVICE_NAME}..."
    systemctl restart "${SERVICE_NAME}"
fi

echo ""
echo "=========================================================="
echo "  Setup Completed Successfully!"
echo "=========================================================="
echo ""
echo "Next Steps:"
echo "1. Edit ${ENV_FILE} to set your Jellyfin credentials:"
echo "   nano ${ENV_FILE}"
echo "   - JELLYFIN_URL=http://<your-jellyfin-ip>:8096"
echo "   - JELLYFIN_API_TOKEN=<your-jellyfin-token>"
echo ""
echo "2. If this is the first time enabling SPI on this Pi, reboot:"
echo "   sudo reboot"
echo ""
echo "3. To manage the PosterPulse background service:"
echo "   sudo systemctl start ${SERVICE_NAME}    # Start service"
echo "   sudo systemctl restart ${SERVICE_NAME}  # Restart service"
echo "   sudo systemctl status ${SERVICE_NAME}   # View status"
echo "   journalctl -u ${SERVICE_NAME} -f        # View live logs"
echo ""
