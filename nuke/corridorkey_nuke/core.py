# -*- coding: utf-8 -*-
"""CorridorKey para Nuke: lógica sin dependencia de `nuke` (se prueba fuera de Nuke)."""
import json
import os
import re
import shutil
import subprocess

HOME_ENV = "CORRIDORKEY_HOME"
CREATE_NO_WINDOW = 0x08000000

# En GPUs de 16 GB o menos, 4K nativo solo entra con ventanas cortas y los knobs de memoria bajados
# (medido en un 4070 Ti de 12 GB: ventana 24 a 4K tumbó el PC con un BSOD).
LOW_MEM = ["--low_vram", "--low_vram_swin_window_batch", "8", "--low_vram_mlp_chunk_tokens", "32768"]
LOW_MEM_WINDOW = 8
LOW_MEM_MAX_MIB = 16384

# Ventana temporal máxima recomendada para una GPU de 12 GB según los megapíxeles procesados
# (tabla del README de CorridorKey: 720p 80, 1080p 24, 1440p y 4K 8).
WINDOW_LIMITS = ((1.0, 80), (2.2, 24), (float("inf"), 8))

# Despill en vivo (nodos Expression del Group). amt = fuerza; scr = 0 pantalla verde, 1 azul; sg/sb = exceso de verde
# o de azul. "avg" es la regla de CorridorKey (runtime.py:604); "max" es la suave: solo baja el canal de la pantalla
# hasta el mayor de los otros dos, así respeta amarillos y tonos cálidos.
SPILL = {"avg": ("max(g-(r+b)/2,0)", "max(b-(r+g)/2,0)"), "max": ("max(g-max(r,b),0)", "max(b-max(r,g),0)")}
DESPILL_EXPR = ("r+amt*((1-scr)*sg+scr*sb)/2", "g-amt*(1-scr)*sg+amt*scr*sb/2", "b+amt*(1-scr)*sg/2-amt*scr*sb")

# Tamaño en disco de un EXR half con compresión Zip, medido en un plate de prueba (HD y 4K dan lo mismo por megapíxel)
MB_PER_MPX_RGB, MB_PER_MPX_ALPHA = 4.2, 0.3
DISK_MARGIN_MB = 2048  # memmaps de --low_vram y holgura


def home():
    return os.environ.get(HOME_ENV) or os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "CorridorKey")


def load_config():
    path = os.path.join(home(), "config.json")
    if not os.path.isfile(path):
        raise RuntimeError("CorridorKey no está instalado (falta %s). Ejecuta instalar.bat." % path)
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    for k in ("python", "infer", "ffmpeg"):
        if not os.path.isfile(cfg.get(k, "")):
            raise RuntimeError("Instalación incompleta: no existe '%s' (%s). Vuelve a ejecutar instalar.bat."
                               % (k, cfg.get(k)))
    return cfg


def gpu_info():
    """(nombre, total MiB, libre MiB) de la primera GPU NVIDIA, o None si nvidia-smi no responde."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15, creationflags=CREATE_NO_WINDOW).stdout
        name, total, free = [s.strip() for s in out.splitlines()[0].split(",")]
        return name, int(total), int(free)
    except Exception:
        return None


def build_argv(cfg, in_dir, out_dir, fps, outputs, temp_dir, hint_dir=None, hint_quality=0.75,
               despill=0.5, low_mem=False, window=None):
    """window = frames de la ventana temporal (1 = frame a frame); None = automática, o 8 si low_mem."""
    argv = [cfg["python"], cfg["infer"], "--input", in_dir, "--output_dir", out_dir,
            "--frame_dir_linear", "--frame_dir_fps", str(fps), "--output_format", "exr",
            "--outputs"] + list(outputs) + [
            "--despill_strength", str(despill), "--ffmpeg_bin", cfg["ffmpeg"], "--temp_dir", temp_dir]
    if hint_dir:
        argv += ["--hint_video", hint_dir, "--hint_quality", str(hint_quality)]
    if low_mem:
        argv += LOW_MEM
        window = window or LOW_MEM_WINDOW
    if window:
        argv += ["--hann_chunk", str(window), "--hann_stride", str(max(1, window // 2))]
    return argv


def window_limit(width, height):
    """Ventana temporal máxima recomendada en una GPU de 12 GB para esa resolución de proceso."""
    mpx = width * height / 1e6
    return next(w for m, w in WINDOW_LIMITS if mpx <= m)


def disk_need_mb(width, height, n, convert):
    """(MB en la carpeta temporal, MB en la carpeta de salida) para procesar n frames a width x height.
    Temporal: el clip convertido (si hay que convertirlo) + alpha y fg; salida: alpha y fg (al reemplazar una versión,
    los archivos viejos conviven un momento con los nuevos)."""
    mpx = width * height / 1e6
    out = n * mpx * (MB_PER_MPX_RGB + MB_PER_MPX_ALPHA)
    return out + (n * mpx * MB_PER_MPX_RGB if convert else 0), out


def free_mb(path):
    """MB libres en la unidad de `path` (sube hasta una carpeta que exista)."""
    p = os.path.abspath(path)
    while not os.path.exists(p) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    return shutil.disk_usage(p).free / 2 ** 20


def disk_problems(needs, free=free_mb):
    """needs = [(carpeta, MB)]. Suma por unidad y devuelve una línea por unidad sin espacio suficiente."""
    by_drive = {}
    for path, mb in needs:
        drive = os.path.splitdrive(os.path.abspath(path))[0].upper() or path
        by_drive.setdefault(drive, [path, 0.0])[1] += mb
    out = []
    for drive, (path, mb) in sorted(by_drive.items()):
        need, have = mb + DISK_MARGIN_MB, free(path)
        if have < need:
            out.append("%s necesita ~%.1f GB y tiene %.1f GB libres" % (drive, need / 1024, have / 1024))
    return out


def output_dir(out_dir, in_dir, kind):
    """infer.py escribe <output_dir>/<nombre de la carpeta de entrada>_<salida>_exr/."""
    return os.path.join(out_dir, "%s_%s_exr" % (os.path.basename(os.path.normpath(in_dir)), kind))


def progress(log_text, written, n_frames):
    """(fracción 0-1, mensaje) a partir del log de infer.py y de cuántos frames ya se escribieron."""
    m = re.findall(r"window (\d+)/(\d+)", log_text)
    if not m:
        return 0.02, "Cargando modelos…"
    a, b = int(m[-1][0]), int(m[-1][1])
    if a < b or written == 0:
        return 0.7 * a / b, "Etapa 1: ventana %d de %d" % (a, b)
    return 0.7 + 0.3 * min(written, n_frames) / max(n_frames, 1), "Etapa 2: frame %d de %d" % (written, n_frames)


def exit_code(log_text):
    m = re.findall(r"CK_EXIT=(\d)", log_text)
    return int(m[-1]) if m else None


def log_tail(log_text, n=12):
    lines = [l for l in log_text.replace("\r", "\n").splitlines() if l.strip()]
    return "\n".join(lines[-n:])


def _ps_quote(s):
    return "'" + s.replace("'", "''") + "'"


def _powershell(cmd):
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                          capture_output=True, text=True, timeout=60, creationflags=CREATE_NO_WINDOW).stdout


def spawn_detached(argv, cwd, log):
    """Lanza argv oculto y fuera del árbol de procesos de Nuke (WMI); devuelve el PID de cmd.exe.

    Como hijo de Nuke 17 algunos torch no cargan (c10.dll, WinError 1114; medido con el de ComfyUI):
    por WMI el proceso recibe el entorno normal del usuario. El log termina con CK_EXIT=<código>.
    shortcut: solo Windows, como el resto del instalador."""
    inner = ('set PYTHONIOENCODING=utf-8&& set PYTHONUTF8=1&& %s > "%s" 2>&1 && echo CK_EXIT=0 >> "%s" '
             '|| echo CK_EXIT=1 >> "%s"' % (subprocess.list2cmdline(argv), log, log, log))
    out = _powershell(
        "$si = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ShowWindow=[uint16]0}; "
        "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
        "@{CommandLine=%s; CurrentDirectory=%s; ProcessStartupInformation=$si}; "
        "\"$($r.ReturnValue) $($r.ProcessId)\"" % (_ps_quote('cmd.exe /c "%s"' % inner), _ps_quote(cwd))).split()
    if len(out) != 2 or out[0] != "0":
        raise RuntimeError("No se pudo lanzar CorridorKey (Win32_Process.Create: %s)" % " ".join(out))
    return int(out[1])


def kill(pid):
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=30,
                   creationflags=CREATE_NO_WINDOW)


def safe_rmtree(path, base, ignore_errors=False):
    """Borra `path` solo si está estrictamente dentro de `base` (las carpetas de trabajo del plugin).
    ignore_errors=True borra todo lo que pueda y sigue (Windows no deja borrar archivos que Nuke tiene abiertos)."""
    p, b = os.path.abspath(path), os.path.abspath(base)
    if not p.lower().startswith(b.lower() + os.sep):
        raise RuntimeError("Me niego a borrar fuera de la carpeta de trabajo: %s" % path)
    if os.path.isdir(p):
        shutil.rmtree(p, ignore_errors=ignore_errors)


def clip_base(path):
    """Nombre de una secuencia sin extensión ni número de frame: 'X_aPlate_v001.%04d.exr' -> 'X_aPlate_v001'."""
    name = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"(\.|_)?(%0?\d*d|#+)$|[._]\d{4,}$", "", name) or name


def prerenders_dir(script_path):
    """<depto>/2_prerenders, al lado de la carpeta 1_projects que contiene el script; None si no está en esa estructura."""
    d = os.path.dirname(os.path.abspath(script_path))
    while os.path.basename(d).lower() != "1_projects":
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up
    return os.path.join(os.path.dirname(d), "2_prerenders")


def result_path(out_base, name, kind, version):
    """Secuencia final: <out_base>/<name>_<kind>_v01/<name>_<kind>_v01.%04d.exr (la convención de 2_prerenders)."""
    n = "%s_%s_v%02d" % (name, kind, version)
    return os.path.join(out_base, n, n + ".%04d.exr")


def publish(jobs, first):
    """jobs = [(carpeta con los .exr nuevos, patrón `%04d` de destino)]. Mueve cada secuencia a `pattern % frame` desde
    `first`, reemplazando lo que hubiera en la carpeta de destino.
    Todo o nada ENTRE TODAS las secuencias: primero aparta los archivos viejos de todas; si Nuke tiene alguno abierto
    (Windows no deja moverlo) deja todo como estaba y falla, en vez de dejar frames viejos mezclados con nuevos o una
    secuencia nueva junto a otra vieja."""
    aside, placed, dst = [], [], None

    def rollback():
        for p in placed:
            os.remove(p)
        for p in aside:
            os.replace(p + ".old", p)

    try:
        for _, pattern in jobs:
            dst = os.path.dirname(pattern)
            os.makedirs(dst, exist_ok=True)
            for f in os.listdir(dst):
                if f.lower().endswith(".exr"):
                    p = os.path.join(dst, f)
                    os.replace(p, p + ".old")
                    aside.append(p)
    except OSError as e:
        rollback()
        raise RuntimeError("Hay frames abiertos en %s y no se pueden reemplazar (¿otro Read del script con esta "
                           "secuencia?). Sube la versión para conservar la anterior, o desactiva ese Read y vuelve a "
                           "intentar.\n(%s)" % (dst, e))
    try:
        for src_dir, pattern in jobs:
            for i, f in enumerate(sorted(f for f in os.listdir(src_dir) if f.lower().endswith(".exr"))):
                placed.append(shutil.move(os.path.join(src_dir, f), pattern % (first + i)))
    except Exception:
        rollback()
        raise
    for p in aside:
        try:
            os.remove(p + ".old")
        except OSError:
            pass  # queda un .old suelto: no afecta a la secuencia


def read_log(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""
