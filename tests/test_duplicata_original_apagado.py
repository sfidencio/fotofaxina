"""Se a pasta analisada antes foi apagada, a cópia que ainda existe tem de virar a original
(e ir para o envio) — antes ela ficava marcada como duplicata de um arquivo inexistente.

    python tests/test_duplicata_original_apagado.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="fotofaxina-dup-"))
os.environ["FOTOFAXINA_DIR"] = str(TMP / "dados")

from PIL import Image  # noqa: E402


def main():
    a, b = TMP / "extraido", TMP / "extraido-1-001"
    a.mkdir()
    for i in range(4):
        ex = Image.Exif()
        ex[272] = "Celular"
        ex.get_ifd(0x8769)[36867] = datetime(2014, 5, 1 + i, 10).strftime("%Y:%m:%d %H:%M:%S")
        Image.new("RGB", (1200, 900), (40 * i, 90, 160)).save(a / f"IMG_{i}.jpg", exif=ex)

    from app import pipeline
    from app.config import Config

    cfg = Config.load()
    pipeline.processar(str(a), cfg)
    shutil.copytree(a, b)
    r = pipeline.processar(str(b), cfg)
    assert r["pasta"]["repetidas"] == 4, r["pasta"]  # cópias: a primeira pasta ainda existe

    shutil.rmtree(a)  # usuário apagou a primeira extração
    r = pipeline.processar(str(b), cfg)
    assert r["pasta"]["a_enviar"] == 4, f"as cópias que existem deveriam ir para o envio: {r['pasta']}"
    print("OK: cópias viram originais quando a pasta antiga some.")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
