#!/usr/bin/env bash
# Phase-1-Installation des jetson-perception-worker auf dem Nano.
# Voraussetzung: USB-SSD ist als /mnt/ssd gemountet (mit noatime).
# Auf dem Nano als User 'erik' ausfuehren. Verwendet sudo nur fuer 4 Stellen.
set -euo pipefail

REPO_DIR="/home/erik/perception"
VENV="${REPO_DIR}/.venv"
ENV_FILE="/etc/perception/env"
SSD_PATH="/mnt/ssd"

step() { echo; echo "==> $*"; }

# 0. Voraussetzungen pruefen
step "Pruefe Voraussetzungen"
if ! mountpoint -q "${SSD_PATH}"; then
    echo "FEHLER: ${SSD_PATH} ist nicht gemountet." >&2
    echo "Erst USB-SSD anschliessen, formatieren, fstab-Eintrag setzen." >&2
    exit 1
fi
df -h / | awk 'NR==2 { if ($5+0 > 90) { print "WARN: eMMC > 90% voll"; exit 0 } }'

# 1. Pakete (Tesseract + Python-venv)
step "apt-Pakete"
sudo apt update
sudo apt install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng \
    python3-venv python3-pip stress-ng

# 2. Venv auf SSD (Symlink von /home/erik/perception/.venv)
step "Repo-Verzeichnis und venv auf SSD"
sudo mkdir -p "${SSD_PATH}/perception" "${SSD_PATH}/perception/tmp"
sudo chown -R erik:erik "${SSD_PATH}/perception"
mkdir -p "${REPO_DIR}"
if [[ ! -d "${VENV}" ]]; then
    python3 -m venv --system-site-packages "${SSD_PATH}/perception/venv"
    ln -sfn "${SSD_PATH}/perception/venv" "${VENV}"
fi
"${VENV}/bin/pip" install --upgrade pip
"${VENV}/bin/pip" install -r "${REPO_DIR}/requirements.txt"

# 3. Token + EnvironmentFile (kein Klartext-Output)
step "EnvironmentFile /etc/perception/env"
sudo mkdir -p /etc/perception
if [[ ! -f "${ENV_FILE}" ]]; then
    TOKEN_VAL="$(openssl rand -hex 32)"
    sudo bash -c "umask 077; cat > ${ENV_FILE}" <<EOF
PERCEPTION_TOKEN=${TOKEN_VAL}
PERCEPTION_TEMP=${SSD_PATH}/perception/tmp
PERCEPTION_HOST=jetson-nano
LOG_LEVEL=INFO
EOF
    sudo chmod 600 "${ENV_FILE}"
    echo "Token erzeugt. Abruf nur ueber: sudo cat ${ENV_FILE}"
    echo "Diesen Token gleich in den Orchestrator-.env auf host als NANO_TOKEN setzen."
else
    echo "${ENV_FILE} existiert bereits — nicht ueberschrieben."
fi

# 4. systemd-Unit
step "systemd-Unit installieren"
sudo install -m 644 "${REPO_DIR}/jetson-perception.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable jetson-perception.service
echo "Service vorbereitet. Start mit: sudo systemctl start jetson-perception"

# 5. Smoke-Test (lokal)
step "Smoke-Test (warte 3 s, dann curl /health)"
sudo systemctl restart jetson-perception
sleep 3
curl -s http://127.0.0.1:8800/health || echo "FEHLER: /health nicht erreichbar"

echo
echo "Fertig. Logs: journalctl -u jetson-perception -f"
