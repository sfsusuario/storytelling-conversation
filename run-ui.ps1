# run-ui.ps1 - lanza la interfaz web (Gradio) de Charla.
# Uso:  .\run-ui.ps1

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
. "$PSScriptRoot\_python.ps1"

$py = Resolve-CharlaPython
& $py -m charla.ui
exit $LASTEXITCODE
