# setup-liveportrait.ps1 - instala LivePortrait para el movimiento "Cara viva".
#   - clona KwaiVGI/LivePortrait en %LOCALAPPDATA%\escalator\LivePortrait
#   - crea su propio venv (sus dependencias no se mezclan con las de escalator)
#   - descarga los pesos (~1 GB) desde Hugging Face
# Uso:  .\setup-liveportrait.ps1
# Para otra carpeta: define ESCALATE_LIVEPORTRAIT_DIR antes de ejecutarlo.

# Continue: native tools (git, pip) write progress to stderr, which 'Stop' turns
# into a fatal error under redirection; failures are checked via $LASTEXITCODE.
$ErrorActionPreference = 'Continue'
$dir = if ($env:ESCALATE_LIVEPORTRAIT_DIR) { $env:ESCALATE_LIVEPORTRAIT_DIR } else { "$env:LOCALAPPDATA\escalator\LivePortrait" }

Write-Host "=== LivePortrait: instalacion en $dir ===" -ForegroundColor Cyan

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: falta git. Instalalo con:  winget install Git.Git" -ForegroundColor Red
    exit 1
}

Write-Host "[1/4] Codigo..."
if (Test-Path "$dir\inference.py") {
    Write-Host "      ya clonado."
} else {
    New-Item -ItemType Directory -Force (Split-Path $dir) | Out-Null
    git clone --depth 1 https://github.com/KwaiVGI/LivePortrait $dir
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

Write-Host "[2/4] Entorno Python propio..."
if (-not (Test-Path "$dir\.venv\Scripts\python.exe")) {
    python -m venv "$dir\.venv"
}
$py = "$dir\.venv\Scripts\python.exe"
& $py -m pip install --quiet --upgrade pip

Write-Host "[3/4] Dependencias (CPU; ~1 GB la primera vez)..."
function Check([string]$what) {
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: fallo $what." -ForegroundColor Red; exit 1 }
}
& $py -m pip install --quiet torch torchvision; Check "pip (torch)"
# lmdb (training only) has no Windows wheel for this pin; gradio is only their demo app.
$reqs = Get-Content "$dir\requirements_base.txt" | Where-Object { $_ -notmatch '^(lmdb|gradio)\b' }
& $py -m pip install --quiet $reqs; Check "pip (requirements)"
& $py -m pip install --quiet onnxruntime huggingface_hub requests; Check "pip (onnxruntime)"

Write-Host "[4/4] Pesos del modelo..."
& "$dir\.venv\Scripts\hf.exe" download KwaiVGI/LivePortrait --local-dir "$dir\pretrained_weights" `
    --exclude "*.git*" --exclude "README.md" --exclude "docs/*"
Check "la descarga de pesos"
if (-not (Test-Path "$dir\pretrained_weights\liveportrait\base_models")) {
    Write-Host "ERROR: faltan los pesos en pretrained_weights\liveportrait." -ForegroundColor Red; exit 1
}

Write-Host ""
Write-Host "LIVEPORTRAIT LISTO" -ForegroundColor Green
Write-Host "Usalo con  --motion liveportrait  o 'Cara viva' en la web."
