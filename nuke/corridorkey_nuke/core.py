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
RELEVO_QUALITY = 0.95  # confianza en el alpha de un tramo como hint del otro; = arrastre entre ventanas de CorridorKey
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


def split_at(in_dir, work, base, k):
    """Tramos para un hint en el frame k (desde 0) del clip: CorridorKey solo acepta el hint en el primer frame, así que
    se procesa k..fin hacia adelante y el resto con el clip invertido. Cada tramo es una carpeta de enlaces a los EXR ya
    convertidos, nombrados en el orden en que se procesan (infer.py los lee por nombre).
    El frame con hint sale distinto de sus vecinos propagados (medido: salta por los dos lados, ver ROADMAP). Por eso el
    tramo hacia atrás parte en k+1 y su hint es el alpha que el tramo hacia adelante dio ahí ("relevo", hint_relevo):
    k sale propagado, igual que sus vecinos, y merge_tramos descarta de cada tramo su frame con hint.
    Devuelve [{"in", "frames", "label", "relevo"}]; frames = posición en el clip de cada frame del tramo, en ese orden."""
    files = sorted(f for f in os.listdir(in_dir) if f.lower().endswith(".exr"))
    n, specs, tramos = len(files), [], []
    if k < n - 1 or n == 1:  # referencia en el último frame: solo hacia atrás, con el hint del artista
        specs.append(("adelante", range(k, n), "hacia adelante", False))
    if k > 0:
        specs.append(("atras", range(min(k + 1, n - 1), -1, -1), "hacia atrás", k < n - 1))
    for name, idx, label, relevo in specs:
        d = os.path.join(work, name)
        safe_rmtree(d, base)
        os.makedirs(d)
        for j, i in enumerate(idx):
            src, dst = os.path.join(in_dir, files[i]), os.path.join(d, "plate.%06d.exr" % j)
            try:
                os.link(src, dst)  # misma unidad: no ocupa disco
            except OSError:
                shutil.copyfile(src, dst)
        tramos.append({"in": d, "frames": list(idx), "label": label, "relevo": relevo})
    return tramos


def hint_relevo(tramos, outs, t):
    """Hint de un tramo con relevo: el alpha que el primer tramo (outs[0]) ya escribió para el frame donde parte t."""
    src = output_dir(outs[0], tramos[0]["in"], "alpha")
    files = sorted(f for f in os.listdir(src) if f.lower().endswith(".exr"))
    return os.path.join(src, files[tramos[0]["frames"].index(t["frames"][0])])


def merge_tramos(tramos, outs, dst, in_dir, kinds):
    """Junta lo que escribió infer.py en cada tramo (outs[i] = su carpeta de salida) en la carpeta de una corrida
    normal (output_dir(dst, in_dir, kind)), en el orden del clip. Si un frame sale en dos tramos, se descarta el que
    es el frame con hint de su tramo y queda el propagado."""
    propagados = {i for t in tramos for i in t["frames"][1:]}
    for kind in kinds:
        d = output_dir(dst, in_dir, kind)
        os.makedirs(d, exist_ok=True)
        for t, out in zip(tramos, outs):
            src = output_dir(out, t["in"], kind)
            files = sorted(f for f in os.listdir(src) if f.lower().endswith(".exr"))
            if len(files) != len(t["frames"]):
                raise RuntimeError("El tramo %s escribió %d de %d frames en %s."
                                   % (t["label"], len(files), len(t["frames"]), src))
            for j, (f, i) in enumerate(zip(files, t["frames"])):
                p = os.path.join(d, "ck_%06d.exr" % i)
                if not (j == 0 and i in propagados) and not os.path.exists(p):
                    os.replace(os.path.join(src, f), p)


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


# Cola (0.8): cada nodo tiene en su carpeta de trabajo el trabajo que mandó (lo escribe Nuke) y su estado (lo escribe
# cola.py mientras corre; Nuke lo pasa a "publicado" al conectar el resultado).
JOB, STATE = "trabajo.json", "estado.json"
ACTIVE = ("en cola", "procesando")  # el proceso de fondo todavía tiene algo que hacer
FINAL = ("listo", "error", "cancelado")  # el proceso de fondo terminó; falta que Nuke lo publique o lo muestre


def write_json(path, data):
    """Escribe y reemplaza de una vez: quien lee nunca ve un archivo a medias."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    for i in range(20):  # Windows no deja reemplazar un archivo que el otro proceso tiene abierto en ese instante
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == 19:
                raise
            time.sleep(0.1)


def read_json(path):
    """El contenido, o None si no existe o no se puede leer."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def set_state(work, state, **info):
    write_json(os.path.join(work, STATE), dict(info, estado=state, t=time.time()))


def get_state(work):
    return read_json(os.path.join(work, STATE)) or {}


def retry_window(window, limit, log_text):
    """Tras quedarse sin memoria de GPU: (ventana que falló, ventana siguiente más chica o None si ya era frame a
    frame). Con ventana automática, la que falló es la que eligió CorridorKey o, si no la informó, la recomendada."""
    failed = window or auto_window(log_text) or limit
    return failed, smaller_window(failed)


def fmt_secs(secs):
    """132 -> '2 min 12 s'; 45 -> '45 s'."""
    secs = int(secs)
    return "%d min %02d s" % divmod(secs, 60) if secs >= 60 else "%d s" % secs


def job_progress(job, st, kind="alpha"):
    """(fracción 0-1, mensaje) de un trabajo según su estado y el log de infer.py. Con tramos (frame de referencia),
    el avance es el de todo el trabajo y el mensaje dice en qué tramo va."""
    if st.get("estado") != "procesando":
        return 0.0, "En cola: espera a que termine otro proceso de CorridorKey"
    work, tramos, i = job["work"], job.get("tramos"), st.get("tramo", 0)
    t = tramos[i] if tramos else {"in": os.path.join(work, "in"), "frames": range(job["n"])}
    watch = output_dir(os.path.join(work, st["out_name"]), t["in"], kind)
    frac, msg = progress(read_log(os.path.join(work, "run.log")), count_exr(watch), len(t["frames"]))
    if not tramos:
        return frac, msg
    done = sum(len(x["frames"]) for x in tramos[:i])
    total = sum(len(x["frames"]) for x in tramos)
    return (done + frac * len(t["frames"])) / total, "Tramo %s (%d de %d) · %s" % (t["label"], i + 1, len(tramos), msg)


STATE_LABELS = {"en cola": "En cola", "procesando": "Procesando", "listo": "Terminado, falta publicar",
                "publicado": "Publicado", "error": "Error", "cancelado": "Cancelado"}


def queue_rows(now=None, hours=24):
    """Los trabajos de todos los scripts, para el panel de la cola: primero el que se procesa, después los que esperan
    (en orden de llegada) y al final los terminados en las últimas `hours` horas, del más reciente al más viejo."""
    now = now or time.time()
    runs, rows = os.path.join(home(), "runs"), []
    for key in (os.listdir(runs) if os.path.isdir(runs) else []):
        for node in os.listdir(os.path.join(runs, key)) if os.path.isdir(os.path.join(runs, key)) else []:
            work = os.path.join(runs, key, node)
            st, job = get_state(work), read_json(os.path.join(work, JOB))
            state = st.get("estado")
            if not state or not job or state not in ACTIVE and now - st.get("t", 0) > hours * 3600:
                continue
            frac, detail = (None, "")
            if state == "procesando":
                try:
                    frac, detail = job_progress(job, st)
                except Exception:  # el log o la carpeta de salida cambian mientras se leen
                    frac = 0.0
            elif state == "error":  # la línea que dice qué pasó, no la ruta del log
                lines = [l for l in st.get("msg", "").splitlines() if l.strip() and not l.startswith("Log completo")]
                detail = lines[-1] if lines else ""
            secs = now - st.get("inicio", st.get("t", now)) if state == "procesando" else st.get("segundos")
            rows.append({"work": work, "estado": state, "texto": STATE_LABELS.get(state, state),
                         "shot": job.get("name") or node, "script": job.get("script") or key,
                         "node": job.get("node"), "avance": frac, "detalle": detail,
                         "tiempo": fmt_secs(secs) if secs is not None else "", "t": st.get("t", 0),
                         "msg": st.get("msg", "")})
    first = {"procesando": 0, "en cola": 1}
    rows.sort(key=lambda r: (first.get(r["estado"], 2), r["t"] if r["estado"] in ACTIVE else -r["t"]))
    return rows


def cancel_job(work):
    """Cancela un solo trabajo sin cortar la cola: si espera, la cola lo salta; si se está procesando, se corta su
    infer.py (cola.py anota el PID en infer.pid) y la cola sigue con el siguiente. False si ya no estaba activo."""
    st = get_state(work)
    if st.get("estado") not in ACTIVE:
        return False
    set_state(work, "cancelado", **{k: v for k, v in st.items() if k not in ("estado", "t")})
    if st["estado"] == "procesando":
        try:
            with open(os.path.join(work, "infer.pid")) as f:
                kill(int(f.read().strip()))
        except (OSError, ValueError):
            pass  # infer.py aún no arrancaba: la cola lo ve cancelado y no lo corre
    return True
