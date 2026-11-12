# -*- coding: utf-8 -*-
"""Autoprueba de core.py (sin Nuke): python tests\\test_core.py"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nuke"))
from corridorkey_nuke import core  # noqa: E402

CFG = {"python": r"C:\x y\python.exe", "infer": r"C:\x y\infer.py", "ffmpeg": r"C:\x y\ffmpeg.exe"}


class Argv(unittest.TestCase):
    def test_basico(self):
        a = core.build_argv(CFG, "in", "out", 24, ["alpha", "fg"], "tmp")
        self.assertIn("--frame_dir_linear", a)
        self.assertEqual(a[a.index("--output_format") + 1], "exr")
        self.assertEqual(a[a.index("--outputs") + 1:a.index("--despill_strength")], ["alpha", "fg"])
        self.assertNotIn("--hint_video", a)
        self.assertNotIn("--low_vram", a)

    def test_hint_y_memoria(self):
        a = core.build_argv(CFG, "in", "out", 24, ["alpha"], "tmp", hint_dir="h", hint_quality=0.95, low_mem=True)
        self.assertEqual(a[a.index("--hint_video") + 1], "h")
        self.assertEqual(a[a.index("--hint_quality") + 1], "0.95")
        self.assertEqual(a[a.index("--hann_chunk") + 1], "8")
        self.assertIn("--low_vram", a)

    def test_hint_primer_frame_y_arrastre(self):
        a = core.build_argv(CFG, "in", "out", 24, ["alpha"], "tmp", hint_dir="h", hint_first=True)
        self.assertEqual(a[a.index("--hint_first_frame") + 1], "h")
        self.assertNotIn("--hint_video", a)
        self.assertNotIn("--carry_hint_quality", a)  # sin valor explícito CorridorKey usa su 0.95
        a = core.build_argv(CFG, "in", "out", 24, ["alpha"], "tmp", hint_dir="h", carry_quality=0.8)
        self.assertEqual(a[a.index("--carry_hint_quality") + 1], "0.8")
        a = core.build_argv(CFG, "in", "out", 24, ["alpha"], "tmp", hint_dir="h", carry_quality=0.8, no_carry=True)
        self.assertIn("--no_carry_hint", a)
        self.assertNotIn("--carry_hint_quality", a)
        a = core.build_argv(CFG, "in", "out", 24, ["alpha"], "tmp", no_carry=True, carry_quality=0.8)  # sin hint: nada
        self.assertNotIn("--no_carry_hint", a)

    def test_ventana(self):
        def hann(a):
            return a[a.index("--hann_chunk") + 1], a[a.index("--hann_stride") + 1]
        self.assertNotIn("--hann_chunk", core.build_argv(CFG, "in", "out", 24, ["alpha"], "tmp"))  # automática
        self.assertEqual(hann(core.build_argv(CFG, "in", "out", 24, ["alpha"], "tmp", window=24)), ("24", "12"))
        self.assertEqual(hann(core.build_argv(CFG, "in", "out", 24, ["alpha"], "tmp", window=1)), ("1", "1"))
        a = core.build_argv(CFG, "in", "out", 24, ["alpha"], "tmp", low_mem=True, window=16)
        self.assertEqual(hann(a), ("16", "8"))  # la ventana elegida manda, y la memoria baja se mantiene
        self.assertEqual(a.count("--hann_chunk"), 1)
        self.assertIn("--low_vram", a)

    def test_limite_de_ventana(self):
        self.assertEqual(core.window_limit(1280, 720), 80)
        self.assertEqual(core.window_limit(1920, 1080), 24)
        self.assertEqual(core.window_limit(3840, 2160), 8)

    def test_window_limit_por_gpu(self):
        for mib, res, want in ((12282, (3840, 2160), 8), (6144, (3840, 2160), 2), (8192, (3840, 2160), 4),
                               (6144, (2560, 1440), 4), (4096, (1920, 1080), 2), (3072, (1280, 720), 4),
                               (24564, (1920, 1080), 48), (81920, (3840, 2160), 48)):
            self.assertEqual(core.window_limit(res[0], res[1], mib), want, (mib, res))

    def test_reintento_por_memoria(self):
        self.assertEqual([core.smaller_window(w) for w in (80, 24, 16, 8, 3, 2, 1)], [48, 16, 8, 4, 2, 1, None])
        self.assertTrue(core.is_oom("torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 1.11 GiB"))
        self.assertFalse(core.is_oom("window 3/8"))
        self.assertEqual(core.auto_window("Auto VRAM: 7.8 GB -> hann_chunk=24, hann_stride=12, low_vram=True"), 24)
        self.assertIsNone(core.auto_window("nada"))

    def test_memoria_minima(self):
        a = core.build_argv(CFG, "in", "out", 24, ["alpha"], "tmp", low_mem="min", window=2)
        self.assertEqual(a[a.index("--low_vram_foundation_chunk") + 1], "1")
        self.assertEqual(a[a.index("--hann_chunk") + 1], "2")

    def test_carpeta_salida(self):
        self.assertEqual(core.output_dir("out", os.path.join("run", "in"), "alpha"), os.path.join("out", "in_alpha_exr"))


class Progreso(unittest.TestCase):
    def test_sin_ventanas(self):
        self.assertEqual(core.progress("cargando", 0, 74)[0], 0.02)

    def test_etapa1_y_2(self):
        log = "window 1/6 [0:24]\nwindow 3/6 [24:48]\n"
        f, msg = core.progress(log, 0, 74)
        self.assertAlmostEqual(f, 0.35)
        self.assertIn("3 de 6", msg)
        f, msg = core.progress("window 6/6 [50:74]", 37, 74)
        self.assertAlmostEqual(f, 0.85)

    def test_exit_code(self):
        self.assertIsNone(core.exit_code("window 1/6"))
        self.assertEqual(core.exit_code("x\nCK_EXIT=0 \n"), 0)
        self.assertEqual(core.exit_code("CK_EXIT=1 "), 1)


class Config(unittest.TestCase):
    def test_sin_instalar(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ[core.HOME_ENV] = d
            with self.assertRaises(RuntimeError) as cm:
                core.load_config()
            self.assertIn("instalar.bat", str(cm.exception))


class Borrado(unittest.TestCase):
    def test_solo_dentro_de_la_base(self):
        with tempfile.TemporaryDirectory() as d:
            base = os.path.join(d, "_corridorkey")
            dentro, fuera = os.path.join(base, "nodo", "in"), os.path.join(d, "importante")
            os.makedirs(dentro)
            os.makedirs(fuera)
            with self.assertRaises(RuntimeError):
                core.safe_rmtree(fuera, base)
            with self.assertRaises(RuntimeError):
                core.safe_rmtree(base, base)  # la base misma tampoco
            with self.assertRaises(RuntimeError):  # prefijo parecido: "_corridorkey2" no está dentro de "_corridorkey"
                core.safe_rmtree(os.path.join(d, "_corridorkey2"), base)
            core.safe_rmtree(dentro, base)
            core.safe_rmtree(os.path.join(base, "no_existe"), base)  # inexistente: no falla
            self.assertFalse(os.path.isdir(dentro))
            self.assertTrue(os.path.isdir(fuera))


class Nombres(unittest.TestCase):
    def test_clip_base(self):
        for ruta, esperado in (("X:/s/SHOW_101_1200_aPlate_v001.%04d.exr", "SHOW_101_1200_aPlate_v001"),
                               ("x/SHOW_101_0100_aPlate_v001.####.exr", "SHOW_101_0100_aPlate_v001"),
                               ("x/shot_plate.1001.exr", "shot_plate"),
                               ("x/shot_plate_1001.exr", "shot_plate"),
                               ("x/shot_plate_v001.exr", "shot_plate_v001")):  # sin número de frame: no tocar la versión
            self.assertEqual(core.clip_base(ruta), esperado)

    def test_prerenders_from_clip(self):
        with tempfile.TemporaryDirectory() as t:
            shot = os.path.join(t, "SHOT_0100")
            for d in ("_input/plate_v001", "comp/2_prerenders", "Roto/2_prerenders/matte_v01", "suelto"):
                os.makedirs(os.path.join(shot, d))
            f = lambda *p: os.path.join(shot, *p)
            self.assertEqual(core.prerenders_from_clip(f("_input", "plate_v001", "p.%04d.exr")), f("comp", "2_prerenders"))
            self.assertEqual(core.prerenders_from_clip(f("Roto", "2_prerenders", "matte_v01", "m.%04d.exr")),
                             f("Roto", "2_prerenders"))
            fuera = os.path.join(t, "descargas")
            os.makedirs(fuera)
            self.assertIsNone(core.prerenders_from_clip(os.path.join(fuera, "clip.mov")))

    def test_process_label(self):
        self.assertEqual(core.process_label("python.exe", r"C:\x\envs\sharp-nodes\python.exe persistent_worker.py"),
                         "python")  # sin 'comfy' en la línea no se adivina
        self.assertEqual(core.process_label("python.exe", r"C:\comfy-env\envs\sharp-nodes\python.exe w.py"),
                         "ComfyUI (modelo de SHARP)")
        self.assertEqual(core.process_label("python.exe", r"python.exe -s ComfyUI\main.py --port 8000"), "ComfyUI (python)")
        self.assertEqual(core.process_label("Nuke17.1.exe", ""), "Nuke17.1")

    def test_frame_path(self):
        for patron in ("x/p.%04d.exr", "x/p.####.exr"):
            self.assertEqual(core.frame_path(patron, 1001), "x/p.1001.exr")
        self.assertEqual(core.frame_path("x/still.exr", 1001), "x/still.exr")

    def test_run_key(self):
        a, b = core.run_key("X:/s/comp/1_projects/SHOT_comp_v012.nk"), core.run_key(r"X:\s\comp\1_projects\SHOT_comp_v013.nk")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("SHOT_comp_"))
        self.assertNotEqual(a, core.run_key("X:/otro/1_projects/SHOT_comp_v012.nk"))

    def test_purge_old_runs(self):
        with tempfile.TemporaryDirectory() as runs:
            keep, viejo, nuevo = (os.path.join(runs, d) for d in ("keep", "viejo", "nuevo"))
            for d in (keep, viejo, nuevo):
                os.makedirs(os.path.join(d, "nodo"))
            hace_un_mes = time.time() - 30 * 86400
            os.utime(viejo, (hace_un_mes, hace_un_mes))
            os.utime(keep, (hace_un_mes, hace_un_mes))
            core.purge_old_runs(keep)
            self.assertEqual(sorted(os.listdir(runs)), ["keep", "nuevo"])

    def test_alive(self):
        self.assertTrue(core.alive(os.getpid()))
        self.assertFalse(core.alive(4194300))  # PID que Windows no asigna (múltiplo de 4 fuera de rango habitual)

    def test_prerenders_dir(self):
        p = core.prerenders_dir(r"X:\SHOW\101\SHOW_101_0500\Comp\1_projects\sub\script.nk")
        self.assertEqual(p, r"X:\SHOW\101\SHOW_101_0500\Comp\2_prerenders")
        self.assertIsNone(core.prerenders_dir(r"C:\otra\cosa\script.nk"))

    def test_result_path(self):
        p = core.result_path("out", "SHOW_101_0100_ck", "alpha", 2)
        self.assertEqual(p, os.path.join("out", "SHOW_101_0100_ck_alpha_v02", "SHOW_101_0100_ck_alpha_v02.%04d.exr"))


class Despill(unittest.TestCase):
    """Las expresiones de los nodos Expression usan sintaxis que también es Python: se evalúan aquí y se comparan con
    la regla de CorridorKey (runtime.py:604) generalizada al canal de la pantalla."""

    @staticmethod
    def ref(rgb, amt, screen, method):
        k = 1 if screen == 0 else 2  # canal de la pantalla: verde o azul
        o = [i for i in range(3) if i != k]
        lim = (rgb[o[0]] + rgb[o[1]]) / 2 if method == "avg" else max(rgb[o[0]], rgb[o[1]])
        spill = max(rgb[k] - lim, 0)
        out = list(rgb)
        out[k] -= amt * spill
        for i in o:
            out[i] += amt * spill / 2
        return out

    def test_contra_la_regla(self):
        for method in ("avg", "max"):
            for screen in (0, 1):
                for rgb in ((0.2, 0.6, 0.4), (0.2, 0.4, 0.7), (0.8, 0.6, 0.5), (0.5, 0.5, 0.5), (3.7, 4.1, 1.4)):
                    for amt in (0.0, 0.5, 1.0):
                        env = dict(zip("rgb", rgb), amt=amt, scr=screen)
                        env["sg"], env["sb"] = (eval(e, {"max": max}, env) for e in core.SPILL[method])
                        got = [eval(e, {"max": max}, env) for e in core.DESPILL_EXPR]
                        want = self.ref(rgb, amt, screen, method)
                        for a, b in zip(got, want):
                            self.assertAlmostEqual(a, b, places=9, msg=(method, screen, rgb, amt))

    def test_average_como_corridorkey(self):
        for a, b in zip(self.ref((0.2, 0.6, 0.4), 0.5, 0, "avg"), (0.275, 0.45, 0.475)):  # el valor del test de Nuke
            self.assertAlmostEqual(a, b)


class Disco(unittest.TestCase):
    def test_necesidad(self):
        tmp, out = core.disk_need_mb(1920, 1080, 100, convert=True)
        mpx = 1920 * 1080 / 1e6
        self.assertAlmostEqual(out, 100 * mpx * 4.5)
        self.assertAlmostEqual(tmp, out + 100 * mpx * 4.2)
        self.assertAlmostEqual(core.disk_need_mb(1920, 1080, 100, convert=False)[0], out)

    def test_problemas_por_unidad(self):
        libre = {"C:": 50 * 1024, "D:": 1 * 1024}
        free = lambda p: libre[os.path.splitdrive(p)[0].upper()]
        self.assertEqual(core.disk_problems([(r"C:\tmp", 1000), (r"D:\salida", 100)], free)[0][:2], "D:")
        self.assertEqual(len(core.disk_problems([(r"C:\tmp", 1000), (r"D:\salida", 100)], free)), 1)
        self.assertEqual(core.disk_problems([(r"C:\tmp", 1000), (r"C:\salida", 1000)], free), [])  # 50 GB alcanzan
        self.assertEqual(len(core.disk_problems([(r"C:\a", 30 * 1024), (r"C:\b", 20 * 1024)], free)), 1)  # se suman

    def test_libre_en_carpeta_que_no_existe(self):
        self.assertGreater(core.free_mb(os.path.join(tempfile.gettempdir(), "no", "existe", "aun")), 0)


class Publicar(unittest.TestCase):
    def _origen(self, d, n, contenido, sub="src"):
        src = os.path.join(d, sub)
        os.makedirs(src, exist_ok=True)
        for i in range(n):
            with open(os.path.join(src, "alpha_%06d.exr" % i), "w") as f:
                f.write("%s%d" % (contenido, i))
        return src

    def _leer(self, pattern, frame):
        with open(pattern % frame) as f:
            return f.read()

    def test_nuevo_y_sobrescribe(self):
        with tempfile.TemporaryDirectory() as d:
            pat = os.path.join(d, "salida", "a_v01", "a_v01.%04d.exr")
            core.publish([(self._origen(d, 3, "nuevo"), pat)], 1001)
            self.assertEqual(self._leer(pat, 1001), "nuevo0")
            self.assertEqual(self._leer(pat, 1003), "nuevo2")
            self.assertEqual(os.listdir(os.path.join(d, "src")), [])  # movió, no copió
            core.publish([(self._origen(d, 2, "otro"), pat)], 1001)  # menos frames: no quedan los viejos
            self.assertEqual(sorted(os.listdir(os.path.dirname(pat))), ["a_v01.1001.exr", "a_v01.1002.exr"])
            self.assertEqual(self._leer(pat, 1002), "otro1")

    @unittest.skipUnless(os.name == "nt", "el bloqueo de archivos abiertos es de Windows")
    def test_frame_abierto_no_mezcla(self):
        with tempfile.TemporaryDirectory() as d:
            pat = os.path.join(d, "salida", "a_v01", "a_v01.%04d.exr")
            core.publish([(self._origen(d, 3, "viejo"), pat)], 1001)
            with open(pat % 1002):  # Nuke tiene este frame abierto
                with self.assertRaises(RuntimeError) as cm:
                    core.publish([(self._origen(d, 3, "nuevo"), pat)], 1001)
            self.assertIn("Sube la versión", str(cm.exception))
            self.assertEqual([self._leer(pat, f) for f in (1001, 1002, 1003)], ["viejo0", "viejo1", "viejo2"])
            self.assertEqual(len(os.listdir(os.path.dirname(pat))), 3)  # sin .old sueltos

    @unittest.skipUnless(os.name == "nt", "el bloqueo de archivos abiertos es de Windows")
    def test_dos_secuencias_todo_o_nada(self):
        """Si la segunda secuencia está bloqueada, la primera tampoco se reemplaza (alpha nuevo + fg viejo = mezcla)."""
        with tempfile.TemporaryDirectory() as d:
            a, b = (os.path.join(d, "salida", n, n + ".%04d.exr") for n in ("alpha_v01", "fg_v01"))
            def origenes(c):
                return [(self._origen(d, 2, c + "A", "srcA"), a), (self._origen(d, 2, c + "B", "srcB"), b)]

            core.publish(origenes("viejo"), 1001)
            with open(b % 1002):  # solo el fg tiene un frame abierto
                with self.assertRaises(RuntimeError):
                    core.publish(origenes("nuevo"), 1001)
            self.assertEqual([self._leer(a, 1001), self._leer(a, 1002)], ["viejoA0", "viejoA1"])
            self.assertEqual([self._leer(b, 1001), self._leer(b, 1002)], ["viejoB0", "viejoB1"])
            core.publish(origenes("nuevo"), 1001)  # soltado: ahora sí
            self.assertEqual([self._leer(a, 1002), self._leer(b, 1002)], ["nuevoA1", "nuevoB1"])


@unittest.skipUnless(os.name == "nt", "WMI solo en Windows")
class Wmi(unittest.TestCase):
    def test_spawn_con_espacios_y_codigo_de_salida(self):
        with tempfile.TemporaryDirectory(prefix="ck test ") as d:  # ruta con espacios a propósito
            for cmd, esperado in ((["cmd.exe", "/c", "echo", "hola"], 0), (["cmd.exe", "/c", "exit", "3"], 1)):
                log = os.path.join(d, "run %d.log" % esperado)
                core.spawn_detached(cmd, d, log)
                for _ in range(60):
                    if core.exit_code(core.read_log(log)) is not None:
                        break
                    time.sleep(0.5)
                self.assertEqual(core.exit_code(core.read_log(log)), esperado, core.read_log(log))


if __name__ == "__main__":
    unittest.main(verbosity=2)
