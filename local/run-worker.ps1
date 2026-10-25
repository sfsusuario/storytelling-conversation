# run-worker.ps1 - conecta este PC con la web publica (storytelling.fierro.dev).
# Levanta el estudio local (o usa el que ya corre en :7880) y atiende las
# tareas que llegan desde el servidor; solo conexiones salientes.
# Necesita en .env:  STUDIO_WORKER_TOKEN=<WORKER_TOKEN del servidor>
#                    STUDIO_SERVER_URL=https://api.storyteller.fierro.dev  (opcional)
# Uso:  .\run-worker.ps1
#       .\run-worker.ps1 -Server http://127.0.0.1:8000   (contra ..\run-server-local.ps1)
param([string]$Server = "")

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
. "$PSScriptRoot\_python.ps1"

$py = if (Test-Path ".venv\Scripts\python.exe") { (Resolve-Path ".venv\Scripts\python.exe").Path } else { Resolve-CharlaPython }
& $py -c "import studio.worker, httpx" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Instalando el proyecto en $py ..." -ForegroundColor Cyan
    & $py -m pip install -q -e ".[ui]"
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: fallo la instalacion." -ForegroundColor Red; exit 1 }
}
if (-not (Test-Path "..\server\frontend\dist\index.html")) {
    Write-Host "Aviso: falta la interfaz local (..\server\frontend\dist); la web publica funciona igual." -ForegroundColor Yellow
}

$workerArgs = @()
if ($Server) { $workerArgs += @("--server", $Server) }
& $py -m studio.worker @workerArgs
exit $LASTEXITCODE
