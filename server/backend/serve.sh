#!/usr/bin/env bash
#
# serve.sh — Arranca/para la API (gunicorn) sin systemd. En el servidor no hay
# worker: el worker corre en el PC (local/run-worker.ps1).
#
# Uso:
#   sudo ./serve.sh start
#   sudo ./serve.sh stop
#   sudo ./serve.sh restart
#   ./serve.sh status
#   ./serve.sh logs                 # tail -f
#   ./serve.sh debug                # API en primer plano (Ctrl+C para salir)
#
# Variables de entorno (opcionales):
#   BIND   dirección:puerto — por defecto 127.0.0.1:8006 (Apache delante)
#
# En producción se recomienda systemd (install.sh instala storyteller-api).
#
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUNICORN="$PROJECT_DIR/.venv/bin/gunicorn"
API_PID="$PROJECT_DIR/gunicorn.pid"
LOG_DIR="$PROJECT_DIR/logs"
BIND="${BIND:-127.0.0.1:8006}"
# --workers 1: la cola de tareas vive en memoria de un solo proceso. No subir.
GUNICORN_ARGS=(--worker-class uvicorn.workers.UvicornWorker --bind "$BIND" --workers 1 --timeout 0)

mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR"

load_env() {
    [[ -f .env ]] || { echo "Falta .env — ejecuta install.sh" >&2; exit 1; }
    set -a; source .env; set +a   # systemd lo hace con EnvironmentFile
}

# El PID del archivo sigue vivo Y es de este proyecto (tras reiniciar, ese número puede ser otro programa)
pid_running() {
    [[ -f "$API_PID" ]] || return 1
    local pid; pid=$(cat "$API_PID" 2>/dev/null)
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null || return 1
    [[ "$(readlink "/proc/$pid/cwd" 2>/dev/null || true)" == "$PROJECT_DIR"* ]]
}

start() {
    if pid_running; then echo "API ya está corriendo (pid $(cat "$API_PID"))."; return; fi
    [[ -x "$GUNICORN" ]] || { echo "No se encuentra $GUNICORN — ¿ejecutaste install.sh?" >&2; exit 1; }
    load_env
    "$GUNICORN" "${GUNICORN_ARGS[@]}" --pid "$API_PID" \
        --access-logfile "$LOG_DIR/access.log" --error-logfile "$LOG_DIR/error.log" --daemon main:app
    sleep 1
    if pid_running; then echo "API arrancada (pid $(cat "$API_PID")) en $BIND"
    else echo "Falló el arranque de la API. Revisa $LOG_DIR/error.log" >&2; exit 1; fi
}

stop() {
    if ! pid_running; then echo "API no está corriendo."; rm -f "$API_PID"; return; fi
    local pid; pid=$(cat "$API_PID")
    kill "$pid"
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
    if kill -0 "$pid" 2>/dev/null; then echo "No respondió a SIGTERM, enviando SIGKILL..."; kill -9 "$pid"; fi
    rm -f "$API_PID"
    echo "API detenida."
}

case "${1:-}" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; start ;;
    status)  if pid_running; then echo "API corriendo (pid $(cat "$API_PID"), bind $BIND)"; else echo "API detenida."; fi ;;
    logs)    tail -f "$LOG_DIR/error.log" "$LOG_DIR/access.log" ;;
    debug)
        if pid_running; then echo "Hay una API corriendo (pid $(cat "$API_PID")). Detenla con: $0 stop"; exit 1; fi
        load_env
        echo "API en primer plano en $BIND. Ctrl+C para detener."
        "$GUNICORN" "${GUNICORN_ARGS[@]}" --access-logfile - --error-logfile - main:app
        ;;
    *) echo "Uso: $0 {start|stop|restart|status|logs|debug}" >&2; exit 1 ;;
esac
