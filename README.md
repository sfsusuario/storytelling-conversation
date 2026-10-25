# Storytelling Studio

Videos verticales (Conversación, Escalera) generados en tu PC y manejables desde
el teléfono en **storytelling.fierro.dev**, para compartirlos directo a TikTok.

```
local/              tu PC: estudio (pipelines, GPU, Ollama, TTS) + worker
server/
  frontend/         web React -> Netlify (storytelling.fierro.dev)
  backend/          API FastAPI -> servidor (api.storyteller.fierro.dev)
run-server-local.ps1  el servidor completo en tu PC, para probar
```

## Cómo funciona

```
teléfono --HTTPS--> web (Netlify) --> API (servidor) <--long-poll-- worker (PC) --> estudio :7880
```

- El servidor **no genera nada**: pone en cola cada acción de la web y el worker
  del PC la ejecuta contra el estudio local y devuelve la respuesta (el progreso
  en vivo incluido). El PC solo hace conexiones salientes: no abre puertos.
- Videos, miniaturas e historial quedan copiados en el servidor: con el PC
  apagado se puede ver, descargar y **📤 Compartir** el historial; crear videos
  necesita el PC encendido con el worker.
- Entrada con contraseña (`STUDIO_PASSWORD`); el worker se identifica con
  `WORKER_TOKEN`.

## Uso diario (PC)

```powershell
.\run-worker.ps1     # (desde la raíz) estudio local + conexión con la web pública
cd local
.\run-ui.ps1         # solo el estudio local en http://127.0.0.1:7880 (sin web pública)
```

Detalles del estudio, modalidades y motores: [local/README.md](local/README.md).

## Probar el servidor en local

```powershell
.\run-server-local.ps1 -Worker   # API :8000 + web :5173 + worker; contraseña: local1234
```

## Desplegar

**1. Servidor** (Ubuntu/Debian con Apache, igual que tour-app):

```bash
sudo mkdir -p /var/www/sfs && cd /var/www/sfs
sudo git clone <repo> storytelling-conversation
cd storytelling-conversation/server/backend
sudo bash install.sh                 # .venv, .env (WORKER_TOKEN aleatorio), systemd, Apache (:8006)
sudo nano .env                       # STUDIO_PASSWORD=...
sudo systemctl restart storyteller-api
```

DNS: registro **A** `api.storyteller` -> IP del servidor. Después:
`sudo certbot --apache -d api.storyteller.fierro.dev`. Para actualizar: `bash deploy.sh`.

**2. Web en Netlify:** nuevo sitio desde el repo con *Base directory* =
`server/frontend` (build, publish y `VITE_API_BASE` ya están en
`server/frontend/netlify.toml`). Dominio: `storytelling.fierro.dev` (CNAME a
Netlify).

**3. PC:** en `local/.env` pon `STUDIO_WORKER_TOKEN=<WORKER_TOKEN del servidor>`
y ejecuta `.\run-worker.ps1`.
