# install.ps1 - instala todo lo necesario para Charla.
#   - paquete Python con sus dependencias
#   - ffmpeg (winget si esta disponible; si no, descarga un build estatico)
#   - crea .env a partir de .env.example si no existe
# Uso:  .\install.ps1

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host "=== Charla: instalacion ===" -ForegroundColor Cyan

# --- 1. Python -------------------------------------------------------------
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "ERROR: no se encontro 'python' en el PATH." -ForegroundColor Red
    Write-Host "Instala Python 3.11+ desde https://www.python.org/downloads/ y reintenta."
    exit 1
}
$ver = python --version
Write-Host "[1/4] Python detectado: $ver"

# --- 2. Paquete + dependencias (CLI + UI) ----------------------------------
Write-Host "[2/4] Instalando el paquete y dependencias (CLI + UI)..."
python -m pip install -e ".[ui]" --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: fallo la instalacion de dependencias." -ForegroundColor Red
    Write-Host "Si usas Python muy nuevo y alguna rueda falla, prueba con:  py -3.12 -m venv .venv"
    exit 1
}
Write-Host "      paquete 'charla' instalado."

# --- 3. ffmpeg -------------------------------------------------------------
Write-Host "[3/4] Comprobando ffmpeg..."
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpeg) {
    $local = Get-ChildItem "$env:LOCALAPPDATA\ffmpeg\*\bin\ffmpeg.exe" -ErrorAction SilentlyContinue |
             Select-Object -First 1
    if ($local) { $ffmpeg = $local }
}
if ($ffmpeg) {
    Write-Host "      ffmpeg ya disponible."
} else {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    $installed = $false
    if ($winget) {
        Write-Host "      instalando ffmpeg con winget..."
        winget install --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements --silent
        if ($LASTEXITCODE -eq 0) { $installed = $true }
    }
    if (-not $installed) {
        Write-Host "      descargando build estatico de ffmpeg (~90 MB)..."
        $dest = "$env:LOCALAPPDATA\ffmpeg"
        New-Item -ItemType Directory -Force $dest | Out-Null
        $zip = "$dest\ffmpeg-release-essentials.zip"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" `
                          -OutFile $zip -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath $dest -Force
        Remove-Item $zip
        Write-Host "      ffmpeg extraido en $dest (la app lo encuentra ahi sola)."
    }
}

# --- 4. .env ---------------------------------------------------------------
Write-Host "[4/4] Configuracion de claves..."
if (Test-Path ".env") {
    Write-Host "      .env ya existe, no se toca."
} else {
    Copy-Item ".env.example" ".env"
    Write-Host "      creado .env a partir de .env.example." -ForegroundColor Yellow
    Write-Host "      EDITA .env y pon tu ANTHROPIC_API_KEY (o GOOGLE_API_KEY)." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Listo ===" -ForegroundColor Green
Write-Host "  Prueba gratis (sin LLM):  charla --script-file examples\demo_script.json"
Write-Host "  Generacion guiada:        .\run-cli.ps1"
Write-Host "  Interfaz web:             .\run-ui.ps1"
Write-Host "  Voces del doblaje (RVC):  .\install-rvc.ps1   (opcional, ~1.5 GB)"
