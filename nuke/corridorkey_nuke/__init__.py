# -*- coding: utf-8 -*-
"""CorridorKey para Nuke. `register()` agrega los menús; se llama desde menu.py (lo escribe instalar.bat)."""
__version__ = "0.5.1"


def register():
    import nuke
    from . import ui
    m = nuke.menu("Nuke").addMenu("CorridorKey")
    m.addCommand("Crear nodo CorridorKey", ui.create_node)
    m.addCommand("Limpiar carpetas de nodos borrados", ui.clean_orphans)
    m.addCommand("Abrir carpeta de trabajo", ui.open_home)
    m.addCommand("Diagnóstico", ui.diagnose)
    nuke.menu("Nodes").addCommand("Keyer/CorridorKey", ui.create_node)  # también con Tab > CorridorKey
