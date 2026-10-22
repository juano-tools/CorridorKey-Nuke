# -*- coding: utf-8 -*-
"""Nodo CorridorKey para Nuke: un Group con las entradas `clip` y `hint` y un botón Procesar.

Probado para Nuke 15.1 y 17 (solo API estándar). Los resultados viven dentro del Group (Reads + Switch), así que
el nodo se guarda con el script y entrega el cutout; el desplegable `Ver` cambia entre cutout, alpha, fg, fg + alpha
(straight) y el clip. El modelo solo entrega alpha y fg: el despill y el cutout se calculan en vivo dentro del nodo.
Los EXR de resultado se guardan en la carpeta de salida (por defecto <depto>/2_prerenders); los temporales, en la PC."""
import hashlib
import os
import time

import nuke

from . import core

FORMAT_VERSION = "1"  # súbela si cambia cómo se escribe el plate: invalida lo ya convertido
KINDS = ("alpha", "fg")  # lo que entrega el modelo y se guarda; el cutout y el straight se calculan en vivo
OUTPUT_ITEMS = ["cutout", "alpha", "fg", "fg + alpha (straight)", "clip original"]  # = entradas 0..4 del Switch `sw`
DESPILL_ITEMS = ["Average (CorridorKey)", "Máximo (suave)", "Ninguno"]  # = entradas 0..2 del Switch `dsp_sw`
SCREEN_ITEMS = ["Verde", "Azul"]  # = parent.despill_color en las expresiones (core.DESPILL_EXPR)
WINDOW_ITEMS = ["Auto", "Frame a frame", "8", "16", "24", "48", "80"]
# (nombre en el desplegable, ancho al que se reduce dentro del nodo (None = el del clip), cómo lo nombra el estado)
RES = (("HD (recomendado)", 1920.0, "HD interno"), ("720p (liviano)", 1280.0, "720p interno"),
       ("Nativa", None, "resolución nativa"))
RES_ITEMS = [r[0] for r in RES]
LOW_MEM_MIN_PIXELS = 3.0e6  # por encima de ~1440p las ventanas largas no entran en una GPU de 12 GB

TIPS = {
    "resolution": (
        "HD (recomendado): el clip se reduce a 1920 px de ancho DENTRO del nodo y el resultado vuelve al tamaño "
        "original. No pongas un Reformat antes: no hace falta y, si lo pones, el resultado saldrá a ese tamaño reducido.\n\n"
        "720p (liviano): igual, pero a 1280 px de ancho. Para equipos con poca memoria de GPU o para una prueba "
        "rápida: es más rápido y usa menos memoria, a costa de menos detalle en los bordes (pelo fino, motion blur).\n\n"
        "Nativa: procesa a la resolución del clip (en 4K es unas 4 veces más lento). En una GPU de 12 GB usa ventanas "
        "temporales cortas, así que conviene conectar un hint.\n\n"
        "Un clip que ya es más chico que el ancho elegido no se agranda."),
    "first": ("Primer frame a procesar. Sigue al rango del clip conectado; si lo cambias a mano se respeta "
              "(el botón 'Rango del clip' lo vuelve a tomar del clip)."),
    "last": "Último frame a procesar. Sigue al rango del clip conectado; si lo cambias a mano se respeta.",
    "range_btn": "Vuelve a poner Primer y Último frame según el rango del clip conectado.",
    "hint_quality": (
        "Solo se usa si conectas la entrada hint (un matte del sujeto, blanco = sujeto; se usa su alpha, o su canal "
        "rojo si no tiene alpha). Cuánto confía el modelo en tu matte:\n"
        "0.95 = matte de artista (roto), 0.75 = matte automático o rough (un keyer rápido), 0.5 o menos = aproximado."),
    "despill_color": "Color de la pantalla: el despill baja ese canal (verde o azul).",
    "despill_mode": (
        "Despill que se aplica en vivo sobre el fg (cambiarlo no vuelve a procesar):\n"
        "Average (CorridorKey): el mismo del modelo. Baja el verde que supera el promedio de rojo y azul y reparte "
        "la mitad a cada uno.\n"
        "Máximo (suave): solo baja el verde que supera al mayor de rojo y azul, así respeta amarillos y tonos "
        "cálidos. Corrige menos que Average.\n"
        "Ninguno: deja el fg crudo. Úsalo si vas a despillar con otro nodo (DespillMadness, etc.): conecta ese nodo a "
        "la vista 'fg + alpha (straight)' y haz el Premult después.\n\n"
        "Si el fg ya viene limpio, el despill casi no cambia nada: es normal."),
    "window": (
        "Cuántos frames mira el modelo a la vez para que el key sea estable en el tiempo (más frames = menos "
        "parpadeo y mejor borde, pero más memoria de GPU).\n"
        "Auto: CorridorKey elige según la memoria libre (recomendado).\n"
        "Frame a frame: cada frame solo; el más liviano, puede parpadear.\n"
        "8 a 80: ventana fija. En GPUs de 16 GB o menos se usa siempre el modo de memoria baja, y si la ventana supera "
        "lo recomendado para la resolución (12 GB: 720p 80, HD 24, 4K 8) el nodo pide confirmación: en un PC de 12 GB "
        "una ventana de 24 en 4K lo colgó."),
    "despill": ("Fuerza del despill: 0 = nada, 1 = completo (CorridorKey usa 0.5 por defecto). Se ve al instante, "
                "sin Procesar."),
    "output": (
        "Qué muestra el nodo (cambiarlo no vuelve a procesar):\n"
        "cutout = el fg con el despill de abajo, premultiplicado por el alpha: listo para componer.\n"
        "alpha = el matte en gris.\nfg = foreground crudo (sin despill ni premultiplicar).\n"
        "fg + alpha (straight) = el fg crudo con el alpha en el canal alpha, SIN premultiplicar: para despillar con "
        "tu propio nodo y premultiplicar después.\nclip original = el clip sin keyear."),
    "run_btn": ("Procesa el clip con CorridorKey. Si el clip y el hint no cambiaron desde la última vez, reutiliza los "
                "archivos ya convertidos y no los reescribe."),
    "reconvert_btn": ("Reconvertir y procesar: vuelve a escribir el clip y el hint aunque parezcan iguales (por si "
                      "reemplazaste un archivo que Nuke no detecta) y procesa."),
    "clean_btn": ("Borra los temporales (clip y hint convertidos, que viven en tu PC). Los resultados de la carpeta de "
                  "salida no se tocan."),
    "open_btn": "Abre la carpeta de salida, donde quedan los EXR del resultado.",
    "out_dir": ("Dónde se guardan los EXR del resultado (alpha y fg, crudos, sin despill), listos para subir.\n"
                "Vacío = automático: la carpeta 2_prerenders del departamento (la que está junto a 1_projects, donde "
                "guardaste el script). Si el script no está en esa estructura, usa una carpeta de CorridorKey en tu PC."),
    "out_name": ("Nombre de los archivos. Aparece escrito el nombre automático (el del clip + _ck) para que lo "
                 "retoques: si lo cambias a mano se respeta; si lo borras, vuelve a ser automático.\n"
                 "Queda como <nombre>_<alpha|fg>_v01\\<nombre>_<...>_v01.1001.exr"),
    "version": ("Procesar REEMPLAZA los archivos de esta versión (no acumula espacio). Para conservar la anterior, "
                "sube el número antes de procesar: se crea una carpeta nueva (v02) y la v01 queda intacta."),
    "status": "Resultado de la última corrida.",
}
# Nuke no ajusta las líneas de este texto: en un panel angosto lo que no cabe se corta, por eso va en líneas cortas
NOTE = "clip: el plate tal cual, sin Reformat.\nhint (opcional): matte del sujeto."


def _pick(knob, *names):
    """Primer nombre de colorspace que exista en el config OCIO de este script (los nombres cambian de config en config)."""
    have = [v.split("\t")[0] for v in knob.values()]
    for n in names:
        if n in have:
            return n
    raise RuntimeError("El config de color no tiene ninguno de: %s" % ", ".join(names))


class _Temp(object):
    """Borra al salir los nodos que se crearon dentro del bloque (Write, Reformat y Shuffle temporales)."""

    def __enter__(self):
        self.before = {n.name() for n in nuke.allNodes()}
        return self

    def __exit__(self, *exc):
        for n in [n for n in nuke.allNodes() if n.name() not in self.before]:
            nuke.delete(n)


def _write(parent, path, kind, first, last, raw=False):
    """Renderiza parent a una secuencia. raw=False escribe los valores de trabajo sin convertir (rol scene_linear)."""
    w = nuke.nodes.Write(inputs=[parent], file=path.replace("\\", "/"), file_type=kind)
    w["channels"].setValue("rgb")
    if kind == "exr":
        w["datatype"].setValue("16 bit half")
        w["compression"].setValue("Zip (1 scanline)")
        w["metadata"].setValue("no metadata")  # el knob solo existe en el Write de EXR
    else:
        w["datatype"].setValue("8 bit")
    names = ("Utility - Raw", "raw", "Raw", "data") if raw else ("scene_linear", "linear", "Linear")
    w["colorspace"].setValue(_pick(w["colorspace"], *names))
    nuke.execute(w, first, last, 1)


def _render_plate(src, in_dir, first, last, scale):
    os.makedirs(in_dir, exist_ok=True)
    with _Temp():
        cur = src
        if scale < 1:
            cur = nuke.nodes.Reformat(inputs=[src], type="scale", scale=scale, resize="distort")
        _write(cur, os.path.join(in_dir, "plate.%04d.exr"), "exr", first, last)


def _render_hint(hint, hint_dir, first, last):
    os.makedirs(hint_dir, exist_ok=True)
    with _Temp():
        sh = nuke.nodes.Shuffle(inputs=[hint])
        ch = "alpha" if "rgba.alpha" in hint.channels() else "red"  # sin alpha, usa el rojo
        for c in ("red", "green", "blue"):
            sh[c].setValue(ch)
        _write(sh, os.path.join(hint_dir, "hint.%04d.png"), "png", first, last, raw=True)


_SKIP = ("xpos", "ypos", "selected", "tile_color", "gl_color", "note_font", "label", "hide_input")


def _file_stamp(n, frame):
    """tamaño:fecha del archivo que lee un Read en `frame`, para notar que lo reemplazaron."""
    try:
        p = n["file"].value()
        p = p % frame if "%" in p else p
        st = os.stat(p)
        return "%d:%d" % (st.st_size, st.st_mtime)
    except Exception:
        return ""


def _fingerprint(node, extra):
    """Huella de TODO lo que alimenta a `node` (nodos, sus knobs, archivos de los Read, color del script) y de `extra`.
    Si no cambia entre dos corridas, lo ya convertido sigue valiendo.
    shortcut: no ve cambios dentro de un archivo que no sea un Read, ni de nodos remotos por expresión de scripts externos."""
    h = hashlib.sha1()
    stack, seen = [node], set()
    while stack and len(seen) < 3000:
        n = stack.pop()
        if n.fullName() in seen:
            continue
        seen.add(n.fullName())
        lines = n.writeKnobs(nuke.TO_SCRIPT).splitlines()
        h.update(("\n".join(l for l in lines if not l.strip().startswith(_SKIP))).encode("utf-8", "replace"))
        if n.Class() == "Read":
            h.update(_file_stamp(n, extra[0]).encode())
        stack.extend(n.dependencies(nuke.INPUTS | nuke.EXPRESSIONS | nuke.HIDDEN_INPUTS))
        if n.Class() == "Group":
            stack.extend(n.nodes())
    h.update(repr(extra).encode("utf-8"))
    root = nuke.root()
    for k in ("colorManagement", "OCIO_config", "workingSpaceLUT", "customOCIOConfigPath"):
        if root.knob(k):
            h.update(str(root[k].value()).encode("utf-8"))
    h.update(FORMAT_VERSION.encode())
    return h.hexdigest()


def _ready(folder, key, n):
    """¿Ya hay en `folder` los n archivos convertidos con esta misma huella?"""
    stamp = os.path.join(folder, ".key")
    try:
        with open(stamp) as f:
            same = f.read().strip() == key
    except OSError:
        return False
    return same and len([f for f in os.listdir(folder) if f.endswith((".exr", ".png"))]) == n


def _stamp(folder, key):
    with open(os.path.join(folder, ".key"), "w") as f:
        f.write(key)


def _dirs(node):
    """(carpeta de temporales de este script, carpeta fija de este nodo). Siempre en la PC del usuario: lo que se sube
    es el resultado de la carpeta de salida, no esto."""
    root = nuke.root().name()
    key = ("%s_%s" % (os.path.splitext(os.path.basename(root))[0], hashlib.sha1(root.encode("utf-8")).hexdigest()[:6])
           if os.path.isfile(root) else "sin_guardar")
    base = os.path.join(core.home(), "runs", key)
    return base, os.path.join(base, node.fullName().replace(".", "_"))


def _clip_name(src):
    """Nombre del primer Read que alimenta a src (sin frame ni extensión); si no hay, el del script."""
    stack, seen = [src], set()
    while stack:
        n = stack.pop(0)
        if n.fullName() in seen:
            continue
        seen.add(n.fullName())
        if n.Class() == "Read":
            return core.clip_base(n["file"].value()) or "CorridorKey"
        stack.extend(n.dependencies(nuke.INPUTS))
    root = nuke.root().name()
    return os.path.splitext(os.path.basename(root))[0] if os.path.isfile(root) else "CorridorKey"


def _sync_name(node, src):
    """Deja escrito en el campo Nombre el nombre automático (clip + _ck) para que se pueda retocar, y devuelve el nombre
    que vale. Si el usuario ya lo cambió a mano no se pisa; si lo vació, vuelve a ser automático."""
    auto = _clip_name(src) + "_ck"
    cur, last = node["out_name"].value().strip(), _hidden(node, "out_name_auto").value()
    if cur in ("", last):  # sin tocar por el usuario: sigue al clip
        node["out_name"].setValue(auto)
        cur = auto
    node["out_name_auto"].setValue(auto)
    return cur


def _hidden(node, name):
    """Knob de texto invisible donde el nodo recuerda el último valor automático; si no existe (nodo creado con una
    versión anterior) se agrega."""
    if node.knob(name) is None:
        k = nuke.String_Knob(name, "")
        k.setFlag(nuke.INVISIBLE)
        node.addKnob(k)
    return node[name]


def _sync_range(node, src, force=False):
    """Primer y Último frame siguen al rango del clip mientras el usuario no los cambie a mano (como el Nombre).
    En nodos de versiones anteriores estaban enlazados al proyecto por expresión: cuentan como "sin tocar"."""
    auto = "%d-%d" % (src.firstFrame(), src.lastFrame())
    last_auto = _hidden(node, "range_auto").value()
    cur = "%d-%d" % (node["first"].value(), node["last"].value())
    linked = node["first"].hasExpression() or node["last"].hasExpression()
    if force or linked or not last_auto or cur == last_auto:
        for k, v in (("first", src.firstFrame()), ("last", src.lastFrame())):
            node[k].clearAnimated()
            node[k].setValue(v)
    node["range_auto"].setValue(auto)


def reset_range(node=None):
    """Botón 'Rango del clip': vuelve a tomar el rango del clip conectado."""
    node = node or nuke.thisNode()
    if node.input(0) is None:
        nuke.message("Conecta el clip a la entrada 'clip' de este nodo.")
        return
    _sync_range(node, node.input(0), force=True)


def on_knob_changed():
    """knobChanged del Group: al conectar o cambiar el clip, se rellenan el nombre y el rango automáticos."""
    if nuke.thisKnob().name() == "inputChange":
        try:
            node = nuke.thisNode()
            src = node.input(0)
            if src is not None and node.knob("out_name") is not None:
                _sync_name(node, src)
                _sync_range(node, src)
        except ValueError:  # el nodo se está destruyendo (se cierra o se limpia el script)
            pass


def _destination(node, src):
    """(carpeta de salida, nombre base, versión) según los knobs del nodo y, si la carpeta está vacía, el script."""
    out = node["out_dir"].value().replace("\\", "/").strip()
    if not out:
        root = nuke.root().name()
        out = (core.prerenders_dir(root) if os.path.isfile(root) else None) or os.path.join(core.home(), "salida")
    return os.path.normpath(out), _sync_name(node, src), int(node["version"].value())


def _window(node):
    """Frames de la ventana temporal elegida; None = automática (también en nodos sin el knob o con un valor raro).
    El knob NO puede llamarse "window": el Group trae un knob interno obsoleto con ese nombre que lo tapa (v0.5.0)."""
    k = node.knob("temporal_window")
    v = k.value() if k is not None else None
    if v not in WINDOW_ITEMS[1:]:
        return None
    return 1 if v == WINDOW_ITEMS[1] else int(v)


def run_infer(work, n, outputs, hint, quality, low_mem, window, out_name):
    """Lanza CorridorKey y espera con barra de progreso y botón Cancelar. Escribe en <work>/<out_name>."""
    cfg = core.load_config()
    in_dir, out_dir, log = os.path.join(work, "in"), os.path.join(work, out_name), os.path.join(work, "run.log")
    tmp = os.path.join(core.home(), "tmp")
    os.makedirs(tmp, exist_ok=True)
    argv = core.build_argv(cfg, in_dir, out_dir, nuke.root()["fps"].value(), outputs, tmp,
                           hint_dir=os.path.join(work, "hint") if hint else None, hint_quality=quality,
                           low_mem=low_mem, window=window)
    if os.path.isfile(log):
        os.remove(log)
    pid = core.spawn_detached(argv, work, log)
    watch = core.output_dir(out_dir, in_dir, outputs[0])
    task = nuke.ProgressTask("CorridorKey")
    try:
        while True:
            text = core.read_log(log)
            code = core.exit_code(text)
            if code is not None:
                break
            if task.isCancelled():
                core.kill(pid)
                raise RuntimeError("Cancelado por el usuario.")
            frac, msg = core.progress(text, len(os.listdir(watch)) if os.path.isdir(watch) else 0, n)
            task.setProgress(int(frac * 100))
            task.setMessage(msg)
            time.sleep(1)
    finally:
        del task
    if code != 0:
        raise RuntimeError("CorridorKey falló:\n\n%s\n\nLog completo: %s" % (core.log_tail(text), log))


def attach_results(node, paths, first, last, src):
    """Crea (o actualiza) dentro del Group un Read por salida del modelo y lo conecta a su Reformat (rf_<tipo>, que
    lo lleva al tamaño del clip y alimenta el despill y las vistas; ver create_node).
    paths = {tipo: patrón con %04d}; los archivos llevan el número de frame del shot."""
    with node:  # un solo nivel de contexto: los helpers no abren otro `with`
        for i, kind in enumerate(KINDS):
            r = nuke.toNode("r_" + kind) or nuke.nodes.Read(name="r_" + kind, xpos=120 * i, ypos=-300)
            r["file"].setValue(paths[kind].replace("\\", "/"))
            r["first"].setValue(first)
            r["last"].setValue(last)
            r["origfirst"].setValue(first)
            r["origlast"].setValue(last)
            r["colorspace"].setValue(_pick(r["colorspace"], "scene_linear", "linear", "Linear"))  # después de file
            r["frame_mode"].setValue("expression")  # sin desfase (la v0.2 numeraba desde 0 con una expresión)
            r["frame"].setValue("")
            rf = nuke.toNode("rf_" + kind)
            rf.setInput(0, r)  # el Read se recrea en cada corrida (ver _detach)
            # al tamaño del clip; Node.format() de un Read devolvió el formato del script, no el del archivo
            rf["type"].setValue("to box")
            rf["box_width"].setValue(src.width())
            rf["box_height"].setValue(src.height())
            rf["box_fixed"].setValue(True)
            rf["box_pixel_aspect"].setValue(src.pixelAspect())
            rf["resize"].setValue("distort")
            try:
                r["reload"].execute()
            except Exception:
                pass
        nuke.toNode("sw")["which"].setExpression("parent.output")  # hasta la primera corrida deja pasar el clip


def _detach(node):
    """Borra los Read de resultados y devuelve lo que leían ({first, last, paths}; None si aún no existían).
    Nuke deja abiertos los frames que leyó y Windows no deja reemplazarlos; borrar el Read es lo único que los suelta
    (medido: vaciar su file, deshabilitarlo o recargarlo no). attach_results los vuelve a crear."""
    old = None
    with node:
        for k in KINDS:
            r = nuke.toNode("r_" + k)
            if r is not None:
                old = old or {"first": int(r["first"].value()), "last": int(r["last"].value()), "paths": {}}
                old["paths"][k] = r["file"].value()
                nuke.delete(r)
    return old


def _prune_outputs(work, base):
    """Borra lo que quede de las corridas en la carpeta temporal (out_*): los EXR ya se movieron a la carpeta de salida,
    así que solo sobran carpetas vacías o restos de una corrida cancelada."""
    for d in os.listdir(work):
        if d.startswith("out_"):
            core.safe_rmtree(os.path.join(work, d), base, ignore_errors=True)


def _process(node, src, hint, force):
    _sync_range(node, src)  # si el rango del clip cambió y el usuario no lo tocó, se procesa el rango nuevo
    first, last = int(node["first"].value()), int(node["last"].value())
    n = last - first + 1
    if n < 1:
        raise RuntimeError("El rango no es válido: el último frame es menor que el primero.")
    _, width, res_label = next(r for r in RES if r[0] == node["resolution"].value())
    scale = 1.0 if width is None else min(1.0, width / src.width())  # un clip más chico que el ancho elegido no se agranda
    pw, ph = int(round(src.width() * scale)), int(round(src.height() * scale))  # lo que procesa el modelo
    base, work = _dirs(node)
    in_dir, hint_dir = os.path.join(work, "in"), os.path.join(work, "hint")
    os.makedirs(work, exist_ok=True)
    out_base, name, version = _destination(node, src)  # antes de convertir y gastar GPU: si algo está mal, que falle ya

    key = _fingerprint(src, (first, last, round(scale, 6)))
    reused = not force and _ready(in_dir, key, n)
    tmp_mb, out_mb = core.disk_need_mb(pw, ph, n, convert=not reused)
    problems = core.disk_problems([(work, tmp_mb), (out_base, out_mb)])
    if problems:
        raise RuntimeError("No hay espacio suficiente en disco para %d frames:\n%s\n\nLibera espacio o elige otra "
                           "Carpeta de salida." % (n, "\n".join(problems)))

    gpu = core.gpu_info()
    small_gpu = gpu is None or gpu[1] <= core.LOW_MEM_MAX_MIB
    window = _window(node)
    if window and small_gpu and window > core.window_limit(pw, ph) and not nuke.ask(
            "La ventana de %d frames supera lo recomendado para %dx%d en una GPU de 12-16 GB (%d).\n"
            "En un PC de 12 GB, una ventana de 24 en 4K lo colgó.\n\n¿Continuar igual?"
            % (window, pw, ph, core.window_limit(pw, ph))):
        raise RuntimeError("Cancelado: elige una ventana temporal más chica o Auto.")
    # con ventana fija CorridorKey ya no elige solo el modo de memoria: en GPUs chicas se pide siempre
    low_mem = small_gpu and (pw * ph > LOW_MEM_MIN_PIXELS or (window or 0) > 1)

    if not reused:
        core.safe_rmtree(in_dir, base)
        _render_plate(src, in_dir, first, last, scale)
        _stamp(in_dir, key)
    if hint is not None:
        hkey = _fingerprint(hint, (first, last, "hint"))
        if force or not _ready(hint_dir, hkey, n):
            core.safe_rmtree(hint_dir, base)
            _render_hint(hint, hint_dir, first, last)
            _stamp(hint_dir, hkey)
    else:
        core.safe_rmtree(hint_dir, base)  # que un hint viejo no se cuele

    out_name = "out_" + time.strftime("%Y%m%d_%H%M%S")  # temporal: el resultado vive en la carpeta de salida
    paths = {k: core.result_path(out_base, name, k, version) for k in KINDS}
    t0 = time.time()
    run_infer(work, n, list(KINDS), hint is not None, node["hint_quality"].value(), low_mem, window, out_name)
    old = _detach(node)
    try:
        core.publish([(core.output_dir(os.path.join(work, out_name), in_dir, k), paths[k]) for k in KINDS], first)
    except Exception:
        if old:
            attach_results(node, old["paths"], old["first"], old["last"], src)
        raise
    attach_results(node, paths, first, last, src)
    _prune_outputs(work, base)
    shown = out_base if len(out_base) <= 36 else "…" + out_base[-35:]  # el campo no ajusta líneas: en un panel angosto se corta
    return "Última corrida %s (%d s): %d frames\n%s, %s\nVentana: %s\nSalida v%02d: %s" % (
        time.strftime("%H:%M"), time.time() - t0, n, res_label,
        "conversión reutilizada" if reused else "conversión nueva",
        "auto" if window is None else "frame a frame" if window == 1 else "%d frames" % window, version, shown)


def run(node=None, force=False):
    """Botón Procesar del nodo."""
    node = node or nuke.thisNode()
    src, hint = node.input(0), node.input(1)
    if src is None:
        nuke.message("Conecta el clip a la entrada 'clip' de este nodo (sin Reformat: la reducción a HD la hace el nodo).")
        return
    gpu = core.gpu_info()
    if gpu and gpu[2] < 6000 and not nuke.ask("La GPU tiene solo %d MiB libres (%s).\nCierra ComfyUI u otras apps que la "
                                              "usen o CorridorKey irá más lento o fallará.\n\n¿Continuar igual?" % (gpu[2], gpu[0])):
        return
    try:
        node["status"].setValue(_process(node, src, hint, force))
    except Exception as e:  # el usuario necesita ver el motivo, no un traceback de Nuke
        nuke.message("CorridorKey no pudo terminar.\n\n%s" % e)


def reconvert(node=None):
    run(node, force=True)


def clean_inputs(node=None):
    node = node or nuke.thisNode()
    base, work = _dirs(node)
    for d in ("in", "hint"):
        core.safe_rmtree(os.path.join(work, d), base)
    if os.path.isdir(work):
        _prune_outputs(work, base)  # y los restos de una corrida cancelada
    nuke.message("Listo: borré el clip y el hint convertidos de '%s'. Los resultados de la carpeta de salida no se tocan." % node.name())


def open_folder(node=None):
    node = node or nuke.thisNode()
    src = node.input(0)
    out_base = _destination(node, src)[0] if src is not None else node["out_dir"].value()
    if not out_base:
        nuke.message("Conecta el clip para que el nodo sepa dónde guardará el resultado.")
        return
    os.makedirs(out_base, exist_ok=True)
    os.startfile(out_base)


def clean_orphans():
    """Borra las carpetas de temporales de los nodos que ya no existen en este script (la carpeta de salida no se toca)."""
    base, _ = _dirs(nuke.root())
    if not os.path.isdir(base):
        nuke.message("No hay carpetas de trabajo para este script.")
        return
    alive = {n.fullName().replace(".", "_") for n in nuke.allNodes("Group", recurseGroups=True) if n.knob("ck_tab")}
    orphans = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)) and d not in alive]
    if not orphans:
        nuke.message("No hay carpetas huérfanas: todas pertenecen a un nodo CorridorKey de este script.")
        return
    if nuke.ask("Estas carpetas ya no tienen nodo en este script:\n\n%s\n\n¿Borrarlas?" % "\n".join(orphans)):
        for d in orphans:
            core.safe_rmtree(os.path.join(base, d), base)


def _add_knobs(g):
    def add(k, tip=None):
        g.addKnob(k)
        if tip:
            k.setTooltip(tip)
        return k

    call = "import corridorkey_nuke.ui as ui; ui.%s(nuke.thisNode())"
    add(nuke.Tab_Knob("ck_tab", "CorridorKey"))
    add(nuke.Text_Knob("note", "", NOTE))
    add(nuke.Enumeration_Knob("resolution", "Resolución", RES_ITEMS), TIPS["resolution"])
    add(nuke.Enumeration_Knob("temporal_window", "Ventana temporal", WINDOW_ITEMS), TIPS["window"])
    add(nuke.Int_Knob("first", "Primer frame"), TIPS["first"])
    add(nuke.Int_Knob("last", "Último frame"), TIPS["last"])
    add(nuke.PyScript_Knob("range_btn", "Rango del clip", call % "reset_range"), TIPS["range_btn"]).clearFlag(nuke.STARTLINE)
    for k in ("first", "last"):  # hasta que se conecte un clip (ver _sync_range)
        g[k].setValue(int(nuke.root()[k + "_frame"].value()))
    add(nuke.String_Knob("range_auto", "")).setFlag(nuke.INVISIBLE)  # último rango automático (ver _sync_range)
    add(nuke.Double_Knob("hint_quality", "Calidad del hint"), TIPS["hint_quality"])
    g["hint_quality"].setRange(0, 1)
    g["hint_quality"].setValue(0.75)
    add(nuke.Text_Knob("div_post", "Post proceso", ""))  # de aquí abajo todo es en vivo: no vuelve a procesar
    add(nuke.Enumeration_Knob("despill_color", "Pantalla", SCREEN_ITEMS), TIPS["despill_color"])
    add(nuke.Enumeration_Knob("despill_mode", "Despill", DESPILL_ITEMS), TIPS["despill_mode"])
    add(nuke.Double_Knob("despill", "Fuerza"), TIPS["despill"])
    g["despill"].setRange(0, 1)
    g["despill"].setValue(0.5)
    add(nuke.Enumeration_Knob("output", "Ver", OUTPUT_ITEMS), TIPS["output"])
    add(nuke.Text_Knob("div_out", ""))
    add(nuke.File_Knob("out_dir", "Carpeta de salida"), TIPS["out_dir"])
    add(nuke.String_Knob("out_name", "Nombre"), TIPS["out_name"])
    add(nuke.String_Knob("out_name_auto", "")).setFlag(nuke.INVISIBLE)  # último nombre automático (ver _sync_name)
    add(nuke.Int_Knob("version", "Versión"), TIPS["version"])
    g["version"].setValue(1)
    add(nuke.Text_Knob("div", ""))
    add(nuke.PyScript_Knob("run_btn", "Procesar", call % "run"), TIPS["run_btn"])
    add(nuke.PyScript_Knob("reconvert_btn", "Reconvertir", call % "reconvert"), TIPS["reconvert_btn"])
    add(nuke.PyScript_Knob("clean_btn", "Borrar temp.", call % "clean_inputs"), TIPS["clean_btn"])
    add(nuke.PyScript_Knob("open_btn", "Abrir salida", call % "open_folder"), TIPS["open_btn"])
    add(nuke.Text_Knob("status", "Estado", "Sin procesar todavía."), TIPS["status"])


def create_node():
    """Crea un nodo CorridorKey; si hay un nodo seleccionado lo conecta a la entrada clip (el hint lo conectas tú)."""
    sel = nuke.selectedNodes()
    src = sel[0] if sel else None
    g = nuke.nodes.Group()
    g.setName("CorridorKey", uncollide=True)  # Group(name=...) repite el nombre si ya existe: CorridorKey1, 2...
    with g:
        clip = nuke.nodes.Input(name="clip", xpos=400, ypos=-300)
        clip["number"].setValue(0)
        nuke.nodes.Input(name="hint", xpos=520, ypos=-300)["number"].setValue(1)
        # los Read de resultados (r_alpha, r_fg) los crea attach_results y alimentan a estos Reformat
        rf_a = nuke.nodes.Reformat(name="rf_alpha", xpos=0, ypos=-220)
        rf_f = nuke.nodes.Reformat(name="rf_fg", xpos=120, ypos=-220)
        avg = nuke.nodes.Expression(name="dsp_avg", inputs=[rf_f], xpos=120, ypos=-150)
        mx = nuke.nodes.Expression(name="dsp_max", inputs=[rf_f], xpos=240, ypos=-150)
        dsw = nuke.nodes.Switch(name="dsp_sw", inputs=[avg, mx, rf_f], xpos=120, ypos=-90)  # = DESPILL_ITEMS
        cp = nuke.nodes.Copy(name="cp_cutout", inputs=[dsw, rf_a], from0="rgba.red", to0="rgba.alpha", xpos=120, ypos=-30)
        pm = nuke.nodes.Premult(name="pm", inputs=[cp], xpos=120, ypos=30)
        # el alpha del modelo llega como gris en rojo/verde/azul: se copia de rgba.red al canal alpha
        st = nuke.nodes.Copy(name="st", inputs=[rf_f, rf_a], from0="rgba.red", to0="rgba.alpha", xpos=300, ypos=-30)
        sw = nuke.nodes.Switch(name="sw", inputs=[pm, rf_a, rf_f, st, clip], xpos=120, ypos=100)  # = OUTPUT_ITEMS
        sw["which"].setValue(4)  # hasta la primera corrida el nodo deja pasar el clip
        nuke.nodes.Output(inputs=[sw], xpos=120, ypos=160)
    _add_knobs(g)
    with g:  # las expresiones leen knobs del Group: se ponen cuando ya existen
        for name, method in (("dsp_avg", "avg"), ("dsp_max", "max")):
            e = nuke.toNode(name)
            temps = (("amt", "parent.despill"), ("scr", "parent.despill_color")) + tuple(zip(("sg", "sb"), core.SPILL[method]))
            for i, (var, expr) in enumerate(temps):
                e["temp_name%d" % i].setValue(var)
                e["temp_expr%d" % i].setValue(expr)
            for i, expr in enumerate(core.DESPILL_EXPR):
                e["expr%d" % i].setValue(expr)
        nuke.toNode("dsp_sw")["which"].setExpression("parent.despill_mode")
    g["tile_color"].setValue(0x3B7A57FF)
    g["label"].setValue("[value resolution]")
    if src is not None:
        g.setInput(0, src)
        g["xpos"].setValue(src.xpos())
        g["ypos"].setValue(src.ypos() + 90)
        _sync_name(g, src)
    # sin el plugin (script abierto en otra PC) el callback no hace nada en vez de dar error en cada cambio
    g["knobChanged"].setValue("try:\n    import corridorkey_nuke.ui as ui\nexcept ImportError:\n    ui = None\n"
                              "if ui:\n    ui.on_knob_changed()")
    return g


def open_home():
    os.startfile(core.home())


def diagnose():
    try:
        cfg = core.load_config()
        from . import __version__
        lines = ["Instalación: OK (%s)" % core.home(), "Plugin %s, instalador %s" % (__version__, cfg.get("version", "?"))]
    except Exception as e:
        lines = ["Instalación: PROBLEMA", str(e)]
    gpu = core.gpu_info()
    lines.append("GPU: %s, %d MiB libres de %d" % (gpu[0], gpu[2], gpu[1]) if gpu else "GPU: nvidia-smi no responde")
    nuke.message("\n".join(lines))
