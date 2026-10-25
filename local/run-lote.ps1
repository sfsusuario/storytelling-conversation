# run-lote.ps1 - lote automatico: varios videos de ciencia de principio a fin
# con Ollama (guion local, sin claves de API).
#   - temas: banco de datos verificados (por defecto) o propuestos por Ollama
#   - por cada tema: guion (Ollama) -> voz -> video
#   - al final: output\_lote\<fecha>\ con los videos numerados y
#     publicar.txt (titulo + descripcion + hashtags para pegar)
# Uso:  .\run-lote.ps1      (Enter acepta el valor por defecto)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
. "$PSScriptRoot\_python.ps1"
$py = Resolve-CharlaPython

Write-Host "=== Charla: lote automatico con Ollama ===" -ForegroundColor Cyan
Write-Host ""

$count = Read-Host "Cuantos videos [3]"
if (-not $count) { $count = "3" }

Write-Host ""
Write-Host "Origen de los temas:"
Write-Host "  1) banco de datos verificados (recomendado, no se repiten)"
Write-Host "  2) propuestos por Ollama (revisalos: los modelos locales inventan cifras)"
$src = Read-Host "Opcion [1]"
$source = if ($src -eq "2") { "ollama" } else { "bank" }

$cliArgs = @("--count", $count, "--source", $source)
$theme = Read-Host "Tema general (p. ej. astronomia, cuerpo humano) [ciencia y datos curiosos]"
if ($theme) { $cliArgs += @("--theme", $theme) }

$model = Read-Host "Modelo de Ollama para los guiones [por defecto]"
if ($model) { $cliArgs += @("--model", $model) }

$tts = Read-Host "Motor de voz (edge/chatterbox) [por defecto]"
if ($tts) { $cliArgs += @("--tts", $tts) }

Write-Host ""
Write-Host ("Ejecutando: charla-lote " + ($cliArgs -join " ")) -ForegroundColor DarkGray
Write-Host ""
& $py -m charla.batch @cliArgs
exit $LASTEXITCODE
