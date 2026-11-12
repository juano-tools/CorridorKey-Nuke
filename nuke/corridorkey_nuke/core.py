# -*- coding: utf-8 -*-
"""CorridorKey para Nuke: lógica sin dependencia de `nuke` (se prueba fuera de Nuke)."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import time

HOME_ENV = "CORRIDORKEY_HOME"
CREATE_NO_WINDOW = 0x08000000

# En GPUs de 16 GB o menos, 4K nativo solo entra con ventanas cortas y los knobs de memoria bajados
# (medido en un 4070 Ti de 12 GB: ventana 24 a 4K tumbó el PC con un BSOD).
LOW_MEM = ["--low_vram", "--low_vram_swin_window_batch", "8", "--low_vram_mlp_chunk_tokens", "32768"]
# "Mínima": además baja los otros ajustes finos de --low_vram.
# shortcut: valores provisorios (la mitad de LOW_MEM), sin medir; ajustar cuando se midan en una GPU chica.
LOW_MEM_MIN = ["--low_vram", "--low_vram_swin_window_batch", "4", "--low_vram_mlp_chunk_tokens", "16384",
               "--low_vram_foundation_chunk", "1", "--low_vram_full_attn_query_chunk_tokens", "1024"]
LOW_MEM_WINDOW = 8
LOW_MEM_MAX_MIB = 16384

# Ventana temporal que elige CorridorKey según la memoria de la GPU y la resolución (tabla "Long Clips And Low VRAM"
# de su README). Columnas: hasta 720p, 1080p, 1440p y 4K, en megapíxeles procesados.
WINDOW_MPX = (1.0, 2.2, 3.9, float("inf"))
WINDOW_TABLE = ((4, (4, 2, 1, 1)), (6, (24, 8, 4, 2)), (8, (24, 8, 8, 4)), (12, (80, 24, 8, 8)),
                (16, (80, 48, 24, 8)), (24, (80, 48, 48, 8)), (32, (80, 80, 48, 24)), (48, (80, 80, 80, 48)))
WINDOWS = (80, 48, 24, 16, 8, 4, 2, 1)  # de mayor a menor: el orden en que se reintenta si falta memoria

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


def gpu_processes(min_mib=300, top=4):
    """[(nombre, MiB)] de los procesos que más memoria de GPU ocupan, de mayor a menor; [] si no se puede saber.
    nvidia-smi no informa memoria por proceso en Windows: se leen los contadores de rendimiento.
    shortcut: el nombre del contador está en inglés; en un Windows en otro idioma devuelve [] y el aviso sale sin detalle."""
    try:
        out = _powershell(
            "Get-Counter '\\GPU Process Memory(*)\\Dedicated Usage' -ErrorAction Stop | "
            "Select-Object -ExpandProperty CounterSamples | Where-Object CookedValue -gt %d | ForEach-Object { "
            "$p = [int]($_.InstanceName -replace '^pid_(\\d+)_.*','$1'); "
            "$c = Get-CimInstance Win32_Process -Filter \"ProcessId=$p\"; "
            "'{0}|{1}|{2}' -f [int]($_.CookedValue/1MB), $c.Name, $c.CommandLine }" % (min_mib * 2 ** 20))
    except Exception:
        return []
    found = []
    for line in out.splitlines():
        mib, _, rest = line.partition("|")
        name, _, cmd = rest.partition("|")
        if mib.strip().isdigit() and name:
            found.append((process_label(name, cmd), int(mib)))
    return sorted(found, key=lambda x: -x[1])[:top]


def process_label(name, cmdline):
    """Nombre para mostrar: un python.exe no dice nada, así que se reconoce ComfyUI por su línea de comandos."""
    name = re.sub(r"\.exe$", "", name.strip(), flags=re.I)
    if name.lower().startswith("python") and "comfy" in cmdline.lower():
        return "ComfyUI (%s)" % ("modelo de SHARP" if "sharp-nodes" in cmdline.lower() else "python")
    return {"dwm": "escritorio de Windows (dwm)"}.get(name.lower(), name)


def build_argv(cfg, in_dir, out_dir, fps, outputs, temp_dir, hint_dir=None, hint_quality=0.75,
               despill=0.5, low_mem=False, window=None, hint_first=False, carry_quality=None, no_carry=False):
    """window = frames de la ventana temporal (1 = frame a frame); None = automática, o 8 si low_mem.
    hint_first = hint_dir trae un solo frame (--hint_first_frame) en vez de uno por frame (--hint_video).
    no_carry = el hint manda en todos los frames (sin arrastrar la predicción del modelo); carry_quality = confianza
    en ese arrastre (CorridorKey: 0.95)."""
    argv = [cfg["python"], cfg["infer"], "--input", in_dir, "--output_dir", out_dir,
            "--frame_dir_linear", "--frame_dir_fps", str(fps), "--output_format", "exr",
            "--outputs"] + list(outputs) + [
            "--despill_strength", str(despill), "--ffmpeg_bin", cfg["ffmpeg"], "--temp_dir", temp_dir]
    if hint_dir:
        argv += ["--hint_first_frame" if hint_first else "--hint_video", hint_dir, "--hint_quality", str(hint_quality)]
        if no_carry:
            argv.append("--no_carry_hint")
        elif carry_quality is not None:
            argv += ["--carry_hint_quality", str(carry_quality)]
    if low_mem:  # True = memoria baja; "min" = mínima
        argv += LOW_MEM_MIN if low_mem == "min" else LOW_MEM
        window = window or LOW_MEM_WINDOW
    if window:
        argv += ["--hann_chunk", str(window), "--hann_stride", str(max(1, window // 2))]
    return argv


def window_limit(width, height, total_mib=12288):
    """Ventana temporal recomendada para esa resolución de proceso en una GPU con total_mib de memoria."""
    gb = round(total_mib / 1024.0)  # una tarjeta de 12 GB informa 12282 MiB
    row = [w for g, w in WINDOW_TABLE if g <= gb][-1:] or [WINDOW_TABLE[0][1]]
    col = next(i for i, m in enumerate(WINDOW_MPX) if width * height / 1e6 <= m)
    return row[0][col]


def smaller_window(window):
    """La ventana siguiente más chica de la escala; None si ya es frame a frame."""
    return next((w for w in WINDOWS if w < window), None)


def is_oom(log_text):
    t = log_text.lower()
    return "out of memory" in t or "outofmemoryerror" in t


def auto_window(log_text):
    """La ventana que eligió el modo automático de CorridorKey, según su log; None si no la informó."""
    m = re.findall(r"hann_chunk=(\d+)", log_text)
    return int(m[-1]) if m else None


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


def alive(pid):
    """¿Sigue vivo el proceso? (tasklist; ante la duda, sí)."""
    try:
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH", "/FO", "CSV"], capture_output=True,
                             text=True, timeout=30, creationflags=CREATE_NO_WINDOW).stdout
        return '"%d"' % pid in out
    except Exception:
        return True


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


def run_key(script_path):
    """Nombre de la carpeta de temporales de un script. No depende del número de versión (x_v012.nk y x_v013.nk
    comparten carpeta): así un "Guardar como" versión nueva reutiliza lo convertido en vez de acumular otra copia.
    shortcut: dos versiones del mismo script procesando el mismo nodo a la vez se pisarían; separar si llega a pasar."""
    p = re.sub(r"[._]v\d+(?=\.nk$)", "", script_path.replace("\\", "/"), flags=re.I)
    return "%s_%s" % (os.path.splitext(os.path.basename(p))[0], hashlib.sha1(p.encode("utf-8")).hexdigest()[:6])


def purge_old_runs(keep, days=14):
    """Borra las carpetas de temporales hermanas de `keep` que llevan más de `days` días sin uso (su fecha se
    renueva en cada Procesar). Son conversiones: si hacen falta, se vuelven a escribir."""
    runs, limit = os.path.dirname(os.path.abspath(keep)), time.time() - days * 86400
    for d in os.listdir(runs):
        p = os.path.join(runs, d)
        if os.path.isdir(p) and p != os.path.abspath(keep) and os.path.getmtime(p) < limit:
            safe_rmtree(p, runs, ignore_errors=True)


def count_exr(folder):
    return len([f for f in os.listdir(folder) if f.lower().endswith(".exr")]) if os.path.isdir(folder) else 0


def clip_base(path):
    """Nombre de una secuencia sin extensión ni número de frame: 'X_aPlate_v001.%04d.exr' -> 'X_aPlate_v001'."""
    name = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"(\.|_)?(%0?\d*d|#+)$|[._]\d{4,}$", "", name) or name


def frame_path(pattern, frame):
    """Archivo del frame `frame` en una secuencia escrita como 'x.%04d.exr' o 'x.####.exr' (las dos formas de Nuke)."""
    p = re.sub(r"#+", lambda m: "%%0%dd" % len(m.group()), pattern)
    return p % frame if "%" in p else p


def prerenders_dir(script_path):
    """<depto>/2_prerenders, al lado de la carpeta 1_projects que contiene el script; None si no está en esa estructura."""
    d = os.path.dirname(os.path.abspath(script_path))
    while os.path.basename(d).lower() != "1_projects":
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up
    return os.path.join(os.path.dirname(d), "2_prerenders")


def prerenders_from_clip(clip_path):
    """Para un script sin guardar: la carpeta 2_prerenders del shot al que pertenece el clip, subiendo desde su ruta.
    Si el clip ya está bajo un departamento (<depto>/2_prerenders/x/clip) es la de ese departamento; si está en otra
    parte del shot (<shot>/_input/x/clip), la de Comp. Solo si la carpeta ya existe: no se inventa estructura en el
    shot ni se escribe junto al plate. None si el clip no está en esa estructura."""
    d = os.path.dirname(os.path.abspath(clip_path))
    while True:
        if os.path.isdir(os.path.join(d, "2_prerenders")):
            return os.path.join(d, "2_prerenders")
        try:
            comp = next((x for x in os.listdir(d) if x.lower() == "comp"), None)  # con las mayúsculas del disco
        except OSError:
            comp = None
        if comp and os.path.isdir(os.path.join(d, comp, "2_prerenders")):
            return os.path.join(d, comp, "2_prerenders")
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


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
