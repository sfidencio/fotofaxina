"""Abas da janela principal."""
from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSpinBox, QStyle, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import classifier, db, google_photos
from ..config import CATEGORIES, SOURCES, TOKEN_PATH, Config, wants_upload
from .workers import ThumbJob

PAGE = 300


# ------------------------------------------------------------------ Início
class InicioTab(QWidget):
    choose_folder = Signal()
    analyze = Signal()
    upload = Signal()
    stop = Signal()
    retry_errors = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source_lbl = QLabel("Nenhuma pasta selecionada. Plugue um HD ou escolha uma pasta.")
        self.source_lbl.setWordWrap(True)
        self.account_lbl = QLabel()

        self.btn_folder = QPushButton("Escolher pasta / HD…")
        self.btn_analyze = QPushButton("1. Analisar")
        self.btn_upload = QPushButton("2. Enviar para o Google Fotos")
        self.btn_stop = QPushButton("Parar")
        self.btn_retry = QPushButton("Tentar erros de novo")
        self.btn_stop.setEnabled(False)
        for b, sig in ((self.btn_folder, self.choose_folder), (self.btn_analyze, self.analyze),
                       (self.btn_upload, self.upload), (self.btn_stop, self.stop),
                       (self.btn_retry, self.retry_errors)):
            b.clicked.connect(lambda _=False, s=sig: s.emit())

        row = QHBoxLayout()
        for b in (self.btn_folder, self.btn_analyze, self.btn_upload, self.btn_stop):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(self.btn_retry)

        self.stage_lbl = QLabel("Parado")
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
        lay.addWidget(self.source_lbl)
        lay.addWidget(self.account_lbl)
        lay.addLayout(row)
        lay.addWidget(self.stage_lbl)
        lay.addWidget(self.bar)
        lay.addWidget(self.summary_lbl)
        lay.addWidget(QLabel("Registro:"))
        lay.addWidget(self.logbox, 1)

    def set_busy(self, busy: bool):
        for b in (self.btn_folder, self.btn_analyze, self.btn_upload, self.btn_retry):
            b.setEnabled(not busy)
        self.btn_stop.setEnabled(busy)
        if not busy:
            self.stage_lbl.setText("Parado")

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
            f"{CATEGORIES.get(k, k)}: <b>{v}</b>" for k, v in sorted(s.get("por_categoria", {}).items())
        )
        self.summary_lbl.setText(
            f"Arquivos: <b>{s['total']}</b> · Duplicados: <b>{s['duplicadas']}</b> · "
            f"A enviar: <b>{s['a_enviar']}</b> · Já enviados: <b>{s['enviadas']}</b> · "
            f"Erros: <b>{s['erros']}</b><br>{cats}"
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

        self.cat_combo = QComboBox()
        self.cat_combo.addItem("Todas as categorias", None)
        for k, v in CATEGORIES.items():
            self.cat_combo.addItem(v, k)
        self.cat_combo.addItem("Duplicados", "__dup")
        self.sit_combo = QComboBox()
        for label, key in (("Vão para o Google", "upload"), ("Não vão", "skip"),
                           ("Baixa confiança", "low"), ("Já enviadas", "done"),
                           ("Com erro", "error"), ("Tudo", "all")):
            self.sit_combo.addItem(label, key)
        self.cat_combo.currentIndexChanged.connect(self.reload)
        self.sit_combo.currentIndexChanged.connect(self.reload)
        self.count_lbl = QLabel()

        top = QHBoxLayout()
        top.addWidget(QLabel("Categoria:"))
        top.addWidget(self.cat_combo)
        top.addWidget(QLabel("Situação:"))
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

        self.btn_more = QPushButton("Carregar mais")
        self.btn_more.clicked.connect(self._show_more)
        btn_send = QPushButton("Enviar selecionadas")
        btn_skip = QPushButton("Não enviar")
        btn_auto = QPushButton("Voltar ao automático")
        self.move_combo = QComboBox()
        for k, v in CATEGORIES.items():
            self.move_combo.addItem(v, k)
        btn_move = QPushButton("Mudar categoria")
        btn_send.clicked.connect(lambda: self._set_decision("upload"))
        btn_skip.clicked.connect(lambda: self._set_decision("skip"))
        btn_auto.clicked.connect(lambda: self._set_decision(None))
        btn_move.clicked.connect(self._move_category)

        bottom = QHBoxLayout()
        for w in (btn_send, btn_skip, btn_auto, QLabel(" | "), self.move_combo, btn_move):
            bottom.addWidget(w)
        bottom.addStretch()
        bottom.addWidget(self.btn_more)

        hint = QLabel("Dica: Ctrl/Shift para selecionar várias. Duplo clique abre o arquivo.")
        hint.setStyleSheet("color: gray")
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.list, 1)
        lay.addLayout(bottom)
        lay.addWidget(hint)

        self.video_icon = self.style().standardIcon(QStyle.SP_MediaPlay)
        self.file_icon = self.style().standardIcon(QStyle.SP_FileIcon)

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
        cat = CATEGORIES.get(r["category"] or "", "—")
        conf = f" {r['confidence']:.0%}" if r["confidence"] is not None and r["category_by"] == "ia" else ""
        date = (r["taken_at"] or "")[:10]
        return f"{mark}{cat}{conf}\n{date}"

    def _show_more(self):
        chunk = self.rows[self.shown:self.shown + PAGE]
        thumbs = []
        for r in chunk:
            it = QListWidgetItem(self.video_icon if r["is_video"] else self.file_icon, self._label(r))
            it.setData(Qt.UserRole, r["id"])
            it.setToolTip(
                f"{r['path']}\nOrigem: {SOURCES.get(r['source'], r['source'])}"
                f"\nData: {r['taken_at']} ({r['date_source']})"
                + (f"\nCâmera: {r['camera']}" if r["camera"] else "")
                + (f"\nErro: {r['error']}" if r["error"] else "")
            )
            self.list.addItem(it)
            self.items_by_id[r["id"]] = it
            if not r["is_video"]:
                thumbs.append((r["id"], r["path"]))
        self.shown += len(chunk)
        self.count_lbl.setText(f"{self.shown} de {len(self.rows)}")
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
        self.table.setHorizontalHeaderLabels(["Título (clique duplo para renomear)", "Período", "Itens", "No Google"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._renamed)
        btn = QPushButton("Reagrupar (após mudar configurações)")
        btn.clicked.connect(lambda: self.regroup.emit())
        hint = QLabel("Os álbuns são criados no Google Fotos só no envio. Renomeie à vontade antes — "
                      "ex.: “Evento 24 a 26/12/2023” → “Natal 2023”.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")
        lay = QVBoxLayout(self)
        lay.addWidget(hint)
        lay.addWidget(self.table, 1)
        lay.addWidget(btn, 0, Qt.AlignRight)

    def reload(self):
        conn = db.connect()
        rows = conn.execute(
            "SELECT a.*, COUNT(p.id) AS n, SUM(CASE WHEN p.media_item_id IS NOT NULL THEN 1 ELSE 0 END) AS up "
            "FROM albums a LEFT JOIN photos p ON p.album_key=a.key GROUP BY a.key ORDER BY a.start DESC"
        ).fetchall()
        conn.close()
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            t = QTableWidgetItem(r["title"])
            t.setData(Qt.UserRole, r["key"])
            self.table.setItem(i, 0, t)
            s, e = (r["start"] or "")[:10], (r["end"] or "")[:10]
            period = s if s == e else f"{s} → {e}"
            for c, val in ((1, period), (2, f"{r['up'] or 0}/{r['n']}"),
                           (3, "Sim" if r["google_id"] else "Ainda não")):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(i, c, item)
        self.table.blockSignals(False)

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

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg

        cats = QGroupBox("O que vai para o Google Fotos")
        cl = QVBoxLayout(cats)
        self.cat_checks: dict[str, QCheckBox] = {}
        for k, v in CATEGORIES.items():
            cb = QCheckBox(v)
            self.cat_checks[k] = cb
            cl.addWidget(cb)
        self.wa_check = QCheckBox("Incluir fotos pessoais recebidas pelo WhatsApp")
        cl.addWidget(self.wa_check)

        proc = QGroupBox("Análise e álbuns")
        fl = QFormLayout(proc)
        self.ai_check = QCheckBox("Usar IA local (CLIP) para separar memes, prints e documentos")
        self.ai_status = QLabel()
        self.conf_spin = QDoubleSpinBox()
        self.conf_spin.setRange(0.0, 1.0)
        self.conf_spin.setSingleStep(0.05)
        self.gap_spin = QDoubleSpinBox()
        self.gap_spin.setRange(1, 720)
        self.gap_spin.setSuffix(" horas")
        self.min_spin = QSpinBox()
        self.min_spin.setRange(1, 1000)
        self.min_spin.setSuffix(" fotos")
        fl.addRow(self.ai_check)
        fl.addRow(self.ai_status)
        fl.addRow("Confiança mínima da IA:", self.conf_spin)
        fl.addRow("Novo evento após um intervalo de:", self.gap_spin)
        fl.addRow("Tamanho mínimo de um evento:", self.min_spin)

        auto = QGroupBox("Automação")
        al = QVBoxLayout(auto)
        self.scan_check = QCheckBox("Analisar automaticamente quando um HD for plugado")
        self.upload_check = QCheckBox("Enviar automaticamente após a análise (sem revisar)")
        al.addWidget(self.scan_check)
        al.addWidget(self.upload_check)

        acc = QGroupBox("Conta Google")
        gl = QVBoxLayout(acc)
        self.acc_lbl = QLabel()
        self.acc_lbl.setWordWrap(True)
        b1 = QPushButton("1. Selecionar client_secret.json…")
        b2 = QPushButton("2. Conectar conta Google")
        b3 = QPushButton("Desconectar")
        b1.clicked.connect(self._pick_secret)
        b2.clicked.connect(lambda: self.connect_google.emit())
        b3.clicked.connect(self._disconnect)
        row = QHBoxLayout()
        for b in (b1, b2, b3):
            row.addWidget(b)
        row.addStretch()
        gl.addWidget(self.acc_lbl)
        gl.addLayout(row)

        save = QPushButton("Salvar configurações")
        save.clicked.connect(self._save)

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(cats)
        right = QVBoxLayout()
        right.addWidget(proc)
        right.addWidget(auto)
        top.addLayout(right, 1)
        lay.addLayout(top)
        lay.addWidget(acc)
        lay.addStretch()
        lay.addWidget(save, 0, Qt.AlignRight)
        self.load()

    def load(self):
        c = self.cfg
        for k, cb in self.cat_checks.items():
            cb.setChecked(k in c.upload_categories)
        self.wa_check.setChecked(c.include_whatsapp)
        self.ai_check.setChecked(c.use_ai)
        self.conf_spin.setValue(c.ai_min_confidence)
        self.gap_spin.setValue(c.event_gap_hours)
        self.min_spin.setValue(c.min_event_size)
        self.scan_check.setChecked(c.auto_scan_on_drive)
        self.upload_check.setChecked(c.auto_upload)
        self.ai_status.setText(
            "IA instalada." if classifier.ai_available()
            else "IA não instalada — rode: pip install -r requirements-ia.txt (sem ela, só regras)."
        )
        self.refresh_account()

    def refresh_account(self):
        if TOKEN_PATH.exists():
            self.acc_lbl.setText("✔ Conta conectada.")
        elif google_photos.has_client_secret():
            self.acc_lbl.setText("Credencial do Google carregada. Falta clicar em “Conectar conta Google”.")
        else:
            self.acc_lbl.setText("Siga o README para criar o client_secret.json no Google Cloud (5 minutos).")

    def _pick_secret(self):
        path, _ = QFileDialog.getOpenFileName(self, "client_secret.json", "", "JSON (*.json)")
        if path:
            google_photos.install_client_secret(path)
            self.refresh_account()

    def _disconnect(self):
        google_photos.disconnect()
        self.refresh_account()

    def _save(self):
        c = self.cfg
        c.upload_categories = [k for k, cb in self.cat_checks.items() if cb.isChecked()]
        c.include_whatsapp = self.wa_check.isChecked()
        c.use_ai = self.ai_check.isChecked()
        c.ai_min_confidence = self.conf_spin.value()
        c.event_gap_hours = self.gap_spin.value()
        c.min_event_size = self.min_spin.value()
        c.auto_scan_on_drive = self.scan_check.isChecked()
        c.auto_upload = self.upload_check.isChecked()
        c.save()
        QMessageBox.information(self, "Configurações", "Salvo. Use “Reagrupar” na aba Álbuns para aplicar.")
        self.saved.emit()
