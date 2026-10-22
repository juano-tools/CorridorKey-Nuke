# -*- coding: utf-8 -*-
"""Flujo completo en Nuke headless contra una instalación de sandbox:
   Nuke17.0.exe --nukex -i -t tests\\nuke_job_test.py   (con CK_TEST_HOME, CK_TEST_NUKE, CK_TEST_PLATE, CK_TEST_OUT)."""
import os
import sys
import time

import nuke

HOME, NUKEDIR, PLATE, OUT = (os.environ[k] for k in ("CK_TEST_HOME", "CK_TEST_NUKE", "CK_TEST_PLATE", "CK_TEST_OUT"))
HINT = os.environ.get("CK_TEST_HINT")  # carpeta con hint_%04d.png (opcional, índice desde 0)
FIRST, LAST = int(os.environ.get("CK_TEST_FIRST", 1001)), int(os.environ.get("CK_TEST_LAST", 1074))
RES = os.environ.get("CK_TEST_RES", "1080p")

os.environ["CORRIDORKEY_HOME"] = HOME
sys.path.insert(0, NUKEDIR)  # el plugin tal como lo dejó install.ps1
import corridorkey_nuke  # noqa: E402
from corridorkey_nuke import ui  # noqa: E402

print("plugin", corridorkey_nuke.__version__, "desde", os.path.dirname(corridorkey_nuke.__file__))
root = nuke.root()
root["colorManagement"].setValue("OCIO")
root["OCIO_config"].setValue("aces_1.2")
root["fps"].setValue(24)
root["first_frame"].setValue(FIRST)
root["last_frame"].setValue(LAST)

src = nuke.nodes.Read(name="plate")
src["file"].fromUserText(PLATE)
src["first"].setValue(1001)
src["last"].setValue(1074)
src["colorspace"].setValue("ACES - ACES2065-1")  # lo que haría el artista; el default del Read en este config es scene_linear (ACEScg)
print("plate", src.width(), "x", src.height(), "cs", src["colorspace"].value())

hint = None
if HINT:  # un nodo con el matte en el alpha, como lo haría un Roto o un keyer
    h = nuke.nodes.Read(name="hint_png")
    h["file"].fromUserText(os.path.join(HINT, "hint_%04d.png"))
    h["first"].setValue(0)
    h["last"].setValue(73)
    h["frame_mode"].setValue("expression")
    h["frame"].setValue("frame-%d" % 1001)
    h["colorspace"].setValue("Utility - Raw")
    hint = nuke.nodes.Shuffle(inputs=[h], name="hint_alpha")
    hint["alpha"].setValue("red")

t0 = time.time()
run, made = ui.key(src, hint, FIRST, LAST, RES, run_dir=os.path.join(OUT, "run"))
print("KEY_OK en %d s; nodos: %s" % (time.time() - t0, [n.name() for n in made]))
for n in made:
    print("  ", n.name(), n.width(), "x", n.height())

# renderiza un frame de cada salida ya reescalada al formato del plate, para comparar fuera de Nuke
mid = (FIRST + LAST) // 2
for n in made:
    w = nuke.nodes.Write(inputs=[n], file=os.path.join(OUT, "check_%s.exr" % n.name().replace("Premult1", "cutout")).replace("\\", "/"),
                         file_type="exr")
    w["channels"].setValue("rgba")
    w["datatype"].setValue("16 bit half")
    w["colorspace"].setValue("Utility - Raw")
    nuke.execute(w, mid, mid, 1)
print("CHECK_FRAMES frame", mid)
print("JOB_TEST_DONE")
