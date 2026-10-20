# run-cli.ps1 - genera una conversacion en video con preguntas guiadas.
# Todos los valores tienen un valor por defecto: pulsa Enter para aceptarlo
# (los defaults salen de .env / config.py, no de este script).
# Uso:  .\run-cli.ps1

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
. "$PSScriptRoot\_python.ps1"
$py = Resolve-CharlaPython

Write-Host "=== Charla: conversacion en video ===" -ForegroundColor Cyan
Write-Host ""

# --- Input: tema, URL de noticia o guion manual ----------------------------
Write-Host "Puedes dar un tema libre ('los pulpos tienen tres corazones'),"
Write-Host "una URL de noticia (https://...), escribir ? para una lluvia de"
Write-Host "ideas (datos de ciencia verificados), o dejarlo vacio para usar el"
Write-Host "guion de ejemplo sin gastar LLM."
$topic = Read-Host "Tema o URL [demo sin LLM; ? = ideas]"

# --- Lluvia de ideas: elegir de una lista numerada ------------------------
while ($topic -eq "?") {
    & $py -m charla.batch --only-topics --count 8 | Out-Null
    $ideasFile = "output\_lote\temas_propuestos.txt"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $ideasFile)) {
        Write-Host "No se pudieron obtener ideas." -ForegroundColor Red
        $topic = Read-Host "Tema o URL [demo sin LLM]"
        break
    }
    $ideas = @(Get-Content $ideasFile -Encoding UTF8 | Where-Object { $_.Trim() })
    Write-Host ""
    foreach ($idea in $ideas) { Write-Host "  $idea" }
    $pick = Read-Host "Numero de la idea (Enter = otras ideas, t = escribir tema)"
    if ($pick -match '^\d+$' -and [int]$pick -ge 1 -and [int]$pick -le $ideas.Count) {
        $topic = $ideas[[int]$pick - 1] -replace '^\s*\d+\.\s*', ''
        Write-Host "Tema elegido: $topic" -ForegroundColor Green
    } elseif ($pick -eq "t") {
        $topic = Read-Host "Tema o URL [demo sin LLM]"
    }
}

$cliArgs = @()
if ($topic) {
    $cliArgs += $topic
    $language = Read-Host "Idioma del dialogo (es/en/pt/fr...) [por defecto]"
    if ($language) { $cliArgs += @("--language", $language) }

    $maxTurns = Read-Host "Maximo de turnos de dialogo [por defecto]"
    if ($maxTurns) { $cliArgs += @("--max-turns", $maxTurns) }

    $provider = Read-Host "Proveedor de texto (auto/claude/gemini/ollama) [auto]"
    if ($provider) { $cliArgs += @("--text-provider", $provider) }
} else {
    $cliArgs += @("--script-file", "examples\demo_script.json")
}

# --- Ambiente --------------------------------------------------------------
$bg = Read-Host "Volumen del audio ambiente del fondo 0..0.6 [por defecto: sin ambiente]"
if ($bg) { $cliArgs += @("--bg-volume", $bg) }

# --- Ejecutar --------------------------------------------------------------
Write-Host ""
Write-Host ("Ejecutando: charla " + ($cliArgs -join " ")) -ForegroundColor DarkGray
Write-Host ""
& $py -m charla.cli @cliArgs
exit $LASTEXITCODE
