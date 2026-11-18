"""Prévia de imagem (grande, ajustada ao painel) e de vídeo (toca ali mesmo) para as abas Revisão e Lixeira.

O vídeo usa o Qt Multimedia (pacote PySide6-Addons). Sem ele, o painel avisa e o botão "Abrir no
programa do sistema" abre o arquivo no player padrão.
"""
from __future__ import annotations

import os

from PIL import Image, ImageOps
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSlider, QStackedWidget, QVBoxLayout,
                               QWidget)

from .. import scanner  # noqa: F401  (registra o leitor de HEIC no Pillow)
from ..i18n import _

try:  # o Qt Multimedia vem no PySide6-Addons (o pacote do Windows leva só o essencial)
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
    HAS_VIDEO = True
except ImportError:
    HAS_VIDEO = False

VIDEO_EXT = (".mp4", ".mov", ".3gp", ".avi", ".mkv", ".m4v")


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


class MediaPreview(QWidget):
    def __init__(self, parent=None, with_open: bool = True):
        super().__init__(parent)
        self.path: str | None = None
        self._img: QImage | None = None
        self.caption = QLabel()
        self.caption.setWordWrap(True)
        self.caption.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setMinimumSize(160, 160)
        self.label.setStyleSheet("color: gray")
        self.stack = QStackedWidget()
        self.stack.addWidget(self.label)  # página 0: imagem/texto
        self.player = None
        if HAS_VIDEO:
            self.video = QVideoWidget()
            self.player = QMediaPlayer(self)
            self.player.setAudioOutput(QAudioOutput(self))
            self.player.setVideoOutput(self.video)
            self.btn_play = QPushButton(_("Reproduzir"))
            self.btn_play.clicked.connect(self._toggle_play)
            self.seek = QSlider(Qt.Horizontal)
            self.seek.sliderMoved.connect(lambda v: self.player.setPosition(v))
            self.player.durationChanged.connect(lambda d: self.seek.setRange(0, d))
            self.player.positionChanged.connect(lambda p: None if self.seek.isSliderDown() else self.seek.setValue(p))
            self.player.playbackStateChanged.connect(
                lambda st: self.btn_play.setText(_("Pausar") if st == QMediaPlayer.PlayingState else _("Reproduzir")))
            ctl = QHBoxLayout()
            ctl.addWidget(self.btn_play)
            ctl.addWidget(self.seek, 1)
            page = QWidget()
            pl = QVBoxLayout(page)
            pl.setContentsMargins(0, 0, 0, 0)
            pl.addWidget(self.video, 1)
            pl.addLayout(ctl)
            self.stack.addWidget(page)  # página 1: vídeo
        self.btn_open = QPushButton(_("Abrir no programa do sistema"))
        self.btn_open.setToolTip(_("Abre o arquivo no visualizador ou player padrão."))
        self.btn_open.clicked.connect(self.open_external)
        self.btn_open.setVisible(with_open)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.caption)
        lay.addWidget(self.stack, 1)
        lay.addWidget(self.btn_open)

    # -- estado (também usado nos testes)
    @property
    def showing_video(self) -> bool:
        return self.stack.currentIndex() == 1

    @property
    def has_image(self) -> bool:
        pm = self.label.pixmap()
        return pm is not None and not pm.isNull()

    # -- API
    def clear(self, text: str = "", caption: str = ""):
        self.stop()
        self.path = None
        self._img = None
        self.stack.setCurrentIndex(0)
        self.label.setPixmap(QPixmap())
        self.label.setText(text)
        self.caption.setText(caption)

    def set_file(self, path: str, caption: str = "", is_video: bool | None = None):
        self.clear(caption=caption)
        self.path = path
        if not os.path.exists(path):
            self.label.setText(_("(arquivo não encontrado: o HD está plugado?)"))
            return
        video = path.lower().endswith(VIDEO_EXT) if is_video is None else is_video
        if video:
            if self.player is not None:
                self.stack.setCurrentIndex(1)
                self.player.setSource(QUrl.fromLocalFile(path))
                self.player.pause()  # mostra o primeiro quadro; o usuário aperta Reproduzir
            else:
                self.label.setText(_("(vídeo: use “Abrir no programa do sistema”)"))
            return
        try:
            with Image.open(path) as im:
                im.draft("RGB", (1400, 1400))
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail((1400, 1400))
                self._img = QImage(im.tobytes(), im.width, im.height, im.width * 3, QImage.Format_RGB888).copy()
            self.render()
        except Exception:
            self.label.setText(_("(sem prévia)"))

    def render(self):
        """Ajusta a imagem ao tamanho atual do painel (que o usuário pode arrastar)."""
        if self._img is not None and self.stack.currentIndex() == 0:
            self.label.setPixmap(QPixmap.fromImage(self._img).scaled(
                max(self.label.width() - 8, 100), max(self.label.height() - 8, 100),
                Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.render()

    def stop(self):
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())

    def _toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def open_external(self):
        if self.path and os.path.exists(self.path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))
