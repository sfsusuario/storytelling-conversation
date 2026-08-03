# gen-code-zip.ps1 - regenera charla_code.zip (el codigo que consume el modo Colab).
# Incluye: src/, scripts/, examples/, pyproject.toml y .env (claves de API).
# Uso:  .\gen-code-zip.ps1   y luego reemplaza charla_code.zip en MyDrive/charla/

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

python scripts\gen_code_zip.py
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR generando el zip" -ForegroundColor Red; exit 1 }
Write-Host "Listo. Reemplaza charla_code.zip en tu Drive (MyDrive/charla/) y re-ejecuta la celda 1 del cuaderno." -ForegroundColor Green
