# run-cli.ps1 - genera una conversacion en video con preguntas guiadas.
# Todos los valores tienen un valor por defecto: pulsa Enter para aceptarlo.
# Uso:  .\run-cli.ps1

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host "=== Charla: conversacion en video ===" -ForegroundColor Cyan
Write-Host ""

# --- Input: tema, URL de noticia o guion manual ----------------------------
Write-Host "Puedes dar un tema libre ('los pulpos tienen tres corazones'),"
Write-Host "una URL de noticia (https://...) o dejarlo vacio para usar el"
Write-Host "guion de ejemplo sin gastar LLM."
$topic = Read-Host "Tema o URL [demo sin LLM]"

# --- Idioma y turnos -------------------------------------------------------
$language = "es"
$maxTurns = "12"
if ($topic) {
    $language = Read-Host "Idioma del dialogo (es/en/pt/fr...) [es]"
    if (-not $language) { $language = "es" }

    $maxTurns = Read-Host "Maximo de turnos de dialogo [12]"
    if (-not $maxTurns) { $maxTurns = "12" }
}

# --- Ambiente --------------------------------------------------------------
$bg = Read-Host "Volumen del audio ambiente del fondo 0..0.6 [0.15]"
if (-not $bg) { $bg = "0.15" }

# --- Construir y ejecutar --------------------------------------------------
if ($topic) {
    $cliArgs = @($topic, "--language", $language, "--max-turns", $maxTurns, "--bg-volume", $bg)
} else {
    $cliArgs = @("--script-file", "examples\demo_script.json", "--bg-volume", $bg)
}

Write-Host ""
Write-Host ("Ejecutando: charla " + ($cliArgs -join " ")) -ForegroundColor DarkGray
Write-Host ""
python -m charla.cli @cliArgs
exit $LASTEXITCODE
