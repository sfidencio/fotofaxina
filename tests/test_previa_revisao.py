"""Revisão: prévia ao lado (imagem grande / vídeo) e, para uma cópia, o original lado a lado.

    python tests/test_previa_revisao.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="fotofaxina-previa-"))
os.environ["FOTOFAXINA_DIR"] = str(TMP / "dados")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PIL import Image, ImageDraw  # noqa: E402


def main():
    hd = TMP / "hd"
    (hd / "a").mkdir(parents=True)
    (hd / "b").mkdir()
    im = Image.new("RGB", (1200, 800), (20, 80, 160))
    ImageDraw.Draw(im).ellipse([100, 100, 700, 600], fill=(250, 200, 40))
    im.save(hd / "a" / "orig.jpg")
    shutil.copy(hd / "a" / "orig.jpg", hd / "b" / "copia.jpg")
    Image.new("RGB", (900, 600), (200, 30, 30)).save(hd / "sozinha.jpg")
    (hd / "clip.mp4").write_bytes(b"\x00" * 64)

    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from app import pipeline
    from app.config import Config
    from app.gui import media_preview
    from app.gui.tabs import RevisaoTab

    cfg = Config.load()
    pipeline.processar(str(hd), cfg)
    tab = RevisaoTab(cfg)
    tab.sit_combo.setCurrentIndex(tab.sit_combo.findData("all"))
    tab.cat_combo.setCurrentIndex(0)
    tab.reload()

    def escolher(nome):
        tab.list.clearSelection()
        for i in range(tab.list.count()):
            if nome in tab.list.item(i).toolTip().splitlines()[0]:
                tab.list.item(i).setSelected(True)
                app.processEvents()
                return
        raise AssertionError(f"{nome} não está na lista")

    # arquivo normal: só a prévia dele
    escolher("sozinha.jpg")
    assert tab.media_this.has_image and not tab.media_other.isVisibleTo(tab.side)
    assert "ARQUIVO" in tab.media_this.caption.text() and "900×600" in tab.media_this.caption.text()

    # cópia: mostra a cópia e o original para comparar
    tab.cat_combo.setCurrentIndex(tab.cat_combo.findData("__dup"))
    tab.reload()
    assert tab.list.count() == 1, "só uma cópia (a outra é o original mantido)"
    tab.list.item(0).setSelected(True)
    app.processEvents()
    assert tab.media_this.has_image and tab.media_other.has_image
    assert tab.media_other.isVisibleTo(tab.side)
    assert "ESTA CÓPIA" in tab.media_this.caption.text()
    assert "ORIGINAL" in tab.media_other.caption.text()
    nomes = tab.media_this.caption.text() + tab.media_other.caption.text()
    assert "orig.jpg" in nomes and "copia.jpg" in nomes, "mostra os dois arquivos para comparar"

    # vídeo: painel de vídeo (ou aviso, sem Qt Multimedia)
    tab.cat_combo.setCurrentIndex(0)
    tab.reload()
    escolher("clip.mp4")
    assert tab.media_this.showing_video == media_preview.HAS_VIDEO

    # desligar a prévia esconde o painel
    tab.chk_preview.setChecked(False)
    assert not tab.side.isVisibleTo(tab)
    print("OK: prévia na Revisão (imagem, vídeo e cópia x original).")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
