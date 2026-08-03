# install-chatterbox.ps1 - monta el motor de voz Chatterbox (Resemble AI, MIT).
#   - Python 3.10 (si no esta ya; se instala solo para el usuario)
#   - venv dedicado .chatterbox-venv con chatterbox-tts
#   - el modelo (~2 GB) se descarga solo en el primer uso
# Uso:  .\install-chatterbox.ps1
# Clonacion zero-shot desde voices_preview\reales\<personaje>\ con control
# de exageracion emocional. Licencia MIT (uso comercial permitido).

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-Location $PSScriptRoot

Write-Host "=== Charla: instalacion de Chatterbox ===" -ForegroundColor Cyan

# --- 1. Python 3.10 --------------------------------------------------------
$py310 = "$env:LOCALAPPDATA\Python310\python.exe"
if (Test-Path $py310) {
    Write-Host "[1/2] Python 3.10 ya instalado."
} else {
    Write-Host "[1/2] Descargando e instalando Python 3.10 (solo usuario)..."
    $exe = "$env:TEMP\python-3.10.11-amd64.exe"
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe" -OutFile $exe -UseBasicParsing
    & $exe /quiet InstallAllUsers=0 TargetDir="$env:LOCALAPPDATA\Python310" AssociateFiles=0 Shortcuts=0 Include_doc=0 Include_test=0 Include_launcher=0 PrependPath=0 | Out-Null
    if (-not (Test-Path $py310)) { Write-Host "ERROR: fallo la instalacion de Python 3.10." -ForegroundColor Red; exit 1 }
}

# --- 2. chatterbox-tts -----------------------------------------------------
$venvpy = ".chatterbox-venv\Scripts\python.exe"
if (-not (Test-Path $venvpy)) {
    Write-Host "[2/2] Creando venv .chatterbox-venv..."
    & $py310 -m venv .chatterbox-venv
    & $venvpy -m pip install --upgrade pip --quiet
}
Write-Host "[2/2] Instalando chatterbox-tts (pesado, paciencia)..."
& $venvpy -m pip install chatterbox-tts --quiet
& $venvpy -c "from chatterbox.mtl_tts import ChatterboxMultilingualTTS" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: chatterbox-tts no importa." -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "=== Chatterbox listo ===" -ForegroundColor Green
Write-Host "  Uso:  charla ... --tts chatterbox"
Write-Host "  (el modelo ~2 GB se descarga en el primer uso; exageracion por"
Write-Host "   personaje via CHARLA_RICK_EXAGGERATION / CHARLA_MORTY_EXAGGERATION)"
