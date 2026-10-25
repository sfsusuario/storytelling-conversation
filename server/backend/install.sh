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

log "Paquetes del sistema (apache2)"
apt update
apt install -y apache2
a2enmod proxy proxy_http headers >/dev/null || true

# ── Python 3.11+ (igual que tour-app: 3.12 de deadsnakes o compilado) ──────────
log "Detectando Python"
PYTHON_BIN=""
for candidate in python3.12 python3.11 /usr/local/bin/python3.12; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
    fi
done
if [[ -z "$PYTHON_BIN" ]]; then
    log "Instalando Python 3.12 vía PPA deadsnakes"
    apt install -y software-properties-common curl
    add-apt-repository -y ppa:deadsnakes/ppa || true
    apt update
    if apt install -y python3.12 python3.12-venv python3.12-dev 2>/dev/null; then
        PYTHON_BIN="python3.12"
    else
        warn "deadsnakes no disponible. Compilando Python 3.12 desde fuente…"
        apt install -y build-essential zlib1g-dev libncurses5-dev libgdbm-dev \
            libnss3-dev libssl-dev libreadline-dev libffi-dev libsqlite3-dev \
            libbz2-dev liblzma-dev tk-dev uuid-dev wget
        PY_VERSION="3.12.9"
        (
            cd /tmp
            rm -rf "Python-${PY_VERSION}" "Python-${PY_VERSION}.tgz"
            wget -q "https://www.python.org/ftp/python/${PY_VERSION}/Python-${PY_VERSION}.tgz"
            tar xzf "Python-${PY_VERSION}.tgz"
            cd "Python-${PY_VERSION}"
            ./configure --enable-optimizations --prefix=/usr/local
            make -j"$(nproc)"
            make altinstall
        )
        PYTHON_BIN="/usr/local/bin/python3.12"
    fi
fi
case "$PYTHON_BIN" in
    python3.12) apt install -y python3.12-venv || true ;;
    python3.11) apt install -y python3.11-venv || true ;;
esac
ok "Usando $($PYTHON_BIN --version) ($(command -v "$PYTHON_BIN"))"

log "Entorno virtual .venv"
if [[ -d .venv ]]; then
    existing=$(.venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "0.0")
    needed=$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    if [[ "$existing" != "$needed" ]]; then
        warn ".venv usa Python $existing; recreando con $needed"
        rm -rf .venv
    fi
fi
[[ -d .venv ]] || "$PYTHON_BIN" -m venv .venv
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
