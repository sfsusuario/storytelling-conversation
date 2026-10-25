# _python.ps1 - helpers compartidos por install.ps1, run-gradio.ps1, run-web.ps1, run-lote.ps1 y run-cli.ps1.
# Se carga con dot-source:  . "$PSScriptRoot\_python.ps1"
#
# Problema que resuelve: una terminal abierta ANTES de instalar Python (p. ej.
# la de VS Code) hereda un PATH viejo, y "python" cae en el alias de la
# Microsoft Store (WindowsApps\python.exe), que solo imprime
# "Python was not found". Aqui se reconstruye el PATH desde el registro y se
# busca un Python real (3.11+).

function Update-SessionPath {
    # venv activo -> Machine -> User -> lo que quede del PATH actual, sin
    # duplicados (un venv activado sigue teniendo prioridad).
    $parts = @()
    if ($env:VIRTUAL_ENV) { $parts += (Join-Path $env:VIRTUAL_ENV 'Scripts') }
    $parts += [Environment]::GetEnvironmentVariable('Path', 'Machine') -split ';'
    $parts += [Environment]::GetEnvironmentVariable('Path', 'User') -split ';'
    $parts += $env:Path -split ';'
    $seen = @{}
    $clean = foreach ($p in $parts) {
        $p = [Environment]::ExpandEnvironmentVariables($p.Trim())
        if ($p -and -not $seen.ContainsKey($p.ToLower())) {
            $seen[$p.ToLower()] = $true
            $p
        }
    }
    $env:Path = ($clean -join ';')
}

function Test-CharlaPython([string]$exe) {
    # True si $exe es un Python 3.11+ de verdad (el alias de la Store sale
    # con error 9009 sin imprimir nada).
    try {
        $out = & $exe -c "import sys; print(sys.version_info >= (3, 11))" 2>$null
        return ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq 'True')
    } catch { return $false }
}

function Resolve-CharlaPython {
    Update-SessionPath
    $candidates = @()
    $candidates += Get-Command python -All -CommandType Application -ErrorAction SilentlyContinue |
                   Where-Object { $_.Source -notmatch '\\WindowsApps\\' } |
                   ForEach-Object { $_.Source }
    $candidates += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
                   Sort-Object FullName -Descending | ForEach-Object { $_.FullName }
    # Un Python real instalado desde la Store tambien vive en WindowsApps:
    # se acepta solo si responde de verdad.
    $candidates += Get-Command python -All -CommandType Application -ErrorAction SilentlyContinue |
                   Where-Object { $_.Source -match '\\WindowsApps\\' } |
                   ForEach-Object { $_.Source }
    foreach ($c in ($candidates | Select-Object -Unique)) {
        if (Test-CharlaPython $c) { return $c }
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($v in '-3.13', '-3.12', '-3.11') {
            $exe = & $py.Source $v -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe -and (Test-CharlaPython "$exe".Trim())) {
                return "$exe".Trim()
            }
        }
    }
    Write-Host "ERROR: no se encontro un Python 3.11+ utilizable." -ForegroundColor Red
    Write-Host "  - Instala Python desde https://www.python.org/downloads/ (marca 'Add to PATH')."
    Write-Host "  - Si 'python' abre la Microsoft Store: Configuracion > Aplicaciones >"
    Write-Host "    Configuracion avanzada > Alias de ejecucion de aplicaciones, y desactiva"
    Write-Host "    'python.exe' / 'python3.exe'."
    exit 1
}
