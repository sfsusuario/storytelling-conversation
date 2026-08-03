# run-ui.ps1 - lanza la interfaz web (Gradio) de Charla.
# Uso:  .\run-ui.ps1

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

python -m charla.ui
exit $LASTEXITCODE
