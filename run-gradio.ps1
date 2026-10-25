# run-gradio.ps1 - lanza la interfaz Gradio de Charla (modo avanzado: todos
# los ajustes, historial y subida a TikTok).
# Uso:  .\run-gradio.ps1

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
. "$PSScriptRoot\_python.ps1"

$py = Resolve-CharlaPython
& $py -m charla.ui
exit $LASTEXITCODE
