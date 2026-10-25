#!/usr/bin/env bash
# deploy.sh — git pull + dependencias + reinicio del servidor de Storytelling Studio.
# Uso: bash deploy.sh [rama]
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"

if [[ -n "${1:-}" ]]; then git checkout "$1"; fi
git pull --ff-only
.venv/bin/python -m pip install -r requirements.txt -q
$SUDO systemctl restart storyteller-api
sleep 2
curl -fsS http://127.0.0.1:8006/health && echo
