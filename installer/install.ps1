# CorridorKey para Nuke - instalador para Windows PowerShell 5.1 (archivo UTF-8 con BOM: no lo guardes sin BOM).
# Uso normal: doble clic en instalar.bat. Opciones: -Root <carpeta>  -NukeDir <carpeta .nuke>  -OnlyNuke  -NoNuke
param(
    [string]$Root = (Join-Path $env:LOCALAPPDATA 'CorridorKey'),
    [string]$NukeDir = (Join-Path $env:USERPROFILE '.nuke'),
    [switch]$OnlyNuke,
    [switch]$NoNuke
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Version = '0.5.1'
$AppCommit = '485f5e9ab759ead6138cc990776184b59d6ea971'      # CorridorKey 2.0, 2026-10-15
$Utils3dCommit = '83bfa5bda008803f6521ce9547f94023b8afeddd'  # el que fija su requirements.txt
$PluginSrc = Join-Path (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)) 'nuke\corridorkey_nuke'
$Latin1 = [Text.Encoding]::GetEncoding(28591)  # bytes <-> chars 1 a 1: no tocamos los acentos del menu.py del usuario

function Step($m) { Write-Host ''; Write-Host "==> $m" -ForegroundColor Cyan }

function Run($exe, [string[]]$a) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'   # pip escribe avisos por stderr
    & $exe @a
    $code = $LASTEXITCODE; $ErrorActionPreference = $prev
    if ($code -ne 0) { throw "Falló: $(Split-Path -Leaf $exe) $($a -join ' ') (código $code)" }
}

function Download($url, $dest) {
    Write-Host "Descargando $url"
    & curl.exe -L --fail --silent --show-error -o $dest $url
    if ($LASTEXITCODE -ne 0) { throw "No se pudo descargar $url (revisa la conexión, el proxy o el antivirus)." }
}

function Install-Plugin {
    Step "Instalando el menú en Nuke ($NukeDir)"
    if (-not (Test-Path $PluginSrc)) { throw "No encuentro el plugin en $PluginSrc" }
    New-Item -ItemType Directory -Force $NukeDir | Out-Null
    $dst = Join-Path $NukeDir 'corridorkey_nuke'
    if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
    Copy-Item $PluginSrc $dst -Recurse
    Get-ChildItem $dst -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
    $menu = Join-Path $NukeDir 'menu.py'
    $block = "# >>> CorridorKey >>>`r`nimport nuke`r`ntry:`r`n    import corridorkey_nuke`r`n    corridorkey_nuke.register()`r`n" +
             "except Exception as e:`r`n    nuke.tprint('CorridorKey: no se pudo cargar: %s' % e)`r`n# <<< CorridorKey <<<`r`n"
    $text = ''
    if (Test-Path $menu) {
        if (-not (Test-Path "$menu.bak_corridorkey")) { Copy-Item $menu "$menu.bak_corridorkey" }
        $text = [IO.File]::ReadAllText($menu, $Latin1)
    }
    $text = [regex]::Replace($text, '(?s)# >>> CorridorKey >>>.*?# <<< CorridorKey <<<\r?\n?', '')
    if ($text.Length -gt 0 -and -not $text.EndsWith("`n")) { $text += "`r`n" }
    [IO.File]::WriteAllText($menu, $text + $block, $Latin1)
    Write-Host "Menú agregado a $menu (copia de seguridad: menu.py.bak_corridorkey)"
}

New-Item -ItemType Directory -Force $Root | Out-Null
Start-Transcript -Path (Join-Path $Root 'install.log') -Append | Out-Null
$exit = 0
try {
    if (-not $OnlyNuke) {
        Step 'Revisando la GPU NVIDIA'
        $smi = (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue).Source
        if (-not $smi) { $smi = Join-Path $env:SystemRoot 'System32\nvidia-smi.exe' }
        if (-not (Test-Path $smi)) { throw 'No encuentro nvidia-smi: CorridorKey necesita una GPU NVIDIA RTX serie 30 o más nueva, con el driver instalado.' }
        $row = ((& $smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits | Select-Object -First 1) -split ',') | ForEach-Object { $_.Trim() }
        $gpuName = $row[0]; $gpuMiB = [int]$row[1]; $driver = $row[2]
        Write-Host "GPU: $gpuName, $gpuMiB MiB, driver $driver"
        if ($gpuMiB -lt 4000) { throw "La GPU tiene $gpuMiB MiB de VRAM; CorridorKey necesita al menos 4 GB." }
        if ([int]($driver.Split('.')[0]) -lt 570) { throw "El driver NVIDIA $driver es antiguo: actualiza a la versión 570 o superior (nvidia.com/drivers)." }
        if ($gpuName -notmatch 'RTX (30|40|50|A|PRO)') { Write-Warning 'CorridorKey está probado en RTX serie 30 o más nueva; en esta GPU puede no funcionar.' }
        $freeGB = (Get-PSDrive ((Split-Path -Qualifier $Root).TrimEnd(':'))).Free / 1GB
        if ($freeGB -lt 15) { throw ('Hay {0:N1} GB libres en la unidad de instalación; se necesitan unos 15 GB.' -f $freeGB) }

        Step 'Preparando herramientas (uv)'
        $uvDir = Join-Path $Root 'tools'; $uv = Join-Path $uvDir 'uv.exe'
        if (-not (Test-Path $uv)) {
            New-Item -ItemType Directory -Force $uvDir | Out-Null
            $zip = Join-Path $uvDir 'uv.zip'
            Download 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' $zip
            Expand-Archive $zip -DestinationPath $uvDir -Force
            Remove-Item $zip
            if (-not (Test-Path $uv)) { Copy-Item (Get-ChildItem $uvDir -Recurse -Filter uv.exe | Select-Object -First 1).FullName $uv }
        }

        Step 'Creando el entorno de Python 3.12 (no toca tu Python)'
        $env:UV_PYTHON_INSTALL_DIR = Join-Path $Root 'python'
        $env:UV_CACHE_DIR = Join-Path $Root 'uv-cache'
        $py = Join-Path $Root 'venv\Scripts\python.exe'
        if (-not (Test-Path $py)) { Run $uv @('venv', '--seed', '--managed-python', '--python', '3.12', (Join-Path $Root 'venv')) }

        Step 'Descargando CorridorKey 2.0'
        $app = Join-Path $Root 'app'
        if (-not (Test-Path (Join-Path $app 'infer.py'))) {
            $zip = Join-Path $Root 'app.zip'; $tmpx = Join-Path $Root 'app_tmp'
            Download "https://github.com/nikopueringer/CorridorKey2.0/archive/$AppCommit.zip" $zip
            if (Test-Path $tmpx) { Remove-Item -Recurse -Force $tmpx }
            Expand-Archive $zip -DestinationPath $tmpx -Force
            if (Test-Path $app) { Remove-Item -Recurse -Force $app }
            Move-Item (Get-ChildItem $tmpx -Directory | Select-Object -First 1).FullName $app
            Remove-Item -Recurse -Force $tmpx; Remove-Item $zip
        }

        Step 'Instalando PyTorch con CUDA (unos 3 GB: tarda varios minutos)'
        Run $py @('-m', 'pip', 'install', '--no-cache-dir', '--disable-pip-version-check', 'torch==2.9.1', 'torchvision==0.24.1',
                  '--index-url', 'https://download.pytorch.org/whl/cu128')

        Step 'Instalando dependencias'
        # utils3d viene de git en su requirements.txt; usamos el zip del mismo commit para no exigir git
        $req = Join-Path $Root 'requirements.windows.txt'
        $lines = Get-Content (Join-Path $app 'requirements.txt') | ForEach-Object {
            if ($_ -match '^utils3d') { "utils3d @ https://github.com/EasternJournalist/utils3d/archive/$Utils3dCommit.zip" } else { $_ } }
        [IO.File]::WriteAllText($req, (($lines + 'imageio-ffmpeg') -join "`n") + "`n", $Latin1)
        Run $py @('-m', 'pip', 'install', '--no-cache-dir', '--disable-pip-version-check', '-r', $req)

        Step 'Descargando los modelos (unos 3,5 GB)'
        Push-Location $app
        try { Run $py @('scripts\download_weights.py') } finally { Pop-Location }

        Step 'Verificando'
        $ff = ((& $py -c 'import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())') | Select-Object -Last 1).Trim()
        if (-not (Test-Path $ff)) { throw 'No se encontró el ffmpeg incluido.' }
        Run $py @('-c', 'import torch;assert torch.cuda.is_available(), "torch no ve la GPU";print("torch", torch.__version__, torch.cuda.get_device_name(0))')
        foreach ($f in 'weights\corridorkey_v2.safetensors', 'weights\foundation_stats.safetensors') {
            if (-not (Test-Path (Join-Path $app $f))) { throw "Falta ${f}: la descarga de modelos no terminó." }
        }
        $cfg = [ordered]@{ version = $Version; python = $py; infer = (Join-Path $app 'infer.py'); ffmpeg = $ff; app_commit = $AppCommit }
        [IO.File]::WriteAllText((Join-Path $Root 'config.json'), ($cfg | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
    }
    if (-not $NoNuke) { Install-Plugin }
    Write-Host ''
    Write-Host 'Listo. Reinicia Nuke: aparece el menú CorridorKey en la barra superior.' -ForegroundColor Green
    Write-Host "Instalado en: $Root"
}
catch {
    Write-Host ''
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "El detalle está en $(Join-Path $Root 'install.log'). Envíalo a quien mantiene el instalador."
    $exit = 1
}
finally { Stop-Transcript | Out-Null }
exit $exit
