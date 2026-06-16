#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Network Discovery Tool — installer (Linux / macOS)
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${HERE}/.venv"

echo "==> Network Discovery Tool installer"

# 1. nmap binary (required for nmap-based discovery; tool still works without it)
if ! command -v nmap >/dev/null 2>&1; then
  echo "==> Installing nmap..."
  if   command -v apt-get >/dev/null 2>&1; then sudo apt-get update && sudo apt-get install -y nmap
  elif command -v dnf     >/dev/null 2>&1; then sudo dnf install -y nmap
  elif command -v yum     >/dev/null 2>&1; then sudo yum install -y nmap
  elif command -v pacman  >/dev/null 2>&1; then sudo pacman -S --noconfirm nmap
  elif command -v brew    >/dev/null 2>&1; then brew install nmap
  else echo "!! Could not auto-install nmap. Please install it manually."; fi
else
  echo "==> nmap already installed: $(nmap --version | head -n1)"
fi

# 2. Python virtual environment + deps
echo "==> Creating virtual environment at ${VENV}"
python3 -m venv "${VENV}"
# shellcheck disable=SC1091
source "${VENV}/bin/activate"
pip install --upgrade pip
pip install -r "${HERE}/requirements-discovery.txt"

cat <<EOF

==> Done.

Run the dashboard (use sudo for full ARP/scapy scans):
    source ${VENV}/bin/activate
    sudo -E python -m backend.services.noc_service.discovery.run serve

Or a one-off CLI scan:
    python -m backend.services.noc_service.discovery.run scan --export

Dashboard:  http://localhost:8088/   (default login: admin / admin)
Set DISCOVERY_ADMIN_PASSWORD before first run to change the password.
EOF
