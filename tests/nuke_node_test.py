# -*- coding: utf-8 -*-
"""Prueba del nodo CorridorKey en Nuke headless, contra una instalación real o de sandbox:
   Nuke17.0.exe --nukex -i -t tests\\nuke_node_test.py
   Variables: CK_TEST_PLATE (patrón %04d, frames 1001+), CK_TEST_WORK (carpeta de la prueba), CK_TEST_HINT (carpeta con
   hint_0000.png...), y opcionalmente CK_TEST_NUKE + CK_TEST_HOME para usar un sandbox en vez de la instalación real."""
import os
import re
import sys
import time

import nuke

PLATE, WORK = (os.environ[k] for k in ("CK_TEST_PLATE", "CK_TEST_WORK"))
HINT = os.environ.get("CK_TEST_HINT")  # sin carpeta de hint, el hint es un Constant blanco
if os.environ.get("CK_TEST_NUKE"):
    sys.path.insert(0, os.environ["CK_TEST_NUKE"])
    os.environ["CORRIDORKEY_HOME"] = os.environ["CK_TEST_HOME"]
else:  # el plugin tal como está en el repo
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nuke"))
    if os.environ.get("CK_TEST_FAKE") == "1":  # sin infer.py real no hace falta la instalación: temporales en la carpeta de prueba
        os.environ["CORRIDORKEY_HOME"] = os.path.join(WORK, "home")
import corridorkey_nuke  # noqa: E402
from corridorkey_nuke import core, ui  # noqa: E402

MSGS, ASKS, ANSWER = [], [], [True]
nuke.message = lambda m: (MSGS.append(m), print("MESSAGE:", m))  # en headless no hay diálogos
# ASKS guarda solo las confirmaciones de ventana; el aviso de poca VRAM libre (depende de la GPU del momento) se acepta
nuke.ask = lambda m: True if "GPU tiene solo" in m else (ASKS.append(m), ANSWER[0])[1]
CALL = {}  # argumentos de la última llamada a run_infer (modo FAKE)
FIRST, LAST = 1001, 1008

# CK_TEST_FAKE=1: sin GPU. infer.py se reemplaza por EXR de color conocido (0.1 en la corrida 1, 0.2 en la 2...), así se
# prueba todo lo demás (conversión, nombres, versiones, sobrescritura con frames leídos) y que los píxeles sean los nuevos.
FAKE = os.environ.get("CK_TEST_FAKE") == "1"
RUNS = [0]


FG_COLOR = (0.2, 0.6, 0.4)  # el fg falso: verde dominante y r != b, para distinguir los despills


def fake_infer(work, n, outputs, hint, quality, low_mem, window, out_name):
    """alpha = gris de valor 0.1 * nº de corrida; fg = FG_COLOR."""
    RUNS[0] += 1
    CALL.update(low_mem=low_mem, window=window, outputs=list(outputs))
    in_dir, out_dir = os.path.join(work, "in"), os.path.join(work, out_name)
    for kind in outputs:
        c = nuke.nodes.Constant()
        c["color"].setValue([RUNS[0] * 0.1] * 4 if kind == "alpha" else list(FG_COLOR) + [1])
        d = core.output_dir(out_dir, in_dir, kind)
        os.makedirs(d, exist_ok=True)
        w = nuke.nodes.Write(inputs=[c], file=os.path.join(d, kind + "_%06d.exr").replace("\\", "/"), file_type="exr")
        w["channels"].setValue("rgba")
        w["datatype"].setValue("16 bit half")
        w["colorspace"].setValue("Utility - Raw")
        nuke.execute(w, 0, n - 1, 1)
        nuke.delete(w)
        nuke.delete(c)


def expect_pixels(node):
    """En modo FAKE: el Read de la salida muestra los píxeles de la última corrida (no un frame viejo en caché)."""
    if FAKE:
        with node:
            v = nuke.toNode("r_alpha").sample("red", 5, 5, frame=1004)
        assert abs(v - RUNS[0] * 0.1) < 0.01, "el Read muestra %.3f y debería mostrar %.1f" % (v, RUNS[0] * 0.1)


if FAKE:
    ui.run_infer = fake_infer
print("plugin", corridorkey_nuke.__version__, "desde", os.path.dirname(corridorkey_nuke.__file__))

root = nuke.root()
root["colorManagement"].setValue("OCIO")
root["OCIO_config"].setValue("aces_1.2")
root["fps"].setValue(24)
root["first_frame"].setValue(FIRST)
root["last_frame"].setValue(LAST)
# la estructura de shot del estudio: <depto>/1_projects/script.nk  ->  <depto>/2_prerenders
script = os.path.join(WORK, "Comp", "1_projects", "test.nk")
os.makedirs(os.path.dirname(script), exist_ok=True)
nuke.scriptSaveAs(script, overwrite=1)
PRE = os.path.join(WORK, "Comp", "2_prerenders")

src = nuke.nodes.Read(name="plate")
src["file"].fromUserText(PLATE)
src["first"].setValue(FIRST)
src["last"].setValue(LAST)  # el nodo toma el rango del clip: 8 frames para que la prueba sea rápida
src["colorspace"].setValue("ACES - ACES2065-1")
if HINT:
    h = nuke.nodes.Read(name="hint_png")
    h["file"].fromUserText(os.path.join(HINT, "hint_%04d.png"))
    h["first"].setValue(0)
    h["last"].setValue(7)
    h["frame_mode"].setValue("expression")
    h["frame"].setValue("frame-%d" % FIRST)
    h["colorspace"].setValue("Utility - Raw")
    hint = nuke.nodes.Shuffle(inputs=[h], name="hint_alpha")
    hint["alpha"].setValue("red")
else:
    hint = nuke.nodes.Constant(name="hint_alpha")
    hint["color"].setValue([1, 1, 1, 1])

for n in nuke.allNodes():
    n["selected"].setValue(False)
src["selected"].setValue(True)
g = ui.create_node()
assert g.input(0).name() == src.name(), "create_node no conectó el clip"
g2 = ui.create_node()  # un segundo nodo no puede llamarse igual: compartirían la carpeta de temporales
assert g2.name() != g.name(), "dos nodos con el mismo nombre: %s" % g.name()
print("nombres:", g.name(), g2.name())
nuke.delete(g2)
g.setInput(1, hint)
assert g["first"].value() == FIRST and g["last"].value() == LAST, "first/last no siguen al clip"
# ningún knob nuestro puede llamarse como uno interno del Group: el interno lo tapa (v0.5.0: "window" daba int(None))
builtin = set(nuke.nodes.Group(name="tmp_builtin").knobs())
nuke.delete(nuke.toNode("tmp_builtin"))
ours = set(re.findall(r'nuke\.\w+_Knob\("(\w+)"', open(ui.__file__, encoding="utf-8").read()))
assert not (ours & builtin), "knobs que chocan con internos del Group: %s" % sorted(ours & builtin)
assert g["temporal_window"].Class() == "Enumeration_Knob" and ui._window(g) is None
base, work = ui._dirs(g)
assert not work.lower().startswith(os.path.join(WORK, "Comp").lower()), "los temporales no deben quedar en el shot: %s" % work
plate0 = os.path.join(work, "in", "plate.%d.exr" % FIRST)
name = core.clip_base(PLATE) + "_ck"
assert g["out_name"].value() == name, "el nombre automático no quedó escrito al crear el nodo: %r" % g["out_name"].value()
assert ui._destination(g, src) == (os.path.normpath(PRE), name, 1), ui._destination(g, src)
# el nombre escrito se respeta si el usuario lo cambia, y si lo vacía vuelve a ser el automático
g["out_name"].setValue("MI_NOMBRE")
assert ui._destination(g, src)[1] == "MI_NOMBRE" and g["out_name"].value() == "MI_NOMBRE"
g["out_name"].setValue("")
assert ui._destination(g, src)[1] == name and g["out_name"].value() == name, "vaciar el nombre no restauró el automático"
# un nodo creado antes de que existiera el campo oculto lo recibe solo
g.removeKnob(g["out_name_auto"])
g["out_name"].setValue("")
assert ui._destination(g, src)[1] == name and g.knob("out_name_auto") is not None, "no migró el nodo sin out_name_auto"
# al cambiar el clip conectado, un nombre sin tocar lo sigue; uno retocado no
other = nuke.nodes.Read(name="otro", file="X:/shot/OTRO_CLIP_v002.%04d.exr", first=1, last=50)
g.setInput(0, other)
followed = g["out_name"].value() == "OTRO_CLIP_v002_ck"
print("inputChange actualizó el nombre:", followed, "->", g["out_name"].value())
assert ui._destination(g, other)[1] == "OTRO_CLIP_v002_ck", "el nombre automático no siguió al clip"
assert (g["first"].value(), g["last"].value()) == (1, 50), "el rango no siguió al clip nuevo"
g["out_name"].setValue("RETOCADO")
g.setInput(0, src)
assert ui._destination(g, src)[1] == "RETOCADO", "un nombre retocado a mano fue pisado al cambiar el clip"
assert (g["first"].value(), g["last"].value()) == (FIRST, LAST), "el rango no volvió al del clip"
g["out_name"].setValue("")
assert ui._destination(g, src)[1] == name
# un rango cambiado a mano se respeta al cambiar el clip; el botón "Rango del clip" lo restaura
g["last"].setValue(1005)
g.setInput(0, other)
g.setInput(0, src)
assert (g["first"].value(), g["last"].value()) == (FIRST, 1005), "un rango retocado a mano fue pisado"
ui.reset_range(g)
assert (g["first"].value(), g["last"].value()) == (FIRST, LAST), "el botón no restauró el rango del clip"
nuke.delete(other)


def seq(kind, version):
    """(carpeta, archivos .exr) de la secuencia final de `kind` en esa versión."""
    d = os.path.dirname(core.result_path(PRE, name, kind, version))
    return d, sorted(f for f in os.listdir(d) if f.endswith(".exr")) if os.path.isdir(d) else []


def expect_seq(kind, version):
    d, files = seq(kind, version)
    n = "%s_%s_v%02d" % (name, kind, version)
    assert files == ["%s.%d.exr" % (n, f) for f in range(FIRST, LAST + 1)], (d, files)


def step(title):
    t = time.time()
    print("\n=== %s" % title, flush=True)
    return t


# 1) primera corrida, con hint
t = step("1. primera corrida con hint")
ui.run(g)
print("estado:", g["status"].value().replace("\n", " | "), "| %d s" % (time.time() - t))
assert "conversión nueva" in g["status"].value(), g["status"].value()
assert len([f for f in os.listdir(os.path.join(work, "in")) if f.endswith(".exr")]) == 8
assert len([f for f in os.listdir(os.path.join(work, "hint")) if f.endswith(".png")]) == 8
for k in ui.KINDS:
    expect_seq(k, 1)
assert not os.path.exists(os.path.join(WORK, "Comp", "1_projects", "_corridorkey")), "dejó temporales junto al script"
expect_pixels(g)
m1 = os.path.getmtime(plate0)
with g:
    sw = nuke.toNode("sw")
    assert all(sw.input(i) is not None for i in range(len(ui.OUTPUT_ITEMS))), "el Switch no quedó cableado"
    assert nuke.toNode("r_alpha")["file"].value().startswith(PRE.replace("\\", "/")), "los Read no apuntan a la salida"
print("nodo:", g.width(), "x", g.height(), "(clip %d x %d)" % (src.width(), src.height()))
assert (g.width(), g.height()) == (src.width(), src.height()), "la salida no volvió al tamaño del clip"
for i, view in enumerate(ui.OUTPUT_ITEMS[:4]):  # esto además deja frames de la salida leídos por Nuke, como un visor abierto
    g["output"].setValue(i)
    w = nuke.nodes.Write(inputs=[g], file=os.path.join(WORK, "check_%d.exr" % i).replace("\\", "/"), file_type="exr")
    w["channels"].setValue("rgba")
    w["datatype"].setValue("16 bit half")
    w["colorspace"].setValue("Utility - Raw")
    nuke.execute(w, 1004, 1004, 1)
    nuke.delete(w)
g["output"].setValue(0)


def rgb(node, ch=("red", "green", "blue")):
    return tuple(node.sample(c, 5, 5, frame=1004) for c in ch)


def expect_rgb(label, got, want, tol=0.012):  # half float: 0.6 se lee como 0.5996
    assert all(abs(a - b) <= tol for a, b in zip(got, want)), "%s: salió %s y debía salir %s" % (label, got, want)
    print("   ok %-26s %s" % (label, tuple(round(v, 3) for v in got)))


# 1b) despill en vivo y vistas: cambiar el despill NO corre el modelo, y las fórmulas dan lo esperado
if FAKE:
    step("1b. despill en vivo y vistas (sin volver a procesar)")
    runs0, al, fg = RUNS[0], RUNS[0] * 0.1, FG_COLOR
    g["output"].setValue(0)  # cutout = despill(fg) * alpha (premultiplicado)
    for label, mode, s, want in (("Average 0.5 (como CorridorKey)", 0, 0.5, (0.275, 0.45, 0.475)),
                                 ("Average 1.0", 0, 1.0, (0.35, 0.3, 0.55)),
                                 ("Máximo 0.5", 1, 0.5, (0.25, 0.5, 0.45)), ("Ninguno", 2, 0.5, fg)):
        g["despill_mode"].setValue(ui.DESPILL_ITEMS[mode])
        g["despill"].setValue(s)
        expect_rgb("cutout, " + label, rgb(g), tuple(v * al for v in want))
    g["despill_mode"].setValue(ui.DESPILL_ITEMS[0])
    g["despill"].setValue(0.5)
    g["output"].setValue(1)
    expect_rgb("alpha", rgb(g), (al,) * 3)
    g["output"].setValue(2)
    expect_rgb("fg crudo", rgb(g), fg)
    g["output"].setValue(3)  # straight: fg crudo SIN premultiplicar y el alpha en el canal alpha
    expect_rgb("straight rgb", rgb(g), fg)
    expect_rgb("straight alpha", rgb(g, ("alpha",)), (al,))
    g["output"].setValue(0)
    # pantalla azul: este fg (verde dominante, azul = promedio de r y g) no tiene exceso de azul -> no cambia
    g["despill_color"].setValue(ui.SCREEN_ITEMS[1])
    for mode in (0, 1):
        g["despill_mode"].setValue(ui.DESPILL_ITEMS[mode])
        g["despill"].setValue(1.0)
        expect_rgb("cutout azul, " + ui.DESPILL_ITEMS[mode], rgb(g), tuple(v * al for v in fg))
    g["despill_color"].setValue(ui.SCREEN_ITEMS[0])
    g["despill_mode"].setValue(ui.DESPILL_ITEMS[0])
    g["despill"].setValue(0.5)
    assert RUNS[0] == runs0, "cambiar el despill volvió a correr el modelo"

    # 1c) ventana temporal, confirmación y chequeo de disco
    step("1c. ventana temporal y disco")
    assert CALL["window"] is None and CALL["outputs"] == ["alpha", "fg"], CALL
    gpu = core.gpu_info()
    small = gpu is None or gpu[1] <= core.LOW_MEM_MAX_MIB
    for item, want in (("24", 24), ("Frame a frame", 1)):
        g["temporal_window"].setValue(item)
        del ASKS[:]
        ui.run(g)
        assert CALL["window"] == want and not ASKS, (item, CALL, ASKS)
        assert CALL["low_mem"] == (small and want > 1), "memoria baja mal decidida: %s" % CALL  # HD < 3 Mpx
        print("   ok ventana %-14s -> window=%s low_mem=%s | %s" % (item, CALL["window"], CALL["low_mem"],
                                                                   g["status"].value().split("\n")[2]))
    if small:  # 48 frames en HD supera lo recomendado para 12-16 GB: pregunta; si dices que no, no corre
        g["temporal_window"].setValue("48")
        ANSWER[0], runs1 = False, RUNS[0]
        del ASKS[:], MSGS[:]
        ui.run(g)
        assert ASKS and RUNS[0] == runs1 and MSGS and "Cancelado" in MSGS[0], (ASKS, MSGS)
        ANSWER[0] = True
        print("   ok ventana 48 en HD: pidió confirmación y no corrió al cancelar")
    g["temporal_window"].setValue("Auto")
    real_problems, runs1 = core.disk_problems, RUNS[0]
    core.disk_problems = lambda needs, free=None: ["X: necesita ~9.0 GB y tiene 1.0 GB libres"]
    del MSGS[:]
    ui.run(g)
    core.disk_problems = real_problems
    assert RUNS[0] == runs1 and MSGS and "No hay espacio suficiente" in MSGS[0], MSGS
    print("   ok sin disco: avisa y no corre")

# 2) cambiar solo un parámetro del modelo: NO reconvierte y SOBRESCRIBE la v01 aunque Nuke haya leído frames de ella
t = step("2. cambia la calidad del hint: reutiliza la conversión y sobrescribe la v01")
g["hint_quality"].setValue(0.9)
ui.run(g)
print("estado:", g["status"].value().replace("\n", " | "), "| %d s" % (time.time() - t))
assert "conversión reutilizada" in g["status"].value(), g["status"].value()
assert os.path.getmtime(plate0) == m1, "reescribió el plate sin necesidad"
for k in ui.KINDS:
    expect_seq(k, 1)
assert not os.path.exists(seq("alpha", 2)[0]), "creó la v02 sin que la pidieran"
expect_pixels(g)

# 2b) un Read AJENO al nodo (el que el artista pone en su comp) tiene abierto un frame de la v01: no se puede reemplazar.
# El nodo debe avisar, dejar la v01 entera con sus píxeles y sus Read funcionando; al soltarlo, debe poder.
t = step("2b. otro Read con la v01 abierta: avisa y no mezcla")
ext = nuke.nodes.Read(name="comp_read", file=core.result_path(PRE, name, "fg", 1).replace("\\", "/"), first=FIRST, last=LAST)
w = nuke.nodes.Write(inputs=[ext], file=os.path.join(WORK, "check_ext.exr").replace("\\", "/"), file_type="exr")
nuke.execute(w, 1004, 1004, 1)
nuke.delete(w)
del MSGS[:]
ui.run(g)
assert MSGS and "Hay frames abiertos" in MSGS[0], MSGS
RUNS[0] -= 1  # esa corrida no se publicó
for k in ui.KINDS:
    expect_seq(k, 1)
expect_pixels(g)
with g:
    assert all(nuke.toNode("r_" + k) is not None and nuke.toNode("rf_" + k).input(0) is nuke.toNode("r_" + k) for k in ui.KINDS), \
        "tras el fallo los Read del nodo no quedaron restaurados"
nuke.delete(ext)
ui.run(g)
expect_pixels(g)
assert "Salida v01" in g["status"].value() and not MSGS[1:], (g["status"].value(), MSGS)

# 3) subir la versión: conserva la v01 y crea la v02
t = step("3. versión 2: la v01 queda intacta")
before = {f: os.path.getmtime(os.path.join(seq("alpha", 1)[0], f)) for f in seq("alpha", 1)[1]}
g["version"].setValue(2)
ui.run(g)
print("estado:", g["status"].value().replace("\n", " | "), "| %d s" % (time.time() - t))
for k in ui.KINDS:
    expect_seq(k, 1)
    expect_seq(k, 2)
after = {f: os.path.getmtime(os.path.join(seq("alpha", 1)[0], f)) for f in seq("alpha", 1)[1]}
assert before == after, "tocó la v01 al crear la v02"
with g:
    assert "_v02" in nuke.toNode("r_alpha")["file"].value(), "los Read no pasaron a la v02"
expect_pixels(g)

# 4) cambiar algo aguas arriba (un Grade): SÍ debe reconvertir
t = step("4. un Grade aguas arriba: reconvierte")
gr = nuke.nodes.Grade(inputs=[src], multiply=1.1)
g.setInput(0, gr)
time.sleep(1.1)
ui.run(g)
print("estado:", g["status"].value().replace("\n", " | "), "| %d s" % (time.time() - t))
assert "conversión nueva" in g["status"].value(), g["status"].value()
assert os.path.getmtime(plate0) > m1, "no reescribió el plate tras cambiar el Grade"

# 5) sin hint: no debe quedar el hint viejo; los temporales no se acumulan
t = step("5. sin hint")
g.setInput(1, None)
ui.run(g)
print("estado:", g["status"].value().replace("\n", " | "), "| %d s" % (time.time() - t))
assert not os.path.isdir(os.path.join(work, "hint")), "quedó el hint viejo"
outs = [d for d in os.listdir(work) if d.startswith("out_")]
residuo = sum(len(files) for d in outs for _, _, files in os.walk(os.path.join(work, d)))
print("carpetas out_* temporales:", outs, "| archivos:", residuo)
assert residuo == 0, "quedaron resultados en los temporales: %s" % outs
for f in seq("alpha", 2)[1] + seq("fg", 2)[1]:
    assert not f.endswith(".old")

# 5b) 720p: el plate convertido sale a 1280 de ancho, el nodo devuelve el tamaño del clip, y cambiar la resolución reconvierte
t = step("5b. resolución 720p")
g["resolution"].setValue(ui.RES_ITEMS[1])
ui.run(g)
print("estado:", g["status"].value().replace("\n", " | "), "| %d s" % (time.time() - t))
assert "720p interno" in g["status"].value() and "conversión nueva" in g["status"].value(), g["status"].value()
chk = nuke.nodes.Read(file=os.path.join(work, "in", "plate.%d.exr" % FIRST).replace("\\", "/"))
assert chk.width() == 1280, "el plate convertido mide %d de ancho, no 1280" % chk.width()
nuke.delete(chk)
assert (g.width(), g.height()) == (src.width(), src.height()), "la salida no volvió al tamaño del clip"
g["resolution"].setValue(ui.RES_ITEMS[0])  # y volver a HD (los pasos siguientes lo esperan)

# 6) guardar, reabrir y comprobar que el nodo y sus resultados sobreviven; borrar temporales
step("6. guardar y reabrir")
gname = g.name()  # tras scriptClear() el objeto g ya no apunta a nada
g["temporal_window"].setValue("16")  # sin procesar: solo para ver que sobrevive a guardar y reabrir
nuke.scriptSaveAs(script, overwrite=1)  # en headless scriptSave() sin nombre no escribió el grafo
nuke.scriptClear()
try:
    nuke.scriptOpen(script)
except RuntimeError as e:  # en headless scriptOpen "falla" pero carga
    print("scriptOpen:", e)
g2 = nuke.toNode(gname)
assert g2 is not None and g2.knob("run_btn") is not None, "el nodo no sobrevivió"
assert g2["version"].value() == 2
assert ui._window(g2) == 16, "la ventana temporal no sobrevivió a guardar y reabrir: %r" % ui._window(g2)
with g2:
    assert nuke.toNode("r_fg") is not None and nuke.toNode("sw").input(0) is not None
print("reabierto:", g2.name(), g2.width(), "x", g2.height(), "| estado:", g2["status"].value().replace("\n", " | "))
ui.clean_inputs(g2)
assert not os.path.isdir(os.path.join(work, "in")), "clean_inputs no borró el plate convertido"
for k in ui.KINDS:
    expect_seq(k, 2)  # la salida no se toca
ui.clean_orphans()
print("NODE_TEST_DONE")
