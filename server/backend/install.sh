#!/usr/bin/env bash
#
# install.sh — Instala el servidor de Storytelling Studio (api.storyteller.fierro.dev).
#
# El servidor no genera videos: recibe las acciones de la web y se las pasa al
# worker del PC (local/run-worker.ps1). Solo necesita Python 3.10+ y Apache.
#
# Uso:
#   cd /var/www/sfs/storytelling-conversation/server/backend
#   sudo bash install.sh
#
set -euo pipefail

SERVICE_USER="${SERVICE_USER:-www-data}"
UNIT=storyteller-api

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  ok:\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  warn:\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m  error:\033[0m %s\n' "$*" >&2; }

if [[ $EUID -ne 0 ]]; then
    err "Necesita root: sudo bash install.sh"
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
[[ -f main.py && -f requirements.txt ]] || { err "Ejecuta desde server/backend"; exit 1; }
log "Backend: $PROJECT_DIR"

log "Paquetes del sistema (python3-venv, apache2)"
apt update
apt install -y python3 python3-venv apache2
a2enmod proxy proxy_http headers >/dev/null || true
python3 -c 'import sys; assert sys.version_info >= (3, 10)' || { err "Se necesita Python 3.10+"; exit 1; }

log "Entorno virtual .venv"
[[ -d .venv ]] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip -q
.venv/bin/python -m pip install -r requirements.txt -q
ok "dependencias instaladas"

mkdir -p logs cache

if [[ ! -f .env ]]; then
    cp .env.example .env
    TOKEN=$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')
    SECRET=$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))')
    sed -i "s|^WORKER_TOKEN=.*|WORKER_TOKEN=$TOKEN|; s|^SECRET_KEY=.*|SECRET_KEY=$SECRET|" .env
    warn ".env creado con WORKER_TOKEN y SECRET_KEY aleatorios. Falta STUDIO_PASSWORD:"
    warn "  nano $PROJECT_DIR/.env"
else
    ok ".env presente"
fi
chmod 600 .env

log "systemd ($UNIT)"
sed -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" -e "s|__SERVICE_USER__|$SERVICE_USER|g" \
    deploy/$UNIT.service > /etc/systemd/system/$UNIT.service
systemctl daemon-reload
systemctl enable $UNIT >/dev/null 2>&1 || true
ok "/etc/systemd/system/$UNIT.service"

if [[ ! -f /etc/apache2/sites-available/storyteller.conf ]]; then
    cp deploy/apache-storyteller.conf /etc/apache2/sites-available/storyteller.conf
    a2ensite storyteller >/dev/null
    ok "sitio Apache storyteller.conf"
else
    ok "sitio Apache ya existe; no se sobrescribe"
fi

chown -R "$SERVICE_USER":"$SERVICE_USER" "$PROJECT_DIR/logs" "$PROJECT_DIR/cache" "$PROJECT_DIR/.env"

log "Instalación finalizada"
cat <<MSG

  1. Contraseña de la web:   nano $PROJECT_DIR/.env   (STUDIO_PASSWORD=...)
  2. Arrancar:               sudo systemctl restart $UNIT && curl http://127.0.0.1:8006/health
  3. DNS: registro A de api.storyteller.fierro.dev -> IP de este servidor, luego:
                             sudo apache2ctl configtest && sudo systemctl reload apache2
  4. HTTPS:                  sudo apt install -y python3-certbot-apache && sudo certbot --apache -d api.storyteller.fierro.dev
  5. En el PC, en local/.env: STUDIO_WORKER_TOKEN=<el WORKER_TOKEN de este .env>  y  .\run-worker.ps1

  Actualizar después:        bash deploy.sh

MSG
