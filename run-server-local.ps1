# run-server-local.ps1 - ejecuta en este PC lo mismo que corre en el servidor:
#   API   server\backend   -> http://127.0.0.1:8000  (ventana aparte)
#   web   server\frontend  -> http://127.0.0.1:5173  (Vite, apuntando a esa API)
# -Worker abre tambien el worker (local\run-worker.ps1) conectado a esta API,
# para probar el circuito completo: web -> API -> worker -> estudio local.
# Uso:  .\run-server-local.ps1            (contrasena de prueba: local1234)
#       .\run-server-local.ps1 -Worker
param([switch]$Worker, [int]$Port = 8000, [int]$WebPort = 5173)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root "server\backend"
$frontend = Join-Path $root "server\frontend"
. (Join-Path $root "local\_python.ps1")

# API: su propio .venv (solo FastAPI), igual que en el servidor
$bpy = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $bpy)) {
    $py = Resolve-CharlaPython
    Write-Host "Creando server\backend\.venv ..." -ForegroundColor Cyan
    & $py -m venv (Join-Path $backend ".venv")
}
& $bpy -m pip install -q -r (Join-Path $backend "requirements.txt")
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: fallo pip install." -ForegroundColor Red; exit 1 }

# .env de pruebas (http, origen de Vite); el del servidor real lo crea install.sh
$envFile = Join-Path $backend ".env"
if (-not (Test-Path $envFile)) {
    $token = & $bpy -c "import secrets; print(secrets.token_urlsafe(32))"
    @(
        "STUDIO_PASSWORD=local1234",
        "WORKER_TOKEN=$token",
        "WEB_ORIGINS=http://127.0.0.1:$WebPort",
        "COOKIE_SECURE=0",
        "CACHE_DIR=cache"
    ) | Set-Content -Path $envFile -Encoding ascii
    Write-Host "server\backend\.env creado (contrasena: local1234)" -ForegroundColor Yellow
}
$token = ((Get-Content $envFile | Where-Object { $_ -match '^WORKER_TOKEN=' }) -replace '^WORKER_TOKEN=', '').Trim()

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: falta Node.js (npm). Instala Node.js LTS desde https://nodejs.org/" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Push-Location $frontend
    try { npm install --no-audit --no-fund } finally { Pop-Location }
}

Write-Host "API en http://127.0.0.1:$Port" -ForegroundColor Green
Start-Process powershell -WorkingDirectory $backend -ArgumentList @(
    "-NoExit", "-Command",
    "& '$bpy' -m uvicorn main:app --env-file .env --host 127.0.0.1 --port $Port"
)

if ($Worker) {
    Write-Host "Worker conectado a la API local (ventana aparte)" -ForegroundColor Green
    $runWorker = Join-Path $root "local\run-worker.ps1"
    Start-Process powershell -ArgumentList @(
        "-NoExit", "-Command",
        "`$env:STUDIO_WORKER_TOKEN='$token'; & '$runWorker' -Server http://127.0.0.1:$Port"
    )
}

Write-Host "Web en http://127.0.0.1:$WebPort  (Ctrl+C para salir)" -ForegroundColor Green
$env:VITE_API_BASE = "http://127.0.0.1:$Port"
Push-Location $frontend
try { npm run dev -- --host 127.0.0.1 --port $WebPort --strictPort --open } finally { Pop-Location }
