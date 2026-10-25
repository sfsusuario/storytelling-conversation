# run-ui.ps1 - lanza Storytelling Studio (web con todas las modalidades, http://127.0.0.1:7880).
# Modo avanzado (Gradio): .\run-gradio.ps1
# Uso:  .\run-ui.ps1            (-Rebuild fuerza recompilar la interfaz)
#       .\run-ui.ps1 -Remote    tambien desde tu telefono via Tailscale
param([switch]$Rebuild, [switch]$Remote)

& "$PSScriptRoot\run-web.ps1" -Rebuild:$Rebuild -Remote:$Remote
exit $LASTEXITCODE
