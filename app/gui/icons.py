"""Ícones dos botões, desenhados aqui mesmo (traço simples, 24×24).

Ficam no código em vez de arquivos para não depender do empacotamento. A cor vem do tema do
sistema (claro ou escuro) — exceto nos destaques: ação principal (verde-água do mascote) e ações
que apagam histórico (vermelho).
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

PATHS: dict[str, str] = {
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "analyze": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M20 20l-4.8-4.8"/>'
               '<path d="M10.5 7.5v6M7.5 10.5h6"/>',
    "upload": '<path d="M7 18H6.5a4.5 4.5 0 0 1-.4-9 6 6 0 0 1 11.6 1.2A4 4 0 0 1 17.5 18H17"/>'
              '<path d="M12 21v-9M8.5 15.5 12 12l3.5 3.5"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "retry": '<path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 4v5h-5"/>',
    "eraser": '<path d="M3.5 14.5 13 5a2 2 0 0 1 2.8 0l3.2 3.2a2 2 0 0 1 0 2.8L12 18H7z"/>'
              '<path d="M8.5 9.5l6 6M7 21h13"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "skip": '<circle cx="12" cy="12" r="8.5"/><path d="M6 6l12 12"/>',
    "auto": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "tag": '<path d="M3 11.6V4a1 1 0 0 1 1-1h7.6a1 1 0 0 1 .7.3l8.4 8.4a1 1 0 0 1 0 1.4l-7.6 7.6a1 1 0 0 1-1.4 0'
           'l-8.4-8.4a1 1 0 0 1-.3-.7z"/><circle cx="7.5" cy="7.5" r="1.3"/>',
    "notdup": '<rect x="2.5" y="5" width="8" height="14" rx="1.5"/><rect x="13.5" y="5" width="8" height="14" rx="1.5"/>'
              '<path d="M5 15l2.5-3 2 2M16 15l2-2.5 1.5 2"/>',
    "more": '<path d="M6 9.5l6 6 6-6"/>',
    "share": '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>',
    "regroup": '<path d="M12 3 21 8l-9 5-9-5z"/><path d="M3 12.5l9 5 9-5M3 17l9 5 9-5"/>',
    "download": '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
    "file": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>'
            '<circle cx="9.5" cy="15" r="2"/><path d="M11.5 15h5M15 15v2"/>',
    "login": '<path d="M10 17l5-5-5-5M15 12H3"/><path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4"/>',
    "logout": '<path d="M15 17l5-5-5-5M20 12H9"/><path d="M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5M14 11v5"/>',
    "save": '<path d="M5 3h11l5 5v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M7 3v5h8V3M7 21v-7h10v7"/>',
    "open": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/>',
    "quit": '<path d="M12 3v9"/><path d="M6.3 6.6a8 8 0 1 0 11.4 0"/>',
}

ACCENT = "#0d9488"   # verde-água do mascote: ações principais
DANGER = "#dc2626"   # apaga histórico (nunca arquivos)
SIZES = (16, 20, 24, 32, 48)


def _svg(name: str, color: str) -> bytes:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f'{PATHS[name]}</svg>'
    ).encode()


def _pixmap(name: str, color: str, size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(_svg(name, color))).render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pm


def icon(name: str, tone: str | None = None) -> QIcon:
    """tone: None (cor do texto do tema), "accent" ou "danger"."""
    pal = QApplication.palette()
    dark = pal.color(QPalette.Window).lightness() < 128  # tema escuro: tons mais claros
    tones = {"accent": "#2dd4bf" if dark else ACCENT, "danger": "#f87171" if dark else DANGER}
    normal = tones.get(tone) or pal.color(QPalette.ButtonText).name()
    disabled = pal.color(QPalette.Disabled, QPalette.ButtonText)
    if disabled.alpha() == 255 and disabled.name() == pal.color(QPalette.ButtonText).name():
        disabled = QColor(150, 150, 150)  # alguns temas não definem a cor de desativado
    ic = QIcon()
    for s in SIZES:
        ic.addPixmap(_pixmap(name, normal, s), QIcon.Normal)
        ic.addPixmap(_pixmap(name, disabled.name(), s), QIcon.Disabled)
    return ic


def set_icon(widget, name: str, tone: str | None = None) -> None:
    widget.setIcon(icon(name, tone))
