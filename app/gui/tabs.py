"""Abas da janela principal."""
from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSpinBox, QStyle, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import autostart, classifier, db, google_photos
from ..config import CATEGORIES, SOURCES, TOKEN_PATH, Config, resource, wants_upload
from ..i18n import LANGUAGES, _, language
from .workers import ThumbJob

PAGE = 300
REPO = "https://github.com/sfidencio/fotofaxina/blob/master/"


def cat_label(key: str | None) -> str:
    return _(CATEGORIES[key]) if key in CATEGORIES else "—"


def guide_url() -> str:
    return REPO + ("docs/CONFIGURAR-GOOGLE.md" if language() == "pt" else "docs/GOOGLE-SETUP.md")


# ------------------------------------------------------------------ Início
class InicioTab(QWidget):
    choose_folder = Signal()
    analyze = Signal()
    upload = Signal()
    stop = Signal()
    retry_errors = Signal()
    forget_folder = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        mascot = QLabel()
        pix = QPixmap(str(resource("assets/mascote-128.png")))
        if not pix.isNull():
            mascot.setPixmap(pix.scaledToHeight(96, Qt.SmoothTransformation))
        title = QLabel(
            "<span style='font-size:20pt; font-weight:600'>FotoFaxina</span><br>"
            + _("Faxina nas fotos do HD: separa, remove duplicadas e envia para o Google Fotos.")
        )
        title.setWordWrap(True)
        header = QHBoxLayout()
        header.addWidget(mascot)
        header.addWidget(title, 1)

        self.source_lbl = QLabel(_("Nenhuma pasta selecionada. Plugue um HD ou escolha uma pasta."))
        self.source_lbl.setWordWrap(True)
        self.account_lbl = QLabel()

        self.btn_folder = QPushButton(_("Escolher pasta / HD…"))
        self.btn_analyze = QPushButton(_("1. Analisar"))
        self.btn_upload = QPushButton(_("2. Enviar para o Google Fotos"))
        self.btn_stop = QPushButton(_("Parar"))
        self.btn_retry = QPushButton(_("Tentar erros de novo"))
        self.btn_forget = QPushButton(_("Esquecer esta pasta…"))
        self.btn_forget.setToolTip(_("Remove do histórico do FotoFaxina os registros da pasta escolhida "
                                     "(não apaga nenhum arquivo)."))
        self.btn_forget.clicked.connect(lambda: self.forget_folder.emit())
        self.btn_stop.setEnabled(False)
        for b, sig in ((self.btn_folder, self.choose_folder), (self.btn_analyze, self.analyze),
                       (self.btn_upload, self.upload), (self.btn_stop, self.stop),
                       (self.btn_retry, self.retry_errors)):
            b.clicked.connect(lambda _checked=False, s=sig: s.emit())

        row = QHBoxLayout()
        for b in (self.btn_folder, self.btn_analyze, self.btn_upload, self.btn_stop):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(self.btn_forget)
        row.addWidget(self.btn_retry)

        self.stage_lbl = QLabel(_("Parado"))
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.summary_lbl = QLabel()
        self.summary_lbl.setTextFormat(Qt.RichText)
        self.summary_lbl.setWordWrap(True)
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setMaximumBlockCount(3000)

        lay = QVBoxLayout(self)
        lay.addLayout(header)
        lay.addWidget(self.source_lbl)
        lay.addWidget(self.account_lbl)
        lay.addLayout(row)
        lay.addWidget(self.stage_lbl)
        lay.addWidget(self.bar)
        lay.addWidget(self.summary_lbl)
        lay.addWidget(QLabel(_("Registro:")))
        lay.addWidget(self.logbox, 1)

    def set_busy(self, busy: bool):
        for b in (self.btn_folder, self.btn_analyze, self.btn_upload, self.btn_retry, self.btn_forget):
            b.setEnabled(not busy)
        self.btn_stop.setEnabled(busy)
        if not busy:
            self.stage_lbl.setText(_("Parado"))

    def set_progress(self, stage, done, total, msg):
        self.stage_lbl.setText(f"{stage}… {msg}" if msg else f"{stage}…")
        if total <= 0:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, total)
            self.bar.setValue(done)

    def log(self, text: str):
        self.logbox.appendPlainText(f"[{datetime.now():%H:%M:%S}] {text}")

    def show_summary(self, s: dict):
        cats = " · ".join(
            f"{cat_label(k)}: <b>{v}</b>" for k, v in sorted(s.get("por_categoria", {}).items())
        )
        self.summary_lbl.setText(
            _("Arquivos: <b>{total}</b> · Duplicados: <b>{dup}</b> · A enviar: <b>{todo}</b> · "
              "Já enviados: <b>{done}</b> · Erros: <b>{err}</b>").format(
                total=s["total"], dup=s["duplicadas"], todo=s["a_enviar"], done=s["enviadas"], err=s["erros"])
            + f"<br>{cats}"
        )


# ------------------------------------------------------------------ Revisão
class RevisaoTab(QWidget):
    changed = Signal()

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.pool = QThreadPool.globalInstance()
        self.items_by_id: dict[int, QListWidgetItem] = {}
        self.rows: list = []
        self.shown = 0
        self._thumb_jobs: list[ThumbJob] = []
        self.originals: dict[int, tuple[str, bool]] = {}

        self.cat_combo = QComboBox()
        self.cat_combo.addItem(_("Todas as categorias"), None)
        for k in CATEGORIES:
            self.cat_combo.addItem(cat_label(k), k)
        self.cat_combo.addItem(_("Duplicados"), "__dup")
        self.sit_combo = QComboBox()
        for label, key in ((_("Vão para o Google"), "upload"), (_("Não vão"), "skip"),
                           (_("Baixa confiança"), "low"), (_("Já enviadas"), "done"),
                           (_("Com erro"), "error"), (_("Tudo"), "all")):
            self.sit_combo.addItem(label, key)
        self.cat_combo.currentIndexChanged.connect(self.reload)
        self.sit_combo.currentIndexChanged.connect(self.reload)
        self.count_lbl = QLabel()

        top = QHBoxLayout()
        top.addWidget(QLabel(_("Categoria:")))
        top.addWidget(self.cat_combo)
        top.addWidget(QLabel(_("Situação:")))
        top.addWidget(self.sit_combo)
        top.addStretch()
        top.addWidget(self.count_lbl)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(160, 160))
        self.list.setGridSize(QSize(180, 215))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(self._open_file)

        self.btn_more = QPushButton(_("Carregar mais"))
        self.btn_more.clicked.connect(self._show_more)
        btn_send = QPushButton(_("Enviar selecionadas"))
        btn_skip = QPushButton(_("Não enviar"))
        btn_auto = QPushButton(_("Voltar ao automático"))
        self.move_combo = QComboBox()
        for k in CATEGORIES:
            self.move_combo.addItem(cat_label(k), k)
        btn_move = QPushButton(_("Mudar categoria"))
        btn_notdup = QPushButton(_("Não é duplicata"))
        btn_notdup.setToolTip(_("Para fotos parecidas, mas diferentes (sequência, rajada): passam a ser "
                                "enviadas e não são mais tratadas como cópia."))
        btn_notdup.clicked.connect(self._not_duplicate)
        btn_forget = QPushButton(_("Esquecer selecionadas…"))
        btn_forget.setToolTip(_("Remove os itens do histórico do FotoFaxina (não apaga nenhum arquivo)."))
        btn_forget.clicked.connect(self._forget_selected)
        self.btn_forget = btn_forget
        btn_send.clicked.connect(lambda: self._set_decision("upload"))
        btn_skip.clicked.connect(lambda: self._set_decision("skip"))
        btn_auto.clicked.connect(lambda: self._set_decision(None))
        btn_move.clicked.connect(self._move_category)

        bottom = QHBoxLayout()
        for w in (btn_send, btn_skip, btn_auto, QLabel(" | "), self.move_combo, btn_move,
                  QLabel(" | "), btn_notdup):
            bottom.addWidget(w)
        bottom.addStretch()
        bottom.addWidget(btn_forget)
        bottom.addWidget(self.btn_more)

        hint = QLabel(_("Dica: Ctrl/Shift para selecionar várias. Duplo clique abre o arquivo."))
        hint.setStyleSheet("color: gray")
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.list, 1)
        lay.addLayout(bottom)
        lay.addWidget(hint)

        self.video_icon = self.style().standardIcon(QStyle.SP_MediaPlay)
        self.file_icon = self.style().standardIcon(QStyle.SP_FileIcon)

    def set_busy(self, busy: bool):
        self.btn_forget.setEnabled(not busy)
        self.btn_forget.setToolTip(_("Aguarde a tarefa atual terminar.") if busy else
                                   _("Remove os itens do histórico do FotoFaxina (não apaga nenhum arquivo)."))

    # -- dados
    def _matches(self, r) -> bool:
        sit = self.sit_combo.currentData()
        if sit == "all":
            return True
        if sit == "done":
            return bool(r["media_item_id"])
        if sit == "error":
            return r["status"] == "error"
        if r["media_item_id"] or r["status"] == "scanned":
            return False
        if sit == "low":
            return (r["confidence"] or 0) < self.cfg.ai_min_confidence and r["category_by"] != "manual"
        will = wants_upload(r, self.cfg)
        return will if sit == "upload" else not will

    def reload(self):
        for j in self._thumb_jobs:
            j.cancelled = True
        self._thumb_jobs = [j for j in self._thumb_jobs if not j.done]
        self.list.clear()
        self.items_by_id.clear()
        cat = self.cat_combo.currentData()
        conn = db.connect()
        if cat == "__dup":
            rows = conn.execute(
                "SELECT * FROM photos WHERE duplicate_of IS NOT NULL ORDER BY taken_at"
            ).fetchall()
        elif cat:
            rows = conn.execute(
                "SELECT * FROM photos WHERE category=? AND duplicate_of IS NULL ORDER BY taken_at", (cat,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM photos WHERE duplicate_of IS NULL ORDER BY taken_at"
            ).fetchall()
        self.originals = {}
        conn.close()
        self.rows = rows if cat == "__dup" else [r for r in rows if self._matches(r)]
        self.shown = 0
        self._show_more()

    def _label(self, r) -> str:
        if r["media_item_id"]:
            mark = "✓ "
        elif r["duplicate_of"] is not None:
            mark = "≡ "
        elif wants_upload(r, self.cfg):
            mark = "↑ "
        else:
            mark = "✕ "
        conf = f" {r['confidence']:.0%}" if r["confidence"] is not None and r["category_by"] == "ia" else ""
        date = (r["taken_at"] or "")[:10]
        return f"{mark}{cat_label(r['category'])}{conf}\n{date}"

    def _show_more(self):
        chunk = self.rows[self.shown:self.shown + PAGE]
        # originais só das duplicatas desta página (em vez de carregar o banco inteiro)
        wanted = [r["duplicate_of"] for r in chunk
                  if r["duplicate_of"] is not None and r["duplicate_of"] not in self.originals]
        if wanted:
            conn = db.connect()
            for i in range(0, len(wanted), 500):
                part = wanted[i:i + 500]
                for o in conn.execute(f"SELECT id, path, media_item_id FROM photos WHERE id IN "
                                      f"({','.join('?' * len(part))})", part):
                    self.originals[o["id"]] = (o["path"], bool(o["media_item_id"]))
            conn.close()
        thumbs = []
        for r in chunk:
            it = QListWidgetItem(self.video_icon if r["is_video"] else self.file_icon, self._label(r))
            it.setData(Qt.UserRole, r["id"])
            source = _(SOURCES[r["source"]]) if r["source"] in SOURCES else (r["source"] or "")
            tip = [r["path"], _("Origem: {origem}").format(origem=source),
                   _("Data: {data} ({fonte})").format(data=r["taken_at"], fonte=r["date_source"])]
            if r["camera"]:
                tip.append(_("Câmera: {camera}").format(camera=r["camera"]))
            if r["error"]:
                tip.append(_("Erro: {erro}").format(erro=r["error"]))
            if r["duplicate_of"] is not None and r["duplicate_of"] in self.originals:
                orig, sent = self.originals[r["duplicate_of"]]
                tip.append(_("Duplicata de: {arquivo}").format(arquivo=orig)
                           + (" " + _("(já está no Google Fotos)") if sent else ""))
            it.setToolTip("\n".join(tip))
            self.list.addItem(it)
            self.items_by_id[r["id"]] = it
            if not r["is_video"]:
                thumbs.append((r["id"], r["path"]))
        self.shown += len(chunk)
        self.count_lbl.setText(_("{n} de {total}").format(n=self.shown, total=len(self.rows)))
        self.btn_more.setEnabled(self.shown < len(self.rows))
        if thumbs:
            job = ThumbJob(thumbs)
            job.signals.ready.connect(self._set_thumb)
            self._thumb_jobs.append(job)  # mantém a referência enquanto a thread roda
            self.pool.start(job)

    def _set_thumb(self, pid: int, path: str):
        it = self.items_by_id.get(pid)
        if it is not None:
            it.setIcon(QIcon(path))

    # -- ações
    def _selected_ids(self) -> list[int]:
        return [it.data(Qt.UserRole) for it in self.list.selectedItems()]

    def _set_decision(self, decision):
        ids = self._selected_ids()
        if not ids:
            return
        conn = db.connect()
        conn.executemany("UPDATE photos SET decision=? WHERE id=? AND media_item_id IS NULL",
                         [(decision, i) for i in ids])
        conn.commit()
        conn.close()
        self.reload()
        self.changed.emit()

    def _move_category(self):
        ids = self._selected_ids()
        if not ids:
            return
        cat = self.move_combo.currentData()
        conn = db.connect()
        conn.executemany(
            "UPDATE photos SET category=?, confidence=1.0, category_by='manual' WHERE id=? AND media_item_id IS NULL",
            [(cat, i) for i in ids],
        )
        conn.commit()
        conn.close()
        self.reload()
        self.changed.emit()

    def _not_duplicate(self):
        ids = self._selected_ids()
        if not ids:
            return
        conn = db.connect()
        n = db.mark_not_duplicate(conn, ids)
        conn.close()
        if n:
            QMessageBox.information(self, _("Não é duplicata"), _(
                "{n} item(ns) não serão mais tratados como cópia. Eles são classificados na próxima "
                "análise ou no próximo envio.").format(n=n))
        self.reload()
        self.changed.emit()

    def _forget_selected(self):
        ids = self._selected_ids()
        if not ids:
            return
        text = _("Esquecer {n} item(ns)?").format(n=len(ids)) + "\n\n" + _("Os arquivos no seu computador NÃO serão apagados, nem nada no Google Fotos. "
              "O FotoFaxina só esquece o que sabe sobre eles: na próxima análise serão tratados como "
              "novos, e o que já tinha sido enviado poderá ser enviado de novo (ficando repetido no "
              "Google Fotos).")
        if QMessageBox.question(self, _("Esquecer"), text) != QMessageBox.Yes:
            return
        conn = db.connect()
        db.forget(conn, ids)
        conn.close()
        self.reload()
        self.changed.emit()

    def _open_file(self, it: QListWidgetItem):
        conn = db.connect()
        r = conn.execute("SELECT path FROM photos WHERE id=?", (it.data(Qt.UserRole),)).fetchone()
        conn.close()
        if r and os.path.exists(r["path"]):
            QDesktopServices.openUrl(QUrl.fromLocalFile(r["path"]))


# ------------------------------------------------------------------ Álbuns
class AlbunsTab(QWidget):
    regroup = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [_("Título (clique duplo para renomear)"), _("Período"), _("Itens"), _("No Google")]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemChanged.connect(self._renamed)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.urls: dict[str, str | None] = {}

        self.btn_share = QPushButton(_("Abrir no Google Fotos para compartilhar"))
        self.btn_share.setEnabled(False)
        self.btn_share.clicked.connect(self._open_album)
        btn = QPushButton(_("Reagrupar (após mudar configurações)"))
        btn.clicked.connect(lambda: self.regroup.emit())
        share_hint = QLabel(_(
            "Para compartilhar: selecione um álbum já enviado → “Abrir no Google Fotos para "
            "compartilhar” → no navegador, clique em <b>Compartilhar</b> e digite os e-mails. "
            "Quem você adicionar recebe as fotos novas que forem para esse álbum depois."
        ))
        share_hint.setWordWrap(True)
        hint = QLabel(_("Os álbuns são criados no Google Fotos só no envio. Renomeie à vontade antes — "
                        "ex.: “Evento 24 a 26/12/2023” → “Natal 2023”."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")
        lay = QVBoxLayout(self)
        lay.addWidget(hint)
        lay.addWidget(self.table, 1)
        lay.addWidget(share_hint)
        row = QHBoxLayout()
        row.addWidget(self.btn_share)
        row.addStretch()
        row.addWidget(btn)
        lay.addLayout(row)

    def _selected_key(self) -> str | None:
        items = self.table.selectedItems()
        if not items:
            return None
        return self.table.item(items[0].row(), 0).data(Qt.UserRole)

    def _selection_changed(self):
        key = self._selected_key()
        url = self.urls.get(key) if key else None
        self.btn_share.setEnabled(bool(url))
        self.btn_share.setToolTip("" if url else _("Este álbum ainda não foi enviado ao Google Fotos."))

    def _open_album(self):
        url = self.urls.get(self._selected_key() or "")
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def reload(self):
        conn = db.connect()
        rows = conn.execute(
            "SELECT a.*, COUNT(p.id) AS n, SUM(CASE WHEN p.media_item_id IS NOT NULL THEN 1 ELSE 0 END) AS up "
            "FROM albums a LEFT JOIN photos p ON p.album_key=a.key GROUP BY a.key ORDER BY a.start DESC"
        ).fetchall()
        conn.close()
        self.urls = {r["key"]: db.album_url(r) for r in rows}
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            t = QTableWidgetItem(r["title"])
            t.setData(Qt.UserRole, r["key"])
            self.table.setItem(i, 0, t)
            s, e = (r["start"] or "")[:10], (r["end"] or "")[:10]
            period = s if s == e else f"{s} → {e}"
            for c, val in ((1, period), (2, f"{r['up'] or 0}/{r['n']}"),
                           (3, _("Sim") if r["google_id"] else _("Ainda não"))):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(i, c, item)
        self.table.blockSignals(False)
        self._selection_changed()

    def _renamed(self, item: QTableWidgetItem):
        if item.column() != 0:
            return
        title = item.text().strip()
        if not title:
            return
        conn = db.connect()
        conn.execute(
            "UPDATE albums SET title=?, custom_title=1, "
            "pending_rename=CASE WHEN google_id IS NULL THEN 0 ELSE 1 END WHERE key=?",
            (title, item.data(Qt.UserRole)),
        )
        conn.commit()
        conn.close()


# ------------------------------------------------------------------ Configurações
class ConfigTab(QWidget):
    saved = Signal()
    connect_google = Signal()
    download_ai = Signal()

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg

        cats = QGroupBox(_("O que vai para o Google Fotos"))
        cl = QVBoxLayout(cats)
        self.cat_checks: dict[str, QCheckBox] = {}
        for k in CATEGORIES:
            cb = QCheckBox(cat_label(k))
            self.cat_checks[k] = cb
            cl.addWidget(cb)
        self.wa_check = QCheckBox(_("Incluir fotos pessoais recebidas pelo WhatsApp"))
        cl.addWidget(self.wa_check)
        cl.addStretch()

        ai = QGroupBox(_("Inteligência artificial (embutida, funciona sem internet)"))
        il = QFormLayout(ai)
        self.ai_check = QCheckBox(_("Usar IA para separar memes, prints e documentos"))
        self.ai_cam_check = QCheckBox(_("Analisar também as fotos da câmera (mais lento)"))
        self.ai_check.toggled.connect(lambda on: self.ai_cam_check.setEnabled(on))
        self.ai_status = QLabel()
        self.ai_status.setWordWrap(True)
        self.ai_status.setStyleSheet("color: gray")
        self.conf_spin = QDoubleSpinBox()
        self.conf_spin.setRange(0.0, 1.0)
        self.conf_spin.setSingleStep(0.05)
        il.addRow(self.ai_check)
        il.addRow(self.ai_cam_check)
        il.addRow(_("Confiança mínima da IA:"), self.conf_spin)
        il.addRow(self.ai_status)
        self.btn_ai = QPushButton(_("Baixar modelo de IA (~96 MB)"))
        self.btn_ai.clicked.connect(lambda: self.download_ai.emit())
        il.addRow(self.btn_ai)

        proc = QGroupBox(_("Álbuns"))
        fl = QFormLayout(proc)
        self.mode_combo = QComboBox()
        for label, key in ((_("Por evento (fotos próximas no tempo)"), "evento"),
                           (_("Por mês"), "mes"), (_("Por ano"), "ano")):
            self.mode_combo.addItem(label, key)
        self.year_title = QLineEdit()
        self.year_title.setPlaceholderText(_("Fotos {ano}"))
        self.year_title.setToolTip(_("Use {ano} onde o ano deve aparecer. Ex.: Fotos {ano}"))
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.gap_spin = QDoubleSpinBox()
        self.gap_spin.setRange(1, 720)
        self.gap_spin.setSuffix(_(" horas"))
        self.min_spin = QSpinBox()
        self.min_spin.setRange(1, 1000)
        self.min_spin.setSuffix(_(" fotos"))
        fl.addRow(_("Organizar álbuns:"), self.mode_combo)
        fl.addRow(_("Nome do álbum anual:"), self.year_title)
        fl.addRow(_("Novo evento após um intervalo de:"), self.gap_spin)
        fl.addRow(_("Tamanho mínimo de um evento:"), self.min_spin)

        auto = QGroupBox(_("Automação e idioma"))
        al = QFormLayout(auto)
        self.scan_check = QCheckBox(_("Analisar automaticamente quando um HD for plugado"))
        self.upload_check = QCheckBox(_("Enviar automaticamente após a análise (sem revisar)"))
        self.startup_check = QCheckBox(_("Iniciar junto com o Windows (minimizado, esperando o HD)"))
        self.startup_check.setVisible(autostart.supported())
        self.lang_combo = QComboBox()
        for key, label in LANGUAGES.items():
            self.lang_combo.addItem(_(label), key)
        al.addRow(self.scan_check)
        al.addRow(self.upload_check)
        al.addRow(self.startup_check)
        al.addRow(_("Idioma / Language:"), self.lang_combo)

        acc = QGroupBox(_("Conta Google"))
        gl = QVBoxLayout(acc)
        self.acc_lbl = QLabel()
        self.acc_lbl.setWordWrap(True)
        self.acc_lbl.setOpenExternalLinks(True)
        b1 = QPushButton(_("Selecionar client_secret.json…"))
        # no instalador com credencial embutida o usuário final não precisa disso
        b1.setVisible(google_photos.bundled_secret_path() is None)
        b2 = QPushButton(_("Conectar conta Google"))
        b3 = QPushButton(_("Desconectar"))
        b1.clicked.connect(self._pick_secret)
        b2.clicked.connect(lambda: self.connect_google.emit())
        b3.clicked.connect(self._disconnect)
        self._busy_buttons = [b1, b2, b3]
        row = QHBoxLayout()
        for b in (b1, b2, b3):
            row.addWidget(b)
        row.addStretch()
        gl.addWidget(self.acc_lbl)
        gl.addLayout(row)

        hist = QGroupBox(_("Histórico do FotoFaxina"))
        hl = QHBoxLayout(hist)
        hist_lbl = QLabel(_("O FotoFaxina guarda o que já analisou e enviou para não repetir. "
                            "Limpar faz ele começar do zero (os arquivos não são apagados)."))
        hist_lbl.setWordWrap(True)
        btn_clear = QPushButton(_("Limpar todo o histórico…"))
        btn_clear.clicked.connect(self._forget_all)
        self._busy_buttons.append(btn_clear)
        hl.addWidget(hist_lbl, 1)
        hl.addWidget(btn_clear)

        save = QPushButton(_("Salvar configurações"))
        save.clicked.connect(self._save)

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(cats)
        mid = QVBoxLayout()
        mid.addWidget(ai)
        mid.addWidget(proc)
        top.addLayout(mid, 1)
        top.addWidget(auto, 1)
        lay.addLayout(top)
        lay.addWidget(acc)
        lay.addWidget(hist)
        lay.addStretch()
        lay.addWidget(save, 0, Qt.AlignRight)
        self.load()

    def set_busy(self, busy: bool):
        for b in self._busy_buttons:
            b.setEnabled(not busy)

    def load(self):
        c = self.cfg
        for k, cb in self.cat_checks.items():
            cb.setChecked(k in c.upload_categories)
        self.wa_check.setChecked(c.include_whatsapp)
        self.ai_check.setChecked(c.use_ai)
        self.ai_cam_check.setChecked(c.ai_on_camera)
        self.ai_cam_check.setEnabled(c.use_ai)
        self.conf_spin.setValue(c.ai_min_confidence)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(c.album_mode)))
        self.year_title.setText(c.year_album_title)
        self._mode_changed()
        self.gap_spin.setValue(c.event_gap_hours)
        self.min_spin.setValue(c.min_event_size)
        self.scan_check.setChecked(c.auto_scan_on_drive)
        self.upload_check.setChecked(c.auto_upload)
        self.startup_check.setChecked(autostart.is_enabled())
        self.lang_combo.setCurrentIndex(max(0, self.lang_combo.findData(c.language)))
        self.refresh_ai()
        self.refresh_account()

    def refresh_ai(self):
        has_model = classifier.model_dir() is not None
        has_runtime = classifier.runtime_installed()
        if has_model and has_runtime:
            text = _("IA pronta: modelo leve embutido, roda no processador, sem placa de vídeo.")
        elif not has_runtime:
            # acontece ao rodar pelo código sem reinstalar as dependências depois de um git pull
            text = _("Falta o componente que executa a IA. No terminal, rode "
                     "<b>pip install -r requirements.txt</b> e abra o FotoFaxina de novo.")
        else:
            text = _("Modelo de IA não encontrado nesta instalação — usando só as regras. "
                     "Clique abaixo para baixar.")
        self.ai_status.setText(text)
        self.btn_ai.setVisible(not has_model)

    def _mode_changed(self):
        mode = self.mode_combo.currentData()
        self.year_title.setEnabled(mode == "ano")
        self.gap_spin.setEnabled(mode == "evento")
        self.min_spin.setEnabled(mode == "evento")

    def refresh_account(self):
        if TOKEN_PATH.exists():
            self.acc_lbl.setText(_("✔ Conta conectada."))
        elif google_photos.has_client_secret():
            self.acc_lbl.setText(_("Falta só clicar em “Conectar conta Google” e autorizar no navegador."))
        else:
            self.acc_lbl.setText(
                _("Falta a credencial do Google (uma vez só, ~10 min).")
                + f' <a href="{guide_url()}">' + _("Veja o passo a passo") + "</a>."
            )

    def _forget_all(self):
        text = _("Limpar TODO o histórico (todas as pastas e álbuns)?") + "\n\n" + _("Os arquivos no seu computador NÃO serão apagados, nem nada no Google Fotos. "
              "O FotoFaxina só esquece o que sabe sobre eles: na próxima análise serão tratados como "
              "novos, e o que já tinha sido enviado poderá ser enviado de novo (ficando repetido no "
              "Google Fotos).")
        if QMessageBox.question(self, _("Limpar histórico"), text) != QMessageBox.Yes:
            return
        conn = db.connect()
        n = db.forget_all(conn)
        conn.close()
        QMessageBox.information(self, _("Limpar histórico"),
                                _("{n} registros removidos. Seus arquivos continuam onde estavam.").format(n=n))
        self.saved.emit()

    def _pick_secret(self):
        path, _filter = QFileDialog.getOpenFileName(self, "client_secret.json", "", "JSON (*.json)")
        if path:
            google_photos.install_client_secret(path)
            self.refresh_account()

    def _disconnect(self):
        google_photos.disconnect()
        self.refresh_account()

    def _save(self):
        c = self.cfg
        old_lang = c.language
        c.upload_categories = [k for k, cb in self.cat_checks.items() if cb.isChecked()]
        c.include_whatsapp = self.wa_check.isChecked()
        c.use_ai = self.ai_check.isChecked()
        c.ai_on_camera = self.ai_cam_check.isChecked()
        c.ai_min_confidence = self.conf_spin.value()
        c.album_mode = self.mode_combo.currentData()
        title = self.year_title.text().strip()
        if title and "{ano}" not in title and "{year}" not in title:
            title += " {ano}"
        c.year_album_title = title
        c.event_gap_hours = self.gap_spin.value()
        c.min_event_size = self.min_spin.value()
        c.auto_scan_on_drive = self.scan_check.isChecked()
        c.auto_upload = self.upload_check.isChecked()
        c.language = self.lang_combo.currentData()
        if autostart.supported():
            try:
                autostart.set_enabled(self.startup_check.isChecked())
            except OSError as e:
                QMessageBox.warning(self, _("Configurações"),
                                    _("Não consegui alterar a inicialização: {erro}").format(erro=e))
        c.save()
        msg = _("Salvo. Use “Reagrupar” na aba Álbuns para aplicar.")
        if c.language != old_lang:
            msg += "\n\n" + _("O novo idioma vale a partir da próxima vez que o FotoFaxina for aberto.")
        QMessageBox.information(self, _("Configurações"), msg)
        self.saved.emit()
