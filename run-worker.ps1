# run-worker.ps1 - conecta este PC con el servidor publico (api.storyteller.fierro.dev)
# para que la web (storyteller.fierro.dev) genere videos aqui.
# Atajo de local\run-worker.ps1: token en local\.env (STUDIO_WORKER_TOKEN).
# Uso:  .\run-worker.ps1
#       .\run-worker.ps1 -Server http://127.0.0.1:8000   (contra run-server-local.ps1)
param([string]$Server = "")

& (Join-Path $PSScriptRoot "local\run-worker.ps1") -Server $Server
exit $LASTEXITCODE
