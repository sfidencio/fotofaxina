"""Fotos do mesmo evento analisadas em momentos diferentes (ex.: primeiro o meu celular, depois o
da esposa) vão para o MESMO álbum no Google Fotos. E um evento ainda não enviado que cresce
mantém o nome que o usuário deu na aba Álbuns.

    python tests/test_evento_continua.py
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
TMP = Path(tempfile.mkdtemp(prefix="fotofaxina-evento-"))
os.environ["FOTOFAXINA_DIR"] = str(TMP / "dados")

from PIL import Image, ImageDraw  # noqa: E402


def foto(path, seed, dt):
    rnd = random.Random(seed)
    im = Image.new("RGB", (1000, 750), tuple(rnd.randint(0, 255) for _ in range(3)))
    d = ImageDraw.Draw(im)
    for _ in range(12):
        x, y = rnd.randint(0, 900), rnd.randint(0, 650)
        d.rectangle([x, y, x + rnd.randint(30, 200), y + rnd.randint(30, 200)],
                    fill=tuple(rnd.randint(0, 255) for _ in range(3)))
    ex = Image.Exif()
    ex[271], ex[272] = "Samsung", "Galaxy"
    ex.get_ifd(0x8769)[36867] = dt.strftime("%Y:%m:%d %H:%M:%S")
    im.save(path, exif=ex)


class GoogleFalso:
    albuns: list = []
    n = 0

    def connect(self, interactive=True):
        pass

    def upload_bytes(self, path, mime):
        GoogleFalso.n += 1
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
    cfg.use_ai = False

    # 1) Natal: 8 fotos minhas enviadas; depois 3 da esposa, no mesmo dia, mais cedo
    natal = datetime(2023, 12, 24, 10)
    meu, esposa = TMP / "hd" / "Meu celular", TMP / "hd" / "Celular esposa"
    meu.mkdir(parents=True)
    esposa.mkdir(parents=True)
    for i in range(8):
        foto(meu / f"IMG_{i}.jpg", i, natal + timedelta(hours=i))
    pipeline.processar(str(meu), cfg)
    pipeline.enviar(cfg)
    for i in range(3):
        foto(esposa / f"IMG_e{i}.jpg", 100 + i, natal - timedelta(hours=3) + timedelta(minutes=10 * i))
    pipeline.processar(str(esposa), cfg)
    res = pipeline.enviar(cfg)
    assert res["enviados_agora"] == 3, res
    assert len(GoogleFalso.albuns) == 1, f"o mesmo Natal virou vários álbuns: {GoogleFalso.albuns}"
    conn = db.connect()
    keys = {r[0] for r in conn.execute("SELECT album_key FROM photos")}
    conn.close()
    assert len(keys) == 1, keys

    # 2) Réveillon ainda não enviado, renomeado pelo usuário; aparecem fotos de antes → mantém o nome
    rev = datetime(2023, 12, 31, 20)
    pasta = TMP / "hd" / "Reveillon"
    pasta.mkdir()
    for i in range(8):
        foto(pasta / f"R_{i}.jpg", 200 + i, rev + timedelta(minutes=30 * i))
    pipeline.processar(str(pasta), cfg)
    conn = db.connect()
    key = conn.execute("SELECT album_key FROM photos WHERE path LIKE ?", ("%R_0.jpg",)).fetchone()[0]
    conn.execute("UPDATE albums SET title='Réveillon 2023', custom_title=1 WHERE key=?", (key,))
    conn.commit()
    conn.close()
    for i in range(3):
        foto(pasta / f"R_antes_{i}.jpg", 300 + i, rev - timedelta(hours=2) + timedelta(minutes=10 * i))
    pipeline.processar(str(pasta), cfg)
    pipeline.enviar(cfg)
    assert GoogleFalso.albuns[1:] == ["Réveillon 2023"], f"perdeu o nome dado pelo usuário: {GoogleFalso.albuns}"
    print("OK: fotos do mesmo evento vão para o mesmo álbum e o nome dado pelo usuário é mantido.")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
