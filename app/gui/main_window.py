"""Janela principal + ícone na bandeja do sistema."""
from __future__ import annotations

import logging

from PySide6.QtCore import QThreadPool, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QMainWindow, QMenu, QMessageBox, QStyle, QSystemTrayIcon, QTabWidget,
)

from .. import __version__, db, google_photos, pipeline
from ..config import APP_DIR, APP_NAME, LOG_PATH, TOKEN_PATH, Config, resource
from ..drive_watcher import DriveWatcher
from ..i18n import _
from .tabs import AlbunsTab, ConfigTab, InicioTab, RevisaoTab
from .workers import Job

APP_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(filename=LOG_PATH, level=logging.INFO, format="%(asctime)s %(message)s", encoding="utf-8")


class MainWindow(QMainWindow):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.root: str | None = None
        self.job: Job | None = None
        self.pool = QThreadPool.globalInstance()
        self.quitting = False

        self.setWindowTitle(f"{APP_NAME} {__version__} — " + _("fotos do HD para o Google Fotos"))
        self.resize(1100, 720)
        icon_file = resource("assets/icon-256.png")
        icon = QIcon(str(icon_file)) if icon_file.exists() else self.style().standardIcon(QStyle.SP_DriveHDIcon)
        self.setWindowIcon(icon)

        self.inicio = InicioTab()
        self.revisao = RevisaoTab(cfg)
        self.albuns = AlbunsTab()
        self.config_tab = ConfigTab(cfg)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.inicio, _("Início"))
        self.tabs.addTab(self.revisao, _("Revisão"))
        self.tabs.addTab(self.albuns, _("Álbuns"))
        self.tabs.addTab(self.config_tab, _("Configurações"))
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)

        self.inicio.choose_folder.connect(self.choose_folder)
        self.inicio.analyze.connect(self.start_analyze)
        self.inicio.upload.connect(self.start_upload)
        self.inicio.stop.connect(self.stop_job)
        self.inicio.retry_errors.connect(self.retry_errors)
        self.revisao.changed.connect(self.refresh_summary)
        self.albuns.regroup.connect(self.start_regroup)
        self.config_tab.connect_google.connect(self.start_connect)
        self.config_tab.download_ai.connect(self.start_download_ai)
        self.config_tab.saved.connect(self.refresh_summary)

        # bandeja
        self.tray = QSystemTrayIcon(icon, self)
        menu = QMenu()
        for text, slot in ((_("Abrir"), self.show_normal), (_("Parar tarefa"), self.stop_job), (_("Sair"), self.quit_app)):
            act = QAction(text, self)
            act.triggered.connect(slot)
            menu.addAction(act)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip(APP_NAME)
        self.tray.activated.connect(lambda reason: self.show_normal()
                                    if reason == QSystemTrayIcon.Trigger else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

        self.watcher = DriveWatcher(parent=self)
        self.watcher.drive_added.connect(self.on_drive_added)

        self.refresh_summary()
        self.inicio.log(_("Pronto. Plugue um HD ou escolha uma pasta."))
        if not cfg.welcome_done:
            QTimer.singleShot(400, self.welcome)

    def welcome(self):
        """Primeira execução: explica em 3 linhas e já oferece conectar a conta Google."""
        self.cfg.welcome_done = True
        self.cfg.save()
        self.show_normal()
        texto = _(
            "<h3>Bem-vindo ao FotoFaxina!</h3>"
            "<p>1. Conecte sua conta do Google Fotos.<br>"
            "2. Plugue o HD (ou escolha uma pasta) — a análise começa sozinha.<br>"
            "3. Confira o resultado e clique em <b>Enviar para o Google Fotos</b>.</p>"
            "<p>O programa fica perto do relógio do Windows, esperando o HD.</p>"
        )
        ask = google_photos.has_client_secret() and not TOKEN_PATH.exists()
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setTextFormat(Qt.RichText)
        box.setText(texto + (_("<p><b>Conectar a conta Google agora?</b></p>") if ask else ""))
        pix = QPixmap(str(resource("assets/mascote-128.png")))
        if not pix.isNull():
            box.setIconPixmap(pix)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No if ask else QMessageBox.Ok)
        if box.exec() == QMessageBox.Yes and ask:
            self.start_connect()

    # ---------------- utilidades
    def notify(self, title: str, msg: str):
        if self.tray.isVisible():
            self.tray.showMessage(title, msg, QSystemTrayIcon.Information, 8000)

    def log(self, text: str):
        self.inicio.log(text)
        logging.info(text)

    def refresh_summary(self):
        conn = db.connect()
        s = db.summary(conn, self.cfg)
        conn.close()
        self.inicio.show_summary(s)
        conn_txt = (_("✔ Conta Google conectada") if TOKEN_PATH.exists()
                    else _("✖ Conta Google não conectada (veja Configurações)"))
        self.inicio.account_lbl.setText(conn_txt)
        self.config_tab.refresh_account()

    def set_root(self, path: str, label: str | None = None):
        self.root = path
        self.inicio.source_lbl.setText(_("Origem: <b>{nome}</b> — {caminho}").format(nome=label or path, caminho=path))

    def _tab_changed(self, idx: int):
        w = self.tabs.widget(idx)
        if w is self.revisao:
            self.revisao.reload()
        elif w is self.albuns:
            self.albuns.reload()

    # ---------------- tarefas
    def _run(self, name: str, fn, *args) -> bool:
        if self.job is not None:
            QMessageBox.information(self, _("Aguarde"), _("Já existe uma tarefa em andamento."))
            return False
        self.job = Job(name, fn, *args)
        self.job.signals.progress.connect(self.inicio.set_progress)
        self.job.signals.log.connect(self.log)
        self.job.signals.finished.connect(self._job_done)
        self.job.signals.failed.connect(self._job_failed)
        self.inicio.set_busy(True)
        self.pool.start(self.job)
        return True

    def _clear_job(self):
        self.job = None
        self.inicio.set_busy(False)
        self.inicio.bar.setRange(0, 1)
        self.refresh_summary()

    def _job_done(self, name: str, res):
        self._clear_job()
        if name == "analisar":
            if isinstance(res, dict) and not res.get("parado"):
                msg = _("{n} itens prontos para enviar ({dup} duplicados ignorados).").format(
                    n=res["a_enviar"], dup=res["duplicadas"])
                self.log(_("Análise concluída.") + " " + msg)
                self.notify(_("Análise concluída"), msg)
                if self.cfg.auto_upload and TOKEN_PATH.exists():
                    self.start_upload()
                else:
                    self.log(_("Revise na aba Revisão/Álbuns e clique em “Enviar para o Google Fotos”."))
            else:
                self.log(_("Análise interrompida. Clique em Analisar para continuar de onde parou."))
        elif name == "enviar":
            msg = _("{ok} enviados, {err} com erro.").format(ok=res.get("enviados_agora", 0),
                                                             err=res.get("erros_agora", 0))
            self.notify(_("Envio concluído"), msg)
        elif name == "conectar":
            QMessageBox.information(self, _("Google Fotos"), _("Conta conectada com sucesso!"))
        elif name == "baixar_ia":
            self.config_tab.refresh_ai()
            if res:
                QMessageBox.information(self, _("Inteligência artificial"),
                                        _("Modelo de IA instalado. Na próxima análise ele já será usado."))
        elif name == "reagrupar":
            self.albuns.reload()

    def _job_failed(self, name: str, err: str):
        self._clear_job()
        self.log(_("Erro em {tarefa}: {erro}").format(tarefa=name, erro=err))
        QMessageBox.warning(self, _("Erro"), err)

    def start_analyze(self):
        if not self.root:
            self.choose_folder()
            if not self.root:
                return
        self._run("analisar", pipeline.processar, self.root, self.cfg)

    def start_upload(self):
        if not TOKEN_PATH.exists():
            QMessageBox.information(self, _("Google Fotos"), _("Conecte sua conta Google na aba Configurações primeiro."))
            self.tabs.setCurrentWidget(self.config_tab)
            return
        self._run("enviar", pipeline.enviar, self.cfg)

    def start_regroup(self):
        self._run("reagrupar", pipeline.reagrupar, self.cfg)

    def start_connect(self):
        self.log(_("Abrindo o navegador para login no Google…"))
        self._run("conectar", pipeline.conectar_google)

    def start_download_ai(self):
        from .. import model_download

        self.tabs.setCurrentWidget(self.inicio)
        self._run("baixar_ia", model_download.download_model)

    def stop_job(self):
        if self.job is not None:
            self.job.stop.set()
            self.log(_("Parando após o item atual…"))

    def retry_errors(self):
        n = pipeline.tentar_erros_novamente()
        self.log(_("{n} itens com erro voltaram para a fila.").format(n=n))
        self.refresh_summary()

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, _("Escolha a pasta ou o HD com as fotos"))
        if path:
            self.set_root(path)

    # ---------------- HD plugado
    def on_drive_added(self, mountpoint: str, label: str):
        self.log(_("HD detectado: {nome}").format(nome=label))
        if self.job is not None:
            self.notify(_("HD detectado"), _("{nome} — será analisado quando a tarefa atual terminar.").format(nome=label))
            return
        if self.cfg.auto_scan_on_drive:
            self.set_root(mountpoint, label)
            self.notify(_("HD detectado"), _("Analisando {nome}…").format(nome=label))
            self.start_analyze()
        else:
            self.show_normal()
            if QMessageBox.question(self, _("HD detectado"),
                                    _("Analisar as fotos de {nome}?").format(nome=label)) == QMessageBox.Yes:
                self.set_root(mountpoint, label)
                self.start_analyze()

    # ---------------- janela/bandeja
    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent):
        if not self.quitting and self.tray.isVisible():
            event.ignore()
            self.hide()
            self.notify(APP_NAME, _("Continua rodando aqui, perto do relógio. Plugue um HD quando quiser."))
            return
        event.accept()

    def quit_app(self):
        self.quitting = True
        if self.job is not None:
            self.job.stop.set()
        self.pool.waitForDone(5000)
        QApplication.quit()
