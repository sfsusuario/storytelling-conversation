# install-xtts.ps1 - monta el motor de voz XTTS v2 (clonacion de voz local).
#   - Python 3.10 (si no esta ya; se instala solo para el usuario)
#   - venv dedicado .xtts-venv con coqui-tts + torch CPU
#   - el modelo base XTTS v2 (~1.9 GB) se descarga solo en el primer uso
# Uso:  .\install-xtts.ps1
# Entrenamiento del modelo por personaje: ver COLAB_XTTS.md
# Licencia XTTS (CPML): solo uso no comercial.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-Location $PSScriptRoot

Write-Host "=== Charla: instalacion de XTTS (voz clonada) ===" -ForegroundColor Cyan

# --- 1. Python 3.10 --------------------------------------------------------
$py310 = "$env:LOCALAPPDATA\Python310\python.exe"
if (Test-Path $py310) {
    Write-Host "[1/3] Python 3.10 ya instalado."
} else {
    Write-Host "[1/3] Descargando e instalando Python 3.10 (solo usuario)..."
    $exe = "$env:TEMP\python-3.10.11-amd64.exe"
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe" -OutFile $exe -UseBasicParsing
    & $exe /quiet InstallAllUsers=0 TargetDir="$env:LOCALAPPDATA\Python310" AssociateFiles=0 Shortcuts=0 Include_doc=0 Include_test=0 Include_launcher=0 PrependPath=0 | Out-Null
    if (-not (Test-Path $py310)) { Write-Host "ERROR: fallo la instalacion de Python 3.10." -ForegroundColor Red; exit 1 }
}

# --- 2. venv dedicado ------------------------------------------------------
$venvpy = ".xtts-venv\Scripts\python.exe"
if (-not (Test-Path $venvpy)) {
    Write-Host "[2/3] Creando venv .xtts-venv..."
    & $py310 -m venv .xtts-venv
    & $venvpy -m pip install --upgrade pip --quiet
}

# --- 3. coqui-tts ----------------------------------------------------------
Write-Host "[3/3] Instalando coqui-tts (torch CPU, paciencia)..."
& $venvpy -m pip install "torch==2.5.1" "torchaudio==2.5.1" --index-url https://download.pytorch.org/whl/cpu --quiet
& $venvpy -m pip install coqui-tts --quiet
# coqui-tts declara transformers>=4.57 pero la serie 5.x le rompe imports
& $venvpy -m pip install "transformers~=4.57.0" --quiet
& $venvpy -c "from TTS.tts.models.xtts import Xtts" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: coqui-tts no importa." -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "=== XTTS listo ===" -ForegroundColor Green
Write-Host "  Zero-shot (sin entrenar):  charla ... --tts xtts"
Write-Host "     (usa los clips de voices_preview\reales\<personaje>\ como referencia;"
Write-Host "      el modelo base ~1.9 GB se descarga en el primer uso)"
Write-Host "  Modelo entrenado en Colab: ver COLAB_XTTS.md y colocar el resultado en"
Write-Host "     models\xtts\rick\  y  models\xtts\morty\"
