# -*- coding: utf-8 -*-
"""CorridorKey para Nuke. `register()` agrega los menús; se llama desde menu.py (lo escribe instalar.bat)."""
__version__ = "0.8.0"


def register():
    import nuke
    from . import ui
    m = nuke.menu("Nuke").addMenu("CorridorKey")
    m.addCommand("Crear nodo CorridorKey", ui.create_node)
    m.addCommand("Procesar seleccionados", ui.process_selected)
    m.addCommand("Ver cola", "import corridorkey_nuke.panel as p; p.show()")
    m.addCommand("Cancelar cola", ui.cancel_queue)
    m.addCommand("Limpiar carpetas de nodos borrados", ui.clean_orphans)
    m.addCommand("Abrir carpeta de trabajo", ui.open_home)
    m.addCommand("Diagnóstico", ui.diagnose)
    nuke.menu("Nodes").addCommand("Keyer/CorridorKey", ui.create_node)  # también con Tab > CorridorKey
    nuke.addOnScriptLoad(ui.resume)  # publica lo que la cola terminó mientras el script estaba cerrado
    if nuke.GUI:
        from . import panel
        panel.register()
