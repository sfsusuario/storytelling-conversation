# run-ui.ps1 - lanza la interfaz web de Charla (React, http://127.0.0.1:7870).
# Modo avanzado (Gradio): .\run-gradio.ps1
# Uso:  .\run-ui.ps1            (-Rebuild fuerza recompilar la interfaz)
param([switch]$Rebuild)

& "$PSScriptRoot\run-web.ps1" -Rebuild:$Rebuild
exit $LASTEXITCODE
