"""Aba "Lixeira do HD": lê a lixeira (do HD externo e da pasta pessoal) e restaura ao lugar original.
Só lê e restaura: não existe aqui nenhum botão que apague ou esvazie a lixeira."""
from __future__ import annotations

import os

from PIL import Image, ImageOps
from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QObject, QRunnable, QSortFilterProxyModel, Qt,
                            QThreadPool, Signal, Slot)
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QProgressDialog, QPushButton, QTableView, QVBoxLayout,
                               QWidget)

from .. import trash
from ..i18n import _
from .icons import set_icon
from .tabs import reveal_in_folder


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


class _Signals(QObject):
    progress = Signal(int, int)
    done = Signal(object)
    failed = Signal(str)


class LoadJob(QRunnable):
    def __init__(self, tr: dict):
        super().__init__()
        self.setAutoDelete(False)
        self.tr, self.signals, self.cancelled = tr, _Signals(), False

    @Slot()
    def run(self):
        try:
            items = trash.list_items(self.tr, progress=self.signals.progress.emit, stop=lambda: self.cancelled)
            self.signals.done.emit(items)
        except Exception as e:
            self.signals.failed.emit(str(e))


class ItemsModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.items: list[dict] = []

    def set_items(self, items: list[dict]):
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()):
        return 4

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return (_("Arquivo"), _("Pasta original"), _("Excluído em"), _("Tamanho"))[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        it, c = self.items[index.row()], index.column()
        raw = (it["name"].lower(), os.path.dirname(it["orig"]).lower(), it["deleted"], it["size"])[c]
        if role == Qt.UserRole:
            return raw
        if role == Qt.DisplayRole:
            return (os.path.basename(it["orig"]), os.path.dirname(it["orig"]), it["deleted"].replace("T", " "),
                    human(it["size"]) if not it["is_dir"] else _("(pasta)"))[c]
        if role == Qt.ToolTipRole:
            return it["orig"]
        return None


class Proxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.text, self.date, self.only_media = "", "", False
        self.setSortRole(Qt.UserRole)

    def set_filters(self, text: str, date: str, only_media: bool):
        self.text, self.date, self.only_media = text.lower().strip(), date, only_media
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        it = self.sourceModel().items[row]
        if self.only_media and not it["media"]:
            return False
        if self.date and not it["deleted"].startswith(self.date):
            return False
        return not self.text or self.text in it["orig"].lower()


class LixeiraTab(QWidget):
    restored = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool.globalInstance()
        self.trashes: list[dict] = []
        self.loaded = False
        self.job: LoadJob | None = None

        info = QLabel(_("Aqui você vê o que está na lixeira do HD e pode restaurar para o lugar original. "
                        "Esta aba só lê e restaura: ela nunca apaga nada da lixeira."))
        info.setWordWrap(True)
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._load)
        self.btn_reload = QPushButton(_("Recarregar"))
        self.btn_reload.clicked.connect(self.reload)
        top = QHBoxLayout()
        top.addWidget(QLabel(_("Lixeira:")))
        top.addWidget(self.combo, 1)
        top.addWidget(self.btn_reload)

        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Filtrar por nome ou pasta…"))
        self.date = QComboBox()
        self.only_media = QCheckBox(_("Só fotos e vídeos"))
        self.only_media.setChecked(True)
        for w in (self.search,):
            w.textChanged.connect(self._filters)
        self.date.currentIndexChanged.connect(self._filters)
        self.only_media.toggled.connect(self._filters)
        flt = QHBoxLayout()
        flt.addWidget(self.search, 1)
        flt.addWidget(QLabel(_("Excluído em:")))
        flt.addWidget(self.date)
        flt.addWidget(self.only_media)

        self.model = ItemsModel()
        self.proxy = Proxy()
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 260)
        self.table.setColumnWidth(1, 420)
        self.table.setColumnWidth(2, 150)
        self.table.selectionModel().selectionChanged.connect(self._selection)

        self.preview = QLabel(_("Selecione um item para ver a prévia."))
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setFixedWidth(280)
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet("color: gray")
        body = QHBoxLayout()
        body.addWidget(self.table, 1)
        body.addWidget(self.preview)

        self.count_lbl = QLabel()
        self.btn_restore = QPushButton(_("Restaurar selecionados"))
        self.btn_restore.clicked.connect(self._restore_selected)
        self.btn_restore_all = QPushButton(_("Restaurar todos os filtrados…"))
        self.btn_restore_all.clicked.connect(self._restore_filtered)
        self.btn_show = QPushButton(_("Mostrar pasta original"))
        self.btn_show.clicked.connect(self._show_folder)
        for b, name, tone in ((self.btn_restore, "retry", "accent"), (self.btn_restore_all, "retry", None),
                              (self.btn_show, "folder", None)):
            set_icon(b, name, tone)
        bottom = QHBoxLayout()
        bottom.addWidget(self.count_lbl)
        bottom.addStretch()
        for b in (self.btn_show, self.btn_restore_all, self.btn_restore):
            bottom.addWidget(b)

        self.status = QLabel()
        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addLayout(top)
        lay.addLayout(flt)
        lay.addLayout(body, 1)
        lay.addWidget(self.status)
        lay.addLayout(bottom)
        self._buttons = [self.btn_restore, self.btn_restore_all, self.btn_show, self.btn_reload]
        if not trash.supported():
            info.setText(_("A leitura da lixeira está disponível no Linux (padrão FreeDesktop). No Windows e "
                           "no macOS, use a Lixeira do sistema para restaurar."))
            for w in (self.combo, self.search, self.date, self.only_media, self.table, *self._buttons):
                w.setEnabled(False)

    # -- carga
    def ensure_loaded(self):
        if not self.loaded and trash.supported():
            self.reload()

    def reload(self):
        self.loaded = True
        self.trashes = trash.find_trashes()
        self.combo.blockSignals(True)
        self.combo.clear()
        for tr in self.trashes:
            n = len(os.listdir(tr["dir"] / "info")) if (tr["dir"] / "info").is_dir() else 0
            self.combo.addItem(f"{_('Pasta pessoal') if tr['topdir'] is None else tr['label']} — "
                               f"{n} {_('itens')}  ({tr['dir']})", tr)
        self.combo.blockSignals(False)
        if not self.trashes:
            self.model.set_items([])
            self.status.setText(_("Nenhuma lixeira encontrada (HD plugado?)."))
            return
        self._load()

    def _current(self) -> dict | None:
        return self.combo.currentData()

    def _load(self):
        tr = self._current()
        if tr is None:
            return
        if self.job is not None:
            self.job.cancelled = True
        self._set_busy(True)
        self.status.setText(_("Lendo a lixeira…"))
        job = LoadJob(tr)
        job.signals.progress.connect(lambda d, t: self.status.setText(_("Lendo a lixeira… {d}/{t}").format(d=d, t=t)))
        job.signals.done.connect(lambda items, j=job: self._loaded(j, items))
        job.signals.failed.connect(lambda msg: (self._set_busy(False), self.status.setText(msg)))
        self.job = job
        self.pool.start(job)

    def _loaded(self, job, items):
        if job is not self.job:
            return
        self.job = None
        items.sort(key=lambda it: it["deleted"], reverse=True)
        self.model.set_items(items)
        dates = sorted({it["deleted"][:10] for it in items if it["deleted"]}, reverse=True)
        self.date.blockSignals(True)
        self.date.clear()
        self.date.addItem(_("Todas as datas"), "")
        for d in dates:
            self.date.addItem(d, d)
        self.date.blockSignals(False)
        self._filters()
        self._set_busy(False)
        self.status.setText("")

    def _set_busy(self, busy: bool):
        for b in self._buttons:
            b.setEnabled(not busy)

    def _filters(self):
        self.proxy.set_filters(self.search.text(), self.date.currentData() or "", self.only_media.isChecked())
        self.count_lbl.setText(_("{n} de {total} itens").format(n=self.proxy.rowCount(), total=len(self.model.items)))

    # -- seleção / prévia
    def _selected(self) -> list[dict]:
        rows = {self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()}
        return [self.model.items[r] for r in sorted(rows)]

    def _selection(self, *_args):
        sel = self._selected()
        if len(sel) != 1:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(_("{n} item(ns) selecionado(s).").format(n=len(sel)) if sel
                                 else _("Selecione um item para ver a prévia."))
            return
        it, tr = sel[0], self._current()
        path = str(tr["dir"] / "files" / it["name"])
        self.preview.setText(it["orig"])
        if it["is_dir"] or not it["media"] or os.path.splitext(it["name"])[1].lower() in (".mp4", ".mov", ".3gp", ".avi", ".mkv", ".m4v"):
            return
        try:
            with Image.open(path) as im:
                im.draft("RGB", (560, 560))
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail((270, 270))
                qimg = QImage(im.tobytes(), im.width, im.height, im.width * 3, QImage.Format_RGB888).copy()
            self.preview.setPixmap(QPixmap.fromImage(qimg))
        except Exception:
            self.preview.setText(it["orig"] + "\n\n" + _("(sem prévia)"))

    def _show_folder(self):
        sel = self._selected()
        if sel and not reveal_in_folder(sel[0]["orig"]):
            QMessageBox.warning(self, _("Arquivo não encontrado"),
                                _("Não encontrei {arquivo}. O HD está plugado?").format(arquivo=os.path.dirname(sel[0]["orig"])))

    # -- restaurar
    def _restore_selected(self):
        self._restore(self._selected())

    def _restore_filtered(self):
        items = [self.model.items[self.proxy.mapToSource(self.proxy.index(r, 0)).row()]
                 for r in range(self.proxy.rowCount())]
        self._restore(items)

    def _restore(self, items: list[dict]):
        tr = self._current()
        if not items or tr is None:
            return
        mb = sum(i["size"] for i in items) / 1048576
        if QMessageBox.question(self, _("Restaurar"), _(
                "Restaurar {n} item(ns) ({mb:.1f} MB) para o lugar original?\n\nArquivos que já existirem no "
                "destino não são sobrescritos.").format(n=len(items), mb=mb)) != QMessageBox.Yes:
            return
        dlg = QProgressDialog(_("Restaurando…"), _("Parar"), 0, len(items), self)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)

        def progress(done, total, name):
            dlg.setValue(done - 1)
            dlg.setLabelText(name)
            QApplication.processEvents()

        res = trash.restore(tr, items, progress, stop=dlg.wasCanceled)
        dlg.close()
        done = {id(i) for i in res["restaurados"]}
        self.model.set_items([i for i in self.model.items if id(i) not in done])
        self._filters()
        msg = _("{n} item(ns) restaurados.").format(n=len(res["restaurados"]))
        if res["existentes"]:
            msg += "\n" + _("{n} já existiam no destino (não foram sobrescritos).").format(n=len(res["existentes"]))
        if res["faltando"]:
            msg += "\n" + _("{n} não estão mais na lixeira.").format(n=len(res["faltando"]))
        if res["falhas"]:
            msg += "\n" + _("{n} falharam, por exemplo: {ex}").format(
                n=len(res["falhas"]), ex=f"{res['falhas'][0][0]} ({res['falhas'][0][1]})")
        if res["parado"]:
            msg += "\n" + _("Parado: o restante continua na lixeira.")
        if res["restaurados"]:
            msg += "\n\n" + _("Para o FotoFaxina considerar esses arquivos, clique em Analisar na aba Início.")
            self.restored.emit()
        QMessageBox.information(self, _("Restaurar"), msg)
