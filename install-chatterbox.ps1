# install-chatterbox.ps1 - monta el motor de voz Chatterbox (Resemble AI, MIT).
#   - Python 3.10 (si no esta ya; se instala solo para el usuario)
#   - venv dedicado .chatterbox-venv con chatterbox-tts (CPU)
#   - con -Xpu: venv APARTE .chatterbox-xpu-venv con PyTorch para GPU Intel
#     Arc (XPU); el venv de CPU no se toca
#   - el modelo (~2 GB) se descarga solo en el primer uso
# Uso:  .\install-chatterbox.ps1
#       .\install-chatterbox.ps1 -Xpu                        (GPU Intel, experimental)
#       .\install-chatterbox.ps1 -Xpu -TorchVersion 2.7.1    (si 2.6 no ve la GPU)
# Clonacion zero-shot desde voices_preview\reales\<personaje>\ con control
# de exageracion emocional. Licencia MIT (uso comercial permitido).
param(
    [switch]$Xpu,
    # chatterbox-tts 0.1.7 fija torch==2.6.0; Lunar Lake (Core Ultra 200V)
    # figura como soportado oficialmente en XPU desde torch 2.7.
    [string]$TorchVersion = "2.6.0"
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-Location $PSScriptRoot

$venv = if ($Xpu) { ".chatterbox-xpu-venv" } else { ".chatterbox-venv" }
$title = if ($Xpu) { "Chatterbox XPU (GPU Intel Arc)" } else { "Chatterbox" }
Write-Host "=== Charla: instalacion de $title ===" -ForegroundColor Cyan

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

# --- 2. venv + paquetes ----------------------------------------------------
$venvpy = "$venv\Scripts\python.exe"
if (-not (Test-Path $venvpy)) {
    Write-Host "[2/3] Creando venv $venv..."
    & $py310 -m venv $venv
    & $venvpy -m pip install --upgrade pip --quiet
}

# Combo verificado: chatterbox-tts 0.1.7 + transformers 5.2.0 (+ torch 2.6).
$chatterbox = @("chatterbox-tts==0.1.7", "transformers==5.2.0")
$xpuIndex = "https://download.pytorch.org/whl/xpu"

if (-not $Xpu) {
    Write-Host "[2/3] Instalando chatterbox-tts (pesado, paciencia)..."
    & $venvpy -m pip install @chatterbox --quiet
} elseif ($TorchVersion -eq "2.6.0") {
    # torch 2.6.0+xpu PRIMERO: satisface el pin torch==2.6.0 de chatterbox
    # (PEP 440 ignora la etiqueta local +xpu), asi pip no lo reemplaza.
    Write-Host "[2/3] Instalando PyTorch 2.6.0 XPU (~2-3 GB, paciencia)..."
    & $venvpy -m pip install "torch==2.6.0" "torchaudio==2.6.0" --index-url $xpuIndex --quiet
    Write-Host "      Instalando chatterbox-tts..."
    & $venvpy -m pip install @chatterbox --quiet
} else {
    # Otra version de torch: chatterbox con sus dependencias y luego torch XPU
    # encima sin dependencias (pip avisara del pin 2.6.0: es esperado).
    Write-Host "[2/3] Instalando chatterbox-tts y luego PyTorch $TorchVersion XPU..."
    & $venvpy -m pip install @chatterbox --quiet
    & $venvpy -m pip install --force-reinstall --no-deps "torch==$TorchVersion" "torchaudio==$TorchVersion" --index-url $xpuIndex --quiet
}

# --- 3. Verificacion -------------------------------------------------------
Write-Host "[3/3] Verificando..."
& $venvpy -c "from chatterbox.mtl_tts import ChatterboxMultilingualTTS" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: chatterbox-tts no importa." -ForegroundColor Red; exit 1 }
if ($Xpu) {
    $check = & $venvpy -c "import torch; ok = torch.__version__.endswith('+xpu') and torch.xpu.is_available(); print(torch.__version__, '|', torch.xpu.get_device_name(0) if ok else 'SIN GPU XPU'); raise SystemExit(0 if ok else 3)" 2>$null
    Write-Host "      $check"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: PyTorch no ve la GPU Intel (o pip reemplazo torch XPU por la version CPU)." -ForegroundColor Red
        Write-Host "  - Actualiza el driver de Intel Arc y reintenta."
        Write-Host "  - O prueba otra version:  .\install-chatterbox.ps1 -Xpu -TorchVersion 2.7.1"
        exit 1
    }
}

Write-Host ""
Write-Host "=== $title listo ===" -ForegroundColor Green
Write-Host "  Uso:  charla ... --tts chatterbox"
if ($Xpu) {
    Write-Host "  Para usar la GPU, en .env:"
    Write-Host "    CHARLA_CHATTERBOX_PYTHON=.chatterbox-xpu-venv/Scripts/python.exe"
    Write-Host "  Mide antes de adoptarlo:"
    Write-Host "    .\.chatterbox-xpu-venv\Scripts\python.exe scripts\bench_chatterbox.py --device xpu"
}
Write-Host "  (el modelo ~2 GB se descarga en el primer uso; exageracion por"
Write-Host "   personaje via CHARLA_RICK_EXAGGERATION / CHARLA_MORTY_EXAGGERATION)"
