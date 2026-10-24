"""Detecta quando um HD/pendrive é plugado (Windows, Linux e macOS) usando psutil."""
from __future__ import annotations

import os
import sys

import psutil
from PySide6.QtCore import QObject, QTimer, Signal


def volume_label(mountpoint: str) -> str:
    if sys.platform == "win32":
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(261)
            ok = ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(mountpoint), buf, 261, None, None, None, None, 0
            )
            if ok and buf.value:
                return f"{buf.value} ({mountpoint.rstrip(os.sep)})"
        except Exception:
            pass
        return mountpoint
    return os.path.basename(mountpoint.rstrip("/")) or mountpoint


def _mounts() -> dict[str, str]:
    out = {}
    for p in psutil.disk_partitions(all=False):
        mp = p.mountpoint
        if sys.platform.startswith("linux") and not mp.startswith(("/media", "/mnt", "/run/media")):
            continue
        if sys.platform == "darwin" and not mp.startswith("/Volumes/"):
            continue
        if "cdrom" in p.opts:
            continue
        out[mp] = p.fstype
    return out


class DriveWatcher(QObject):
    drive_added = Signal(str, str)    # ponto de montagem, rótulo
    drive_removed = Signal(str)

    def __init__(self, interval_ms: int = 4000, parent=None):
        super().__init__(parent)
        self._known = set(_mounts())
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(interval_ms)

    def _poll(self):
        try:
            now = set(_mounts())
        except Exception:
            return
        for mp in sorted(now - self._known):
            self.drive_added.emit(mp, volume_label(mp))
        for mp in sorted(self._known - now):
            self.drive_removed.emit(mp)
        self._known = now
