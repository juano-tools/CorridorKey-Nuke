# -*- coding: utf-8 -*-
"""Panel "Cola de CorridorKey": los shots de la cola de todos los scripts, con su avance y su tiempo.
Solo muestra y cancela; publicar sigue siendo cosa del temporizador de cada script (ui._tick).
Se abre con CorridorKey > Ver cola y queda en Windows > Custom para acoplarlo donde se quiera."""
import os

import nuke

from . import core, ui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:  # Nuke 15
    from PySide2 import QtCore, QtGui, QtWidgets

PANEL_ID = "uk.co.corridorkey.cola"
COLORS = {"procesando": ui.AMBER, "en cola": "#a0a0a0", "listo": ui.GREEN, "publicado": ui.GREEN, "error": ui.RED,
          "cancelado": "#a0a0a0"}
COLS = ("shot", "script", "estado", "avance", "tiempo", "")


class ColaPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.summary = QtWidgets.QLabel()
        lay.addWidget(self.summary)
        self.table = QtWidgets.QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for c in range(1, len(COLS)):
            head.setSectionResizeMode(c, QtWidgets.QHeaderView.ResizeToContents)
        lay.addWidget(self.table)
        self.shape = None  # script abierto + (work, estado) de cada fila: si cambia, se rearman los botones
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh)
        self.refresh()

    def showEvent(self, e):  # el temporizador corre solo mientras el panel está a la vista
        self.refresh()
        self.timer.start()
        QtWidgets.QWidget.showEvent(self, e)

    def hideEvent(self, e):
        self.timer.stop()
        QtWidgets.QWidget.hideEvent(self, e)

    def refresh(self):
        try:
            rows = core.queue_rows()
        except Exception as e:  # un json a medio escribir no debe romper el panel
            self.summary.setText("No se pudo leer la cola: %s" % e)
            return
        n = {s: sum(r["estado"] == s for r in rows) for s in ("procesando", "en cola")}
        self.summary.setText("%d procesando · %d en cola" % (n["procesando"], n["en cola"]) if rows else
                             "La cola está vacía.")
        self.summary.setToolTip("Abajo quedan los terminados de las últimas 24 horas, de todos los scripts.")
        shape = [nuke.root().name()] + [(r["work"], r["estado"]) for r in rows]  # otro script: cambia "ir"
        if shape != self.shape:
            self.shape = shape
            self.table.setRowCount(len(rows))
            for i, r in enumerate(rows):
                self.table.setCellWidget(i, 3, None)
                self.table.setCellWidget(i, 5, self._buttons(r))
        for i, r in enumerate(rows):
            self._fill(i, r)

    def _fill(self, i, r):
        here = os.path.splitext(os.path.basename(r["script"]))[0] if r["script"] != "Root" else "sin guardar"
        tip = r["msg"] or r["detalle"] or r["work"]
        for c, text in ((0, r["shot"]), (1, here), (2, r["texto"]), (4, r["tiempo"])):
            item = self.table.item(i, c) or QtWidgets.QTableWidgetItem()
            item.setText(text)
            item.setToolTip(tip if c in (0, 2) else r["script"])
            if c == 2:
                item.setForeground(QtGui.QColor(COLORS.get(r["estado"], "#a0a0a0")))
            self.table.setItem(i, c, item)
        if r["estado"] == "procesando":
            bar = self.table.cellWidget(i, 3)
            if bar is None:
                bar = QtWidgets.QProgressBar()
                bar.setRange(0, 100)
                self.table.setCellWidget(i, 3, bar)
            bar.setValue(int((r["avance"] or 0) * 100))
            bar.setFormat("%p %")
            bar.setToolTip(r["detalle"])
        else:
            item = self.table.item(i, 3) or QtWidgets.QTableWidgetItem()
            item.setText(r["detalle"] if r["estado"] == "error" else "")
            item.setToolTip(tip)
            self.table.setItem(i, 3, item)

    def _buttons(self, r):
        box = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(box)
        lay.setContentsMargins(2, 0, 2, 0)
        node = _node_here(r)
        for label, tip, fn, on in (
                ("ir", "Selecciona el nodo y abre su panel" if node else
                 "Está en otro script: %s" % r["script"], lambda: _go(node), node is not None),
                ("log", "Abre el log de esta corrida", lambda: _open_log(r["work"]),
                 os.path.exists(os.path.join(r["work"], "run.log"))),
                ("cancelar", "Cancela solo este shot; la cola sigue con los demás", lambda: self._cancel(r),
                 r["estado"] in core.ACTIVE)):
            b = QtWidgets.QPushButton(label)
            b.setToolTip(tip)
            b.setEnabled(on)
            b.clicked.connect(lambda checked=False, fn=fn: fn())  # clicked manda un bool que fn no recibe
            lay.addWidget(b)
        return box

    def _cancel(self, r):
        if nuke.ask("¿Cancelar %s?" % r["shot"]):
            core.cancel_job(r["work"])
            ui._tick()  # el nodo de este script lo muestra al tiro
            self.refresh()


def _node_here(r):
    """El nodo del trabajo si está en el script abierto (mismo nombre y misma carpeta de trabajo); None si no."""
    try:
        node = nuke.toNode(r["node"] or "")
        return node if node is not None and os.path.normcase(ui._dirs(node)[1]) == os.path.normcase(r["work"]) else None
    except Exception:
        return None


def _go(node):
    for n in nuke.selectedNodes():
        n.setSelected(False)
    node.setSelected(True)
    nuke.zoom(1, [node.xpos() + node.screenWidth() / 2, node.ypos() + node.screenHeight() / 2])
    node.showControlPanel()


def _open_log(work):
    os.startfile(os.path.join(work, "run.log"))


# Nuke evalúa este texto en su propio espacio de nombres, donde corridorkey_nuke puede no estar importado
WIDGET = "__import__('corridorkey_nuke.panel', fromlist=['ColaPanel']).ColaPanel"
_PANEL = [None]


def register():
    """Windows > Custom > Cola de CorridorKey, y que Nuke lo reabra si quedó guardado en un workspace."""
    from nukescripts import panels
    panels.registerWidgetAsPanel(WIDGET, "Cola de CorridorKey", PANEL_ID)


def show():
    """CorridorKey > Ver cola: abre el panel junto a Properties; si ya estaba abierto, lo trae al frente."""
    from nukescripts import panels
    if _PANEL[0] is None:
        _PANEL[0] = panels.registerWidgetAsPanel(WIDGET, "Cola de CorridorKey", PANEL_ID, True)
    _PANEL[0].addToPane(nuke.getPaneFor("Properties.1"))
