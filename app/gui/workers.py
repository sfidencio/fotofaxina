"""Execução das etapas em segundo plano sem travar a janela."""
from __future__ import annotations

import os
import threading
import traceback

from PIL import Image, ImageOps
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from ..config import THUMBS_DIR


class JobSignals(QObject):
    progress = Signal(str, int, int, str)
    log = Signal(str)
    finished = Signal(str, object)
    failed = Signal(str, str)


class Job(QRunnable):
    """Roda fn(*args, progress=, log=, stop=) numa thread do pool."""

    def __init__(self, name: str, fn, *args):
        super().__init__()
        self.setAutoDelete(False)
        self.name, self.fn, self.args = name, fn, args
        self.signals = JobSignals()
        self.stop = threading.Event()

    @Slot()
    def run(self):
        try:
            res = self.fn(*self.args, progress=self._progress, log=self.signals.log.emit, stop=self.stop)
            self.signals.finished.emit(self.name, res)
        except Exception as e:
            self.signals.log.emit(traceback.format_exc())
            self.signals.failed.emit(self.name, str(e))

    def _progress(self, stage, done, total, msg=""):
        self.signals.progress.emit(stage, int(done), int(total), str(msg))


class ThumbSignals(QObject):
    ready = Signal(int, str)


class ThumbJob(QRunnable):
    """Gera miniaturas (inclusive HEIC, que o Qt não lê) e avisa a janela."""

    def __init__(self, items: list[tuple[int, str]]):
        super().__init__()
        self.setAutoDelete(False)
        self.items = items
        self.signals = ThumbSignals()
        self.cancelled = False
        self.done = False

    @Slot()
    def run(self):
        try:
            self._run()
        finally:
            self.done = True

    def _run(self):
        THUMBS_DIR.mkdir(parents=True, exist_ok=True)
        for pid, path in self.items:
            if self.cancelled:
                return
            out = THUMBS_DIR / f"{pid}.jpg"
            if not out.exists():
                try:
                    with Image.open(path) as im:
                        im = ImageOps.exif_transpose(im).convert("RGB")
                        im.thumbnail((256, 256))
                        # miniatura quadrada para a grade ficar alinhada
                        sq = Image.new("RGB", (256, 256), (235, 235, 235))
                        sq.paste(im, ((256 - im.width) // 2, (256 - im.height) // 2))
                        sq.save(out, "JPEG", quality=80)
                except Exception:
                    continue
            if os.path.exists(out):
                self.signals.ready.emit(pid, str(out))
