# -*- coding: utf-8 -*-
"""Cola de CorridorKey: corre infer.py shot por shot, en serie y fuera de Nuke. Así Nuke no se bloquea y la cola sigue
aunque se cierre. Uso: <python de CorridorKey> cola.py <cola.json>

cola.json es la lista de trabajos que escribe ui._enqueue. Cada trabajo deja su estado en <carpeta de trabajo>/estado.json:
en cola -> procesando -> listo | error. Nuke lo lee con un temporizador y publica los EXR (ui._tick).
Un proceso de infer.py por shot: cargar el modelo cuesta ~10 s de ~200 s por shot (medido, ver ROADMAP)."""
import os
import subprocess
import sys
import time
import traceback

try:
    from . import core
except ImportError:  # como script, fuera de Nuke
    import core


def _subprocess_infer(argv, log, cwd):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    with open(log, "w", encoding="utf-8") as f:
        p = subprocess.Popen(argv, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, env=env,
                             creationflags=core.CREATE_NO_WINDOW)
        with open(os.path.join(os.path.dirname(log), "infer.pid"), "w") as pf:  # para cancelar solo este shot
            pf.write(str(p.pid))
        return p.wait()


def run_job(cfg, job, infer):
    """Procesa un trabajo, en tramos si el hint va en un frame de referencia (ver core.split_at). Si falta memoria de
    GPU, reintenta con la ventana siguiente más chica (hasta frame a frame)."""
    work = job["work"]
    if core.get_state(work).get("estado") == "cancelado":
        return
    in_dir, log, tmp = os.path.join(work, "in"), os.path.join(work, "run.log"), os.path.join(core.home(), "tmp")
    os.makedirs(tmp, exist_ok=True)
    tramos = job.get("tramos") or [{"in": in_dir}]
    window, low_mem, asked, t0, outs = job["window"], job["low_mem"], None, time.time(), []
    for i, t in enumerate(tramos):
        hint = job["hint"]
        if t.get("relevo"):  # parte un frame después de la referencia, con el alpha del tramo anterior como hint
            hint = dict(hint, hint_dir=core.hint_relevo(tramos, outs, t), hint_first=True,
                        hint_quality=core.RELEVO_QUALITY, no_carry=False)
        while True:
            out_name = "out_" + time.strftime("%Y%m%d_%H%M%S")
            argv = core.build_argv(cfg, t["in"], os.path.join(work, out_name), job["fps"], job["outputs"], tmp,
                                   low_mem=low_mem, window=window, **hint)
            if core.get_state(work).get("estado") == "cancelado":  # desde el panel, entre tramos o reintentos
                return
            core.set_state(work, "procesando", pid=os.getpid(), out_name=out_name, tramo=i, inicio=t0)
            code = infer(argv, log, os.path.dirname(cfg["infer"]))
            if core.get_state(work).get("estado") == "cancelado":  # se cortó su infer.py: la cola sigue con el resto
                return
            text = core.read_log(log)
            time.sleep(1)  # el nombre de la carpeta de salida lleva el segundo: la siguiente no puede repetirlo
            if code == 0:
                break
            failed, window = core.retry_window(window, job["limit"], text) if core.is_oom(text) else (None, None)
            if window is None:
                core.set_state(work, "error", oom=core.is_oom(text), log=log,
                               msg="CorridorKey falló:\n\n%s\n\nLog completo: %s" % (core.log_tail(text), log))
                return
            asked, low_mem = asked or failed, low_mem or True
        outs.append(os.path.join(work, out_name))
    if job.get("tramos"):
        out_name = "out_" + time.strftime("%Y%m%d_%H%M%S")
        core.merge_tramos(tramos, outs, os.path.join(work, out_name), in_dir, job["outputs"])
    core.set_state(work, "listo", out_name=out_name, ventana=window, pedida=asked, segundos=int(time.time() - t0))


def _acquire(lock):
    """Una cola a la vez en la GPU: si hay otra corriendo, esta espera (sus trabajos siguen 'en cola')."""
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return
        except FileExistsError:
            try:
                with open(lock) as f:
                    pid = int(f.read().strip())
            except (OSError, ValueError):  # recién creado y aún vacío, o roto
                pid = None
                if time.time() - os.path.getmtime(lock) < 10:
                    time.sleep(1)
                    continue
            if pid is None or not core.alive(pid):  # la cola anterior murió sin soltarlo
                try:
                    os.remove(lock)
                except OSError:
                    pass
                continue
            time.sleep(5)


def run_queue(path, infer=None, cfg=None):
    cfg = cfg or core.load_config()
    jobs = core.read_json(path) or []
    lock = os.path.join(os.path.dirname(path), "cola.lock")
    _acquire(lock)
    try:
        for job in jobs:
            try:
                run_job(cfg, job, infer or _subprocess_infer)
            except Exception:
                core.set_state(job["work"], "error", msg="La cola falló en este shot:\n\n" + traceback.format_exc())
    finally:
        for p in (lock, path):
            try:
                os.remove(p)
            except OSError:
                pass


if __name__ == "__main__":
    run_queue(sys.argv[1])
