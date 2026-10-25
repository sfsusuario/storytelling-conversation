# install-rvc.ps1 - monta la conversion de voz RVC (voces del doblaje latino).
#   - Python 3.10 (requerido por rvc-python; se instala solo para el usuario)
#   - venv dedicado .rvc-venv con rvc-python + torch CPU + fairseq (wheel Windows)
#   - modelos RVC de Rick (Juan Guzman) y Morty (Eder La Barrera) desde Hugging Face
# Uso:  .\install-rvc.ps1
# Nota: descarga ~1.5 GB en total (torch + modelos). Todo queda fuera de git.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-Location $PSScriptRoot

Write-Host "=== Charla: instalacion de RVC (voces del doblaje) ===" -ForegroundColor Cyan

# --- 1. Python 3.10 --------------------------------------------------------
$py310 = "$env:LOCALAPPDATA\Python310\python.exe"
if (Test-Path $py310) {
    Write-Host "[1/4] Python 3.10 ya instalado."
} else {
    Write-Host "[1/4] Descargando e instalando Python 3.10 (solo usuario)..."
    $exe = "$env:TEMP\python-3.10.11-amd64.exe"
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe" -OutFile $exe -UseBasicParsing
    & $exe /quiet InstallAllUsers=0 TargetDir="$env:LOCALAPPDATA\Python310" AssociateFiles=0 Shortcuts=0 Include_doc=0 Include_test=0 Include_launcher=0 PrependPath=0 | Out-Null
    if (-not (Test-Path $py310)) { Write-Host "ERROR: fallo la instalacion de Python 3.10." -ForegroundColor Red; exit 1 }
}

# --- 2. venv dedicado ------------------------------------------------------
$venvpy = ".rvc-venv\Scripts\python.exe"
if (-not (Test-Path $venvpy)) {
    Write-Host "[2/4] Creando venv .rvc-venv..."
    & $py310 -m venv .rvc-venv
}

# --- 3. rvc-python ---------------------------------------------------------
Write-Host "[3/4] Instalando rvc-python (torch CPU ~200 MB, paciencia)..."
# pip 24.0: las dependencias de fairseq llevan metadata antigua que pip moderno rechaza
& $venvpy -m pip install "pip==24.0" --quiet
# wheel de fairseq precompilado para Windows (no hay wheel oficial)
& $venvpy -m pip install "https://huggingface.co/Jmica/rvc/resolve/01b388e059df1218a5a7b48b91305b2e06fed030/fairseq-0.12.2-cp310-cp310-win_amd64.whl" --quiet
& $venvpy -m pip install rvc-python --quiet
# torch <2.6: desde 2.6 torch.load(weights_only=True) rompe los checkpoints fairseq
& $venvpy -m pip install "torch==2.5.1" "torchaudio==2.5.1" --index-url https://download.pytorch.org/whl/cpu --quiet
& $venvpy -c "from rvc_python.infer import RVCInference" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: rvc-python no importa." -ForegroundColor Red; exit 1 }
Write-Host "      rvc-python OK."

# --- 4. Modelos ------------------------------------------------------------
Write-Host "[4/4] Descargando modelos del doblaje latino (~390 MB)..."
New-Item -ItemType Directory -Force "models\rvc\rick", "models\rvc\morty" | Out-Null
$downloads = @(
    @("https://huggingface.co/Matius54/Rick_Sanchez_Latino/resolve/main/Rick_Sanchez_Lat_v2_e350.pth", "models\rvc\rick\rick.pth"),
    @("https://huggingface.co/Matius54/Rick_Sanchez_Latino/resolve/main/added_IVF1185_Flat_nprobe_1_Rick_Sanchez_Lat_v2_v2.index", "models\rvc\rick\rick.index"),
    @("https://huggingface.co/Matius54/Morty_Smith_Latino/resolve/main/Morty_Lat_e195.pth", "models\rvc\morty\morty.pth"),
    @("https://huggingface.co/Matius54/Morty_Smith_Latino/resolve/main/added_IVF1120_Flat_nprobe_1_v2.index", "models\rvc\morty\morty.index")
)
foreach ($d in $downloads) {
    if (-not (Test-Path $d[1])) {
        Write-Host "      $($d[1])..."
        Invoke-WebRequest -Uri $d[0] -OutFile $d[1] -UseBasicParsing
    }
}

Write-Host ""
Write-Host "=== RVC listo ===" -ForegroundColor Green
Write-Host "  charla usara las voces del doblaje automaticamente (--rvc auto)."
Write-Host "  Desactivar por run:  charla ... --rvc off"
