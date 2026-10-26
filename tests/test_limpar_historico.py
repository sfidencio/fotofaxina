"""Fluxo de quem limpa o histórico para manter tudo limpo: depois de "Limpar todo o histórico",
as fotos novas de um ano vão para o álbum desse ano que já existe no Google Fotos (sem "parte 2")
e as que já foram enviadas não sobem de novo.

    python tests/test_limpar_historico.py
"""
import os
import random
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="fotofaxina-limpar-"))
os.environ["FOTOFAXINA_DIR"] = str(TMP / "dados")

from PIL import Image, ImageDraw  # noqa: E402


def foto(path, seed, dt):
    rnd = random.Random(seed)
    im = Image.new("RGB", (900, 700), tuple(rnd.randint(0, 255) for _ in range(3)))
    d = ImageDraw.Draw(im)
    for _ in range(10):
        x, y = rnd.randint(0, 800), rnd.randint(0, 600)
        d.rectangle([x, y, x + 90, y + 90], fill=tuple(rnd.randint(0, 255) for _ in range(3)))
    ex = Image.Exif()
    ex[271], ex[272] = "Samsung", "S21"
    ex.get_ifd(0x8769)[36867] = dt.strftime("%Y:%m:%d %H:%M:%S")
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, exif=ex)


class GoogleFalso:
    albuns: list = []
    enviadas = 0
    n = 0

    def connect(self, interactive=True):
        pass

    def upload_bytes(self, path, mime):
        GoogleFalso.n += 1
        GoogleFalso.enviadas += 1
        return f"t{GoogleFalso.n}"

    def create_album(self, title):
        GoogleFalso.albuns.append(title)
        return f"alb{len(GoogleFalso.albuns)}", None

    def rename_album(self, *a):
        pass

    def batch_create(self, album_id, items):
        return {t: (True, "m" + t) for t, _ in items}


def main():
    from app import db, pipeline
    from app.config import TOKEN_PATH, Config

    pipeline.GooglePhotos = GoogleFalso
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text("{}")
    cfg = Config.load()
    cfg.album_mode = "ano"
    cfg.use_ai = False
    p1, p2 = TMP / "hd" / "2023 parte 1", TMP / "hd" / "2023 parte 2"
    for i in range(5):
        foto(p1 / f"a{i}.jpg", i, datetime(2023, 3, 1) + timedelta(days=i))
    for i in range(4):
        foto(p2 / f"b{i}.jpg", 50 + i, datetime(2023, 9, 1) + timedelta(days=i))

    pipeline.processar(str(p1), cfg)
    pipeline.enviar(cfg)
    assert GoogleFalso.albuns == ["Fotos 2023"] and GoogleFalso.enviadas == 5

    conn = db.connect()  # usuário: Configurações → Limpar todo o histórico
    db.forget_all(conn)
    conn.close()

    pipeline.processar(str(p2), cfg)
    pipeline.enviar(cfg)
    assert GoogleFalso.albuns == ["Fotos 2023"], f"criou outro álbum depois de limpar: {GoogleFalso.albuns}"
    assert GoogleFalso.enviadas == 9

    conn = db.connect()  # limpa de novo e analisa a parte 1 outra vez: nada sobe repetido
    db.forget_all(conn)
    conn.close()
    r = pipeline.processar(str(p1), cfg)
    pipeline.enviar(cfg)
    assert GoogleFalso.enviadas == 9, "fotos já enviadas subiram de novo depois de limpar o histórico"
    assert r["pasta"]["ja_no_google"] == 5, r["pasta"]
    print("OK: depois de limpar o histórico, fotos novas vão para o mesmo “Fotos 2023” e nada é reenviado.")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
