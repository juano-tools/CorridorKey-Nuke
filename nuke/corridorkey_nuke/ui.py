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

from . import __version__, core

GREEN, AMBER = "#7fd1a8", "#f2a65a"  # los mismos del nodo SHARP Splat

FORMAT_VERSION = "1"  # súbela si cambia cómo se escribe el plate: invalida lo ya convertido
KINDS = ("alpha", "fg")  # lo que entrega el modelo y se guarda; el cutout y el straight se calculan en vivo
OUTPUT_ITEMS = ["cutout", "alpha", "fg", "fg + alpha", "clip original"]  # = entradas 0..4 del Switch `sw`
DESPILL_ITEMS = ["Average", "Máximo", "Ninguno"]  # = entradas 0..2 del Switch `dsp_sw`
SCREEN_ITEMS = ["Verde", "Azul"]  # = parent.despill_color en las expresiones (core.DESPILL_EXPR)
WINDOW_ITEMS = ["Auto", "Frame a frame", "2", "4", "8", "16", "24", "48", "80"]
MEMORY_ITEMS = ["Auto", "Baja", "Mínima"]  # = False / True / "min" en core.build_argv
HINT_FRAMES = ["Todos los frames", "Solo el primer frame"]  # = --hint_video / --hint_first_frame
# (nombre en el desplegable, ancho al que se reduce dentro del nodo (None = el del clip), cómo lo nombra el estado)
RES = (("HD", 1920.0, "HD interno"), ("720p", 1280.0, "720p interno"),
       ("Nativa", None, "resolución nativa"))
RES_ITEMS = [r[0] for r in RES]
LOW_MEM_MIN_PIXELS = 3.0e6  # por encima de ~1440p las ventanas largas no entran en una GPU de 12 GB

TIPS = {
    "resolution": (
        "HD, el recomendado: el clip se reduce a 1920 px de ancho DENTRO del nodo y el resultado vuelve al tamaño "
        "original. No pongas un Reformat antes: no hace falta y, si lo pones, el resultado saldrá a ese tamaño reducido.\n\n"
        "720p, el liviano: igual, pero a 1280 px de ancho. Para equipos con poca memoria de GPU o para una prueba "
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
        "Average: el mismo de CorridorKey. Baja el verde que supera el promedio de rojo y azul y reparte "
        "la mitad a cada uno.\n"
        "Máximo, el suave: solo baja el verde que supera al mayor de rojo y azul, así respeta amarillos y tonos "
        "cálidos. Corrige menos que Average.\n"
        "Ninguno: deja el fg crudo. Úsalo si vas a despillar con otro nodo (DespillMadness, etc.): conecta ese nodo a "
        "la vista 'fg + alpha' y haz el Premult después.\n\n"
        "Si el fg ya viene limpio, el despill casi no cambia nada: es normal."),
    "window": (
        "Cuántos frames mira el modelo a la vez para que el key sea estable en el tiempo (más frames = menos "
        "parpadeo y mejor borde, pero más memoria de GPU).\n"
        "Auto: CorridorKey elige según la memoria libre (recomendado).\n"
        "Frame a frame: cada frame solo; el más liviano, puede parpadear.\n"
        "2 a 80: ventana fija. En GPUs de 16 GB o menos se usa siempre el modo de memoria baja, y si la ventana supera "
        "lo recomendado para tu tarjeta y la resolución el nodo pide confirmación (en un PC de 12 GB una ventana de 24 "
        "en 4K lo colgó).\n\n"
        "Si CorridorKey se queda sin memoria, el nodo reintenta solo con la ventana siguiente más chica; el estado "
        "dice con cuál terminó."),
    "use_hint": ("Usar el hint conectado. Desmárcalo para procesar sin hint sin tener que desconectar el nodo."),
    "hint_frames": (
        "Todos los frames: el hint acompaña a cada frame del clip (lo más controlado).\n"
        "Solo el primer frame: el modelo recibe el hint en el primer frame del rango y sigue al sujeto solo "
        "(sirve si solo tienes un matte de partida; puede derivar en tomas largas u oclusiones)."),
    "carry_quality": (
        "Confianza en lo que el propio modelo arrastra de una ventana temporal a la siguiente (CorridorKey usa 0.95). "
        "Solo actúa con hint y con ventana temporal de más de 1 frame."),
    "no_carry": ("El hint manda: se usa tal cual en todos los frames, sin que la predicción del modelo en la ventana "
                 "anterior sirva de hint. Más literal, pero pierde un mecanismo de estabilidad temporal."),
    "memory": ("Auto: el nodo activa el modo de memoria baja solo cuando hace falta (GPUs de 16 GB o menos, según la "
               "resolución y la ventana). Recomendado.\n"
               "Baja: fuerza el modo de memoria baja de CorridorKey: más lento, menos VRAM.\n"
               "Mínima: memoria baja con todos los ajustes al mínimo. Para tarjetas de 4 a 6 GB o cuando Baja no "
               "alcanza; es la más lenta.\n\n"
               "Con ventana temporal Auto, Baja y Mínima usan la ventana recomendada para tu tarjeta y la resolución."),
    "keep_orig": (
        "Usa el plate original dentro del sujeto y el resultado de CorridorKey solo en los bordes.\n\n"
        "Por qué: el fg de CorridorKey es el color del sujeto recalculado por el modelo. En los bordes eso es lo "
        "valioso: quita la pantalla mezclada en el pelo, el motion blur y las transparencias. Pero dentro del sujeto no "
        "hay nada que separar, y ahí el fg es una copia del plate de menor calidad: si procesas en HD o 720p viene "
        "reescalado (más blando que tu plate) y puede perder grano y detalle fino.\n\n"
        "Qué hace: donde el alpha es sólido (de 0.95 a 1) pone los píxeles del plate; en los bordes y las zonas "
        "translúcidas deja el fg del modelo. El despill se aplica después, sobre todo el sujeto.\n\n"
        "Cuándo usarla: al procesar en HD o 720p un plate de más resolución, casi siempre.\n"
        "Qué revisar: el límite entre el interior y el borde. Si ves una línea ahí, desmárcala.\n\n"
        "Es en vivo: no vuelve a procesar. Cambia las vistas cutout, fg y fg + alpha; los EXR guardados no cambian "
        "(son siempre el alpha y el fg crudos del modelo)."),
    "hint_info": "Qué hint recibirá la próxima corrida.",
    "despill": ("Fuerza del despill: 0 = nada, 1 = completo (CorridorKey usa 0.5 por defecto). Se ve al instante, "
                "sin Procesar."),
    "output": (
        "Qué muestra el nodo (cambiarlo no vuelve a procesar):\n"
        "cutout = el fg con el despill de abajo, premultiplicado por el alpha: listo para componer.\n"
        "alpha = el matte en gris.\nfg = foreground crudo (sin despill ni premultiplicar; con el clip original en las "
        "zonas sólidas si activaste esa opción).\n"
        "fg + alpha = straight: el fg crudo con el alpha en el canal alpha, SIN premultiplicar: para despillar con "
        "tu propio nodo y premultiplicar después.\nclip original = el clip sin keyear."),
    "run_btn": ("Procesa el clip con CorridorKey. Si el clip y el hint no cambiaron desde la última vez, reutiliza los "
                "archivos ya convertidos y no los reescribe."),
    "reconvert_btn": ("Reconvertir y procesar: vuelve a escribir el clip y el hint aunque parezcan iguales (por si "
                      "reemplazaste un archivo que Nuke no detecta) y procesa."),
    "clean_btn": ("Borra los temporales (clip y hint convertidos, que viven en tu PC). Los resultados de la carpeta de "
                  "salida no se tocan."),
    "open_btn": "Abre la carpeta de salida en el explorador.",
    "out_dir": ("Dónde se guardan los EXR del resultado (alpha y fg, crudos, sin despill), listos para subir.\n"
                "Aparece escrita la carpeta automática: 2_prerenders del departamento (la que está junto a 1_projects, "
                "donde guardaste el script). Con el script sin guardar, la 2_prerenders de Comp del shot del clip. Si "
                "nada de eso existe, una carpeta de CorridorKey en tu PC.\n"
                "Si la cambias a mano se respeta; si la borras, vuelve a ser la automática."),
    "out_name": ("Nombre de los archivos. Aparece escrito el nombre automático (el del clip + _ck) para que lo "
                 "retoques: si lo cambias a mano se respeta; si lo borras, vuelve a ser automático.\n"
                 "Queda como <nombre>_<alpha|fg>_v01\\<nombre>_<...>_v01.1001.exr"),
    "version": ("Procesar REEMPLAZA los archivos de esta versión (no acumula espacio). Para conservar la anterior, "
                "sube el número antes de procesar: se crea una carpeta nueva (v02) y la v01 queda intacta."),
    "status": "Resultado de la última corrida.",
}


def _val(node, name, default):
    """Valor de un knob; `default` si el nodo es de una versión anterior y todavía no lo tiene."""
    k = node.knob(name)
    return default if k is None else k.value()


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
        st = os.stat(core.frame_path(n["file"].value(), frame))
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
            h.update((_file_stamp(n, extra[0]) + _file_stamp(n, extra[1])).encode())  # primer y último frame
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
    key = core.run_key(root) if os.path.isfile(root) else "sin_guardar"
    base = os.path.join(core.home(), "runs", key)
    return base, os.path.join(base, node.fullName().replace(".", "_"))


def _clip_file(src):
    """Ruta del primer Read que alimenta a src; None si no hay."""
    stack, seen = [src] if src is not None else [], set()
    while stack:
        n = stack.pop(0)
        if n.fullName() in seen:
            continue
        seen.add(n.fullName())
        if n.Class() == "Read":
            return n["file"].value()
        stack.extend(n.dependencies(nuke.INPUTS))
    return None


def _clip_name(src):
    """Nombre del primer Read que alimenta a src (sin frame ni extensión); si no hay, el del script."""
    clip = _clip_file(src)
    if clip:
        return core.clip_base(clip) or "CorridorKey"
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


def _sync_out_dir(node):
    """Deja escrita en Carpeta de salida la carpeta automática y devuelve la que vale. Automática = 2_prerenders junto
    al 1_projects del script; si el script no está guardado ahí, la 2_prerenders del shot del clip; si tampoco, la de
    CorridorKey en la PC. Como el Nombre: si el usuario la cambió a mano no se pisa; si la vació, vuelve a ser automática."""
    root, clip = nuke.root().name(), _clip_file(node.input(0))
    auto = ((core.prerenders_dir(root) if os.path.isfile(root) else None)
            or (core.prerenders_from_clip(clip) if clip else None)
            or os.path.join(core.home(), "salida")).replace("\\", "/")
    cur, last = node["out_dir"].value().replace("\\", "/").strip(), _hidden(node, "out_dir_auto").value()
    if cur in ("", last):
        node["out_dir"].setValue(auto)
        cur = auto
    node["out_dir_auto"].setValue(auto)
    return cur


def _set_status(node, text):
    node["status"].setValue("<span style='color:%s'>%s</span>" % (GREEN, text.replace("\n", "<br>")))


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


def _hint_in(node):
    """El hint que se usará: el de la entrada 2, salvo que esté desmarcado 'Usar hint'; None si no hay."""
    h = node.input(1)
    return h if h is not None and _val(node, "use_hint", True) else None


def refresh_state(node):
    """Texto del hint y knobs en gris según lo que aplica (hint conectado, ventana temporal, arrastre)."""
    if node.knob("hint_info") is None:  # nodo de una versión anterior
        return
    h, used = node.input(1), _hint_in(node)
    node["hint_info"].setValue("sin conectar" if h is None else h.name() if used else "%s (desmarcado)" % h.name())
    carry = used is not None and not node["no_carry"].value()
    for k, on in (("hint_frames", used is not None), ("hint_quality", used is not None), ("no_carry", used is not None),
                  ("carry_quality", carry and _window(node) != 1)):
        node[k].setEnabled(on)
    node["use_hint"].setEnabled(h is not None)


def on_knob_changed():
    """knobChanged del Group: al conectar o cambiar el clip, se rellenan el nombre y el rango automáticos; al cambiar
    el hint o la ventana temporal, se actualizan los knobs en gris."""
    try:
        node, name = nuke.thisNode(), nuke.thisKnob().name()
        if name == "inputChange":
            src = node.input(0)
            if src is not None and node.knob("out_name") is not None:
                _sync_name(node, src)
                _sync_range(node, src)
        if name in ("inputChange", "showPanel") and node.knob("out_dir") is not None:
            _sync_out_dir(node)  # al abrir el panel: el script pudo guardarse en otra carpeta
        if name in ("inputChange", "use_hint", "no_carry", "temporal_window"):
            refresh_state(node)
    except ValueError:  # el nodo se está destruyendo (se cierra o se limpia el script)
        pass


def _destination(node, src):
    """(carpeta de salida, nombre base, versión) según los knobs del nodo y, si la carpeta está vacía, el script."""
    return os.path.normpath(_sync_out_dir(node)), _sync_name(node, src), int(node["version"].value())


def _window(node):
    """Frames de la ventana temporal elegida; None = automática (también en nodos sin el knob o con un valor raro).
    El knob NO puede llamarse "window": el Group trae un knob interno obsoleto con ese nombre que lo tapa (v0.5.0)."""
    k = node.knob("temporal_window")
    v = k.value() if k is not None else None
    if v not in WINDOW_ITEMS[1:]:
        return None
    return 1 if v == WINDOW_ITEMS[1] else int(v)


def _memory(node):
    """Modo de memoria para core.build_argv: False (auto), True (baja) o "min". Los nodos anteriores a la 0.7 tenían
    la casilla `low_gpu` en vez del desplegable."""
    k = node.knob("gpu_memory")
    if k is None:
        return bool(_val(node, "low_gpu", False))
    return {MEMORY_ITEMS[1]: True, MEMORY_ITEMS[2]: "min"}.get(k.value(), False)


class OutOfMemory(RuntimeError):
    """CorridorKey se quedó sin memoria de GPU; .window = la ventana que eligió su modo automático, si la informó."""
    window = None


def run_infer(work, n, outputs, hint, quality, low_mem, window, out_name, hint_first=False, carry_quality=None,
              no_carry=False):
    """Lanza CorridorKey y espera con barra de progreso y botón Cancelar. Escribe en <work>/<out_name>."""
    cfg = core.load_config()
    in_dir, out_dir, log = os.path.join(work, "in"), os.path.join(work, out_name), os.path.join(work, "run.log")
    tmp = os.path.join(core.home(), "tmp")
    os.makedirs(tmp, exist_ok=True)
    argv = core.build_argv(cfg, in_dir, out_dir, nuke.root()["fps"].value(), outputs, tmp,
                           hint_dir=os.path.join(work, "hint") if hint else None, hint_quality=quality,
                           low_mem=low_mem, window=window, hint_first=hint_first, carry_quality=carry_quality,
                           no_carry=no_carry)
    if os.path.isfile(log):
        os.remove(log)
    pid = core.spawn_detached(argv, work, log)
    watch = core.output_dir(out_dir, in_dir, outputs[0])
    task = nuke.ProgressTask("CorridorKey")
    ticks = 0
    try:
        while True:
            text = core.read_log(log)
            code = core.exit_code(text)
            if code is not None:
                break
            ticks += 1
            if ticks % 10 == 0 and not core.alive(pid):  # murió sin dejar su código de salida (lo mataron de afuera)
                text = core.read_log(log)
                code = core.exit_code(text)
                if code is None:
                    code = 1
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
        err = (OutOfMemory if core.is_oom(text) else RuntimeError)(
            "CorridorKey falló:\n\n%s\n\nLog completo: %s" % (core.log_tail(text), log))
        err.window = core.auto_window(text)
        raise err


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
    _, width, res_label = next(r for r in RES if r[0] == node["resolution"].value().split(" (")[0])  # nodos viejos: "HD (recomendado)"
    scale = 1.0 if width is None else min(1.0, width / src.width())  # un clip más chico que el ancho elegido no se agranda
    pw, ph = int(round(src.width() * scale)), int(round(src.height() * scale))  # lo que procesa el modelo
    base, work = _dirs(node)
    in_dir, hint_dir = os.path.join(work, "in"), os.path.join(work, "hint")
    os.makedirs(work, exist_ok=True)
    os.utime(base)  # marca de uso para la purga
    core.purge_old_runs(base)
    out_base, name, version = _destination(node, src)  # antes de convertir y gastar GPU: si algo está mal, que falle ya

    key = _fingerprint(src, (first, last, round(scale, 6)))
    reused = not force and _ready(in_dir, key, n)
    tmp_mb, out_mb = core.disk_need_mb(pw, ph, n, convert=not reused)
    problems = core.disk_problems([(work, tmp_mb), (out_base, out_mb)])
    if problems:
        raise RuntimeError("No hay espacio suficiente en disco para %d frames:\n%s\n\nLibera espacio o elige otra "
                           "Carpeta de salida." % (n, "\n".join(problems)))

    gpu = core.gpu_info()
    total = gpu[1] if gpu else 12288  # sin nvidia-smi se asume una tarjeta chica
    small_gpu = total <= core.LOW_MEM_MAX_MIB
    limit = core.window_limit(pw, ph, total)  # lo que recomienda CorridorKey para esta tarjeta y resolución
    window = _window(node)
    if window and small_gpu and window > limit and not nuke.ask(
            "La ventana de %d frames supera lo recomendado para %dx%d en una GPU de %d GB (%d).\n"
            "En un PC de 12 GB, una ventana de 24 en 4K lo colgó.\n\n¿Continuar igual?"
            % (window, pw, ph, round(total / 1024.0), limit)):
        raise RuntimeError("Cancelado: elige una ventana temporal más chica o Auto.")
    # con ventana fija CorridorKey ya no elige solo el modo de memoria: en GPUs chicas se pide siempre
    low_mem = _memory(node) or small_gpu and (pw * ph > LOW_MEM_MIN_PIXELS or (window or 0) > 1)
    if low_mem and window is None:
        window = limit  # --low_vram apaga el automático de CorridorKey: la ventana la pone la tabla

    if not reused:
        core.safe_rmtree(in_dir, base)
        _render_plate(src, in_dir, first, last, scale)
        _stamp(in_dir, key)
    hint_first = hint is not None and _val(node, "hint_frames", HINT_FRAMES[0]) == HINT_FRAMES[1]
    if hint is not None:
        hlast = first if hint_first else last  # con 'Solo el primer frame' se convierte un único frame
        hkey = _fingerprint(hint, (first, hlast, "hint"))
        if force or not _ready(hint_dir, hkey, hlast - first + 1):
            core.safe_rmtree(hint_dir, base)
            _render_hint(hint, hint_dir, first, hlast)
            _stamp(hint_dir, hkey)
    else:
        core.safe_rmtree(hint_dir, base)  # que un hint viejo no se cuele

    paths = {k: core.result_path(out_base, name, k, version) for k in KINDS}
    t0, asked = time.time(), window
    while True:  # si falta memoria de GPU, se reintenta con la ventana siguiente más chica (hasta frame a frame)
        out_name = "out_" + time.strftime("%Y%m%d_%H%M%S")  # temporal: el resultado vive en la carpeta de salida
        try:
            run_infer(work, n, list(KINDS), hint is not None, node["hint_quality"].value(), low_mem, window, out_name,
                      hint_first=hint_first, carry_quality=float(_val(node, "carry_quality", 0.95)),
                      no_carry=bool(_val(node, "no_carry", False)))
            break
        except OutOfMemory as e:
            failed = window or e.window or limit
            window = core.smaller_window(failed)
            if window is None:
                raise
            asked, low_mem = asked or failed, low_mem or True
            time.sleep(1)  # el nombre de la carpeta lleva el segundo
    jobs = [(core.output_dir(os.path.join(work, out_name), in_dir, k), paths[k]) for k in KINDS]
    for d, _ in jobs:  # antes de tocar la versión publicada
        if core.count_exr(d) != n:
            raise RuntimeError("CorridorKey terminó pero escribió %d de %d frames en %s.\nNo se reemplazó nada. "
                               "Log: %s" % (core.count_exr(d), n, d, os.path.join(work, "run.log")))
    old = _detach(node)
    try:
        core.publish(jobs, first)
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
        ("auto" if window is None else "frame a frame" if window == 1 else "%d frames" % window)
        + (" (bajó de %d por memoria)" % asked if asked and asked != window else ""), version, shown)


def run(node=None, force=False):
    """Botón Procesar del nodo."""
    node = node or nuke.thisNode()
    src, hint = node.input(0), _hint_in(node)
    if src is None:
        nuke.message("Conecta el clip a la entrada 'clip' de este nodo (sin Reformat: la reducción a HD la hace el nodo).")
        return
    gpu = core.gpu_info()
    # 6000 MiB libres, o el 60 % en tarjetas chicas (una de 6 GB nunca tiene 6000 libres)
    if gpu and gpu[2] < min(6000, 0.6 * gpu[1]):
        procs = "\n".join("   %s: %d MiB" % p for p in core.gpu_processes())
        if not nuke.ask("La GPU tiene solo %d MiB libres (%s).\n%sCierra lo que puedas o CorridorKey irá más lento o "
                        "fallará.\n\n¿Continuar igual?" % (gpu[2], gpu[0], "La ocupan:\n%s\n\n" % procs if procs else "")):
            return
    try:
        _set_status(node, _process(node, src, hint, force))
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

    def section(name, title, tip, closed=False):
        add(nuke.Tab_Knob(name, title, nuke.TABBEGINCLOSEDGROUP if closed else nuke.TABBEGINGROUP), tip)

    def end(name):
        add(nuke.Tab_Knob(name + "_end", "", nuke.TABENDGROUP))

    call = "import corridorkey_nuke.ui as ui; ui.%s(nuke.thisNode())"
    add(nuke.Tab_Knob("ck_tab", "CorridorKey"))
    # el panel se lee de arriba abajo en el orden en que se trabaja: qué entra, dónde sale, Procesar, ajustes en vivo
    add(nuke.Text_Knob("ck_header", "",
                       "<span style='font-size:15pt; color:%s'><b>Corridor</b></span>"
                       "<span style='font-size:15pt; color:%s'>Key</span>"
                       "<span style='color:#888'>&nbsp;&nbsp;v%s</span>" % (GREEN, AMBER, __version__)))
    add(nuke.Text_Knob("ck_div0", ""))

    section("sec_proc", "1 · entrada", "Qué se procesa. Lo que cambies en esta sección se aplica al volver a Procesar.")
    add(nuke.Enumeration_Knob("resolution", "resolución", RES_ITEMS), TIPS["resolution"])
    add(nuke.Int_Knob("first", "rango"), TIPS["first"])
    add(nuke.Int_Knob("last", "a"), TIPS["last"]).clearFlag(nuke.STARTLINE)
    add(nuke.PyScript_Knob("range_btn", "rango del clip", call % "reset_range"), TIPS["range_btn"]).clearFlag(nuke.STARTLINE)
    for k in ("first", "last"):  # hasta que se conecte un clip (ver _sync_range)
        g[k].setValue(int(nuke.root()[k + "_frame"].value()))
    add(nuke.Text_Knob("hint_info", "hint", "sin conectar"), TIPS["hint_info"])
    add(nuke.Boolean_Knob("use_hint", "usar hint"), TIPS["use_hint"]).setFlag(nuke.STARTLINE)
    g["use_hint"].setValue(True)
    add(nuke.Enumeration_Knob("hint_frames", "hint en", HINT_FRAMES), TIPS["hint_frames"])
    add(nuke.Double_Knob("hint_quality", "calidad del hint"), TIPS["hint_quality"])
    g["hint_quality"].setRange(0, 1)
    g["hint_quality"].setValue(0.75)
    add(nuke.Double_Knob("carry_quality", "calidad interna"), TIPS["carry_quality"])
    g["carry_quality"].setRange(0, 1)
    g["carry_quality"].setValue(0.95)
    add(nuke.Boolean_Knob("no_carry", "hint sin arrastre"), TIPS["no_carry"]).setFlag(nuke.STARTLINE)
    end("sec_proc")

    section("sec_out", "2 · salida", "Dónde y con qué nombre quedan los EXR del resultado.")
    add(nuke.File_Knob("out_dir", "carpeta"), TIPS["out_dir"])
    add(nuke.String_Knob("out_name", "nombre"), TIPS["out_name"])
    add(nuke.Int_Knob("version", "versión"), TIPS["version"])
    g["version"].setValue(1)
    add(nuke.PyScript_Knob("open_btn", "abrir carpeta", call % "open_folder"), TIPS["open_btn"])
    end("sec_out")

    add(nuke.Text_Knob("ck_div1", ""))
    add(nuke.PyScript_Knob("run_btn", "<span style='color:%s'><b>&#9654; Procesar</b></span>" % GREEN, call % "run"),
        TIPS["run_btn"]).setFlag(nuke.STARTLINE)
    add(nuke.Text_Knob("status", "estado", "sin procesar"), TIPS["status"])
    add(nuke.Text_Knob("ck_div2", ""))

    section("sec_post", "3 · ajustar", "En vivo: cambiar algo de esta sección se ve al instante y no vuelve a procesar.")
    add(nuke.Enumeration_Knob("output", "ver", OUTPUT_ITEMS), TIPS["output"])
    add(nuke.Enumeration_Knob("despill_color", "pantalla", SCREEN_ITEMS), TIPS["despill_color"])
    add(nuke.Enumeration_Knob("despill_mode", "despill", DESPILL_ITEMS), TIPS["despill_mode"])
    add(nuke.Double_Knob("despill", "fuerza"), TIPS["despill"])
    g["despill"].setRange(0, 1)
    g["despill"].setValue(0.5)
    add(nuke.Boolean_Knob("keep_orig", "plate original en el interior"), TIPS["keep_orig"]).setFlag(nuke.STARTLINE)
    g["keep_orig"].setValue(True)
    end("sec_post")

    section("sec_adv", "avanzado", "Lo que cambies en esta sección se aplica al volver a Procesar.", closed=True)
    add(nuke.Enumeration_Knob("temporal_window", "ventana temporal", WINDOW_ITEMS), TIPS["window"])
    add(nuke.Enumeration_Knob("gpu_memory", "memoria", MEMORY_ITEMS), TIPS["memory"])
    end("sec_adv")

    section("sec_maint", "mantenimiento", "Temporales y reconversión. Normalmente no hace falta tocar nada de esto.", closed=True)
    add(nuke.PyScript_Knob("reconvert_btn", "reconvertir", call % "reconvert"), TIPS["reconvert_btn"]).setFlag(nuke.STARTLINE)
    add(nuke.PyScript_Knob("clean_btn", "borrar temporales", call % "clean_inputs"), TIPS["clean_btn"])
    end("sec_maint")

    add(nuke.String_Knob("range_auto", "")).setFlag(nuke.INVISIBLE)  # último rango automático (ver _sync_range)
    add(nuke.String_Knob("out_name_auto", "")).setFlag(nuke.INVISIBLE)  # último nombre automático (ver _sync_name)
    add(nuke.String_Knob("out_dir_auto", "")).setFlag(nuke.INVISIBLE)  # última carpeta automática (ver _sync_out_dir)


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
        # 'plate original en el interior': donde el alpha es ~1 el fg pasa a ser el clip (antes del despill, que lo limpia igual).
        # shortcut: umbral fijo 0.95-1.0 sin erosión; si queda un halo en el límite, erosionar la máscara.
        ko = nuke.nodes.Expression(name="ko_mask", inputs=[rf_a], expr3="clamp((r-0.95)/0.05,0,1)", xpos=0, ypos=-170)
        fgm = nuke.nodes.Keymix(name="ko_mix", inputs=[rf_f, clip, ko], channels="rgb", xpos=120, ypos=-185)  # B, A, mask
        avg = nuke.nodes.Expression(name="dsp_avg", inputs=[fgm], xpos=120, ypos=-150)
        mx = nuke.nodes.Expression(name="dsp_max", inputs=[fgm], xpos=240, ypos=-150)
        dsw = nuke.nodes.Switch(name="dsp_sw", inputs=[avg, mx, fgm], xpos=120, ypos=-90)  # = DESPILL_ITEMS
        cp = nuke.nodes.Copy(name="cp_cutout", inputs=[dsw, rf_a], from0="rgba.red", to0="rgba.alpha", xpos=120, ypos=-30)
        pm = nuke.nodes.Premult(name="pm", inputs=[cp], xpos=120, ypos=30)
        # el alpha del modelo llega como gris en rojo/verde/azul: se copia de rgba.red al canal alpha
        st = nuke.nodes.Copy(name="st", inputs=[fgm, rf_a], from0="rgba.red", to0="rgba.alpha", xpos=300, ypos=-30)
        sw = nuke.nodes.Switch(name="sw", inputs=[pm, rf_a, fgm, st, clip], xpos=120, ypos=100)  # = OUTPUT_ITEMS
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
        nuke.toNode("ko_mix")["disable"].setExpression("!parent.keep_orig")
    g["tile_color"].setValue(0x3B7A57FF)
    g["label"].setValue("[value resolution]")
    if src is not None:
        g.setInput(0, src)
        g["xpos"].setValue(src.xpos())
        g["ypos"].setValue(src.ypos() + 90)
        _sync_name(g, src)
    _sync_out_dir(g)
    refresh_state(g)
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
