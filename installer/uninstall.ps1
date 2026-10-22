# CorridorKey para Nuke - desinstalador (archivo UTF-8 con BOM). Opciones: -Root  -NukeDir  -Yes (sin preguntar)
param(
    [string]$Root = (Join-Path $env:LOCALAPPDATA 'CorridorKey'),
    [string]$NukeDir = (Join-Path $env:USERPROFILE '.nuke'),
    [switch]$Yes
)
$ErrorActionPreference = 'Stop'
$Latin1 = [Text.Encoding]::GetEncoding(28591)

$menu = Join-Path $NukeDir 'menu.py'
if (Test-Path $menu) {
    $text = [IO.File]::ReadAllText($menu, $Latin1)
    $new = [regex]::Replace($text, '(?s)\r?\n?# >>> CorridorKey >>>.*?# <<< CorridorKey <<<\r?\n?', "`r`n")
    if ($new -ne $text) { [IO.File]::WriteAllText($menu, $new.TrimStart("`r", "`n"), $Latin1); Write-Host "Quité el bloque de CorridorKey de $menu" }
}
$plugin = Join-Path $NukeDir 'corridorkey_nuke'
if (Test-Path $plugin) { Remove-Item -Recurse -Force $plugin; Write-Host "Borré $plugin" }

if (Test-Path $Root) {
    $ok = $Yes
    if (-not $ok) { $ok = (Read-Host "¿Borrar también $Root (modelos, Python y resultados, ~10 GB)? [s/N]") -match '^[sSyY]' }
    if ($ok) { Remove-Item -Recurse -Force $Root; Write-Host "Borré $Root" } else { Write-Host "Dejé $Root sin tocar." }
}
Write-Host 'Listo.'
