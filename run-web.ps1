# run-web.ps1 - lanza Storytelling Studio en http://127.0.0.1:7880: una sola
# web con todas las modalidades (Conversacion, Escalera) e historial compartido.
# La primera vez compila la interfaz (necesita Node.js: npm install + build).
# Uso:  .\run-web.ps1            (-Rebuild fuerza recompilar la interfaz)
#       .\run-web.ps1 -Remote    tambien accesible desde tus dispositivos Tailscale
param([switch]$Rebuild, [switch]$Remote)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
. "$PSScriptRoot\_python.ps1"

# Entorno del proyecto (.venv: torch XPU, kokoro, diffusers... para Escalera).
# Sin .venv se usa el Python del sistema (Escalera sin motores locales).
$py = if (Test-Path ".venv\Scripts\python.exe") { (Resolve-Path ".venv\Scripts\python.exe").Path } else { Resolve-CharlaPython }
& $py -c "import studio" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Instalando el proyecto en $py ..." -ForegroundColor Cyan
    & $py -m pip install -q -e ".[ui]"
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: fallo la instalacion." -ForegroundColor Red; exit 1 }
}

if ($Rebuild -or -not (Test-Path "web\dist\index.html")) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Host "ERROR: falta Node.js (npm) para compilar la interfaz web." -ForegroundColor Red
        Write-Host "  Instala Node.js LTS desde https://nodejs.org/ y reintenta."
        exit 1
    }
    Write-Host "Compilando la interfaz web (solo la primera vez)..." -ForegroundColor Cyan
    Push-Location web
    try {
        if (-not (Test-Path "node_modules")) { npm install --no-audit --no-fund }
        npm run build
        if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: fallo la compilacion." -ForegroundColor Red; exit 1 }
    } finally { Pop-Location }
}

$studioArgs = @()
if ($Remote) { $studioArgs += "--tailscale" }
& $py -m studio.app @studioArgs
exit $LASTEXITCODE
