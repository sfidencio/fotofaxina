"""Gera os PNG/ICO do mascote e do ícone a partir dos SVG (rode após editar os SVG)."""
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def render(svg: Path, size: int, out: Path):
    r = QSvgRenderer(str(svg))
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p)
    p.end()
    img.save(str(out))


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    for size in (512, 128):
        render(ASSETS / "mascote.svg", size, ASSETS / f"mascote-{size}.png")
    render(ASSETS / "icon.svg", 1024, ASSETS / "icon.png")
    big = Image.open(ASSETS / "icon.png")
    big.resize((256, 256), Image.LANCZOS).save(ASSETS / "icon-256.png")
    big.resize((256, 256), Image.LANCZOS).save(
        ASSETS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("ok")
