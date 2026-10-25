"""Fotos parecidas, mas diferentes (sequência, rajada, luz mudando) NÃO podem ser tratadas como
duplicata — senão ficam fora do Google Fotos. Cópias de verdade (reenviada pelo WhatsApp,
exportada em tamanho menor) continuam sendo reconhecidas. E "Não é duplicata" vale para sempre.

    python tests/test_duplicatas_parecidas.py
"""
import io
import os
import random
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="fotofaxina-parecidas-"))
os.environ["FOTOFAXINA_DIR"] = str(TMP / "dados")

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter  # noqa: E402


def cena(seed, w=1600, h=1200):
    rnd = random.Random(seed)
    im = Image.new("RGB", (w, h), (90, 120, 160))
    d = ImageDraw.Draw(im)
    for _ in range(40):
        x, y = rnd.randint(0, w - 100), rnd.randint(0, h - 100)
        d.ellipse([x, y, x + rnd.randint(40, 300), y + rnd.randint(40, 300)],
                  fill=tuple(rnd.randint(0, 255) for _ in range(3)))
    return im.filter(ImageFilter.GaussianBlur(3))


def salva(im, path, dt=None, camera="Galaxy S21"):
    if dt is None:  # sem EXIF (cópia do WhatsApp, imagem baixada…)
        im.save(path, quality=60)
        return
    ex = Image.Exif()
    ex[271], ex[272] = "Samsung", camera
    ex.get_ifd(0x8769)[36867] = dt.strftime("%Y:%m:%d %H:%M:%S")
    im.save(path, exif=ex, quality=92)


class GoogleFalso:
    n = 0

    def connect(self, interactive=True):
        pass

    def upload_bytes(self, path, mime):
        GoogleFalso.n += 1
        return f"t{GoogleFalso.n}"

    def create_album(self, title):
        GoogleFalso.n += 1
        return f"alb{GoogleFalso.n}", None

    def rename_album(self, *a):
        pass

    def batch_create(self, album_id, items):
        return {t: (True, "m" + t) for t, _ in items}


def main():
    from app import db, pipeline
    from app.config import TOKEN_PATH, Config
    from app.phash import phash

    hd = TMP / "hd"
    (hd / "Camera").mkdir(parents=True)
    (hd / "WhatsApp Images").mkdir(parents=True)
    (hd / "Baixadas").mkdir(parents=True)

    a = cena(7)
    b = ImageEnhance.Brightness(a).enhance(1.08)  # o clique seguinte, com um pouco mais de luz
    assert phash(a) == phash(b), "pré-condição: as duas fotos da sequência têm o mesmo hash perceptual"
    salva(a, hd / "Camera" / "20231224_100000.jpg", datetime(2023, 12, 24, 10, 0, 0))
    salva(b, hd / "Camera" / "20231224_100002.jpg", datetime(2023, 12, 24, 10, 0, 2))

    # cópia reenviada pelo WhatsApp: ~1280 px, recomprimida e sem EXIF
    copia = a.resize((1280, 960))
    buf = io.BytesIO()
    copia.save(buf, "JPEG", quality=75)
    assert phash(Image.open(io.BytesIO(buf.getvalue())).convert("RGB")) == phash(a), "pré-condição da cópia"
    (hd / "WhatsApp Images" / "IMG-20231226-WA0001.jpg").write_bytes(buf.getvalue())

    # exportada em tamanho menor, mantendo o EXIF (mesma data e câmera): também é cópia
    salva(a.resize((1200, 900)), hd / "Camera" / "20231224_100000-export.jpg", datetime(2023, 12, 24, 10, 0, 0))

    # duas imagens sem EXIF, parecidas: tratadas como cópia até o usuário dizer que não são
    c = cena(9)
    d = ImageEnhance.Brightness(c).enhance(1.08)
    assert phash(c) == phash(d)
    salva(c, hd / "Baixadas" / "festa1.jpg")
    salva(d, hd / "Baixadas" / "festa2.jpg")

    pipeline.GooglePhotos = GoogleFalso
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text("{}")
    cfg = Config.load()
    cfg.use_ai = False
    cfg.upload_categories = ["foto", "paisagem", "video", "outro"]
    pipeline.processar(str(hd), cfg)

    conn = db.connect()
    by_name = {os.path.basename(r["path"]): r for r in conn.execute("SELECT * FROM photos")}
    seq1, seq2 = by_name["20231224_100000.jpg"], by_name["20231224_100002.jpg"]
    assert seq1["duplicate_of"] is None and seq2["duplicate_of"] is None, \
        "fotos em sequência (datas diferentes na câmera) foram tratadas como duplicata"
    # sem EXIF não dá para saber de qual das duas fotos da sequência a cópia veio; as duas são
    # enviadas, então qualquer uma serve como original
    assert by_name["IMG-20231226-WA0001.jpg"]["duplicate_of"] in (seq1["id"], seq2["id"]), \
        "a cópia do WhatsApp deveria apontar para uma foto da câmera"
    assert by_name["20231224_100000-export.jpg"]["duplicate_of"] == seq1["id"], \
        "a cópia exportada (mesma data e câmera) deveria apontar para a foto com a mesma data"
    f1, f2 = by_name["festa1.jpg"], by_name["festa2.jpg"]
    dup = f2 if f2["duplicate_of"] is not None else f1
    assert (f1["duplicate_of"] is None) != (f2["duplicate_of"] is None), "sem EXIF: uma vira cópia da outra"

    # usuário: "Não é duplicata" → é classificada, enviada e continua assim nas próximas análises
    assert db.mark_not_duplicate(conn, [dup["id"]]) == 1
    conn.close()
    res = pipeline.enviar(cfg)
    assert res["enviados_agora"] == 4, res  # sequência (2) + festa (2)
    pipeline.processar(str(hd), cfg)
    conn = db.connect()
    r = conn.execute("SELECT duplicate_of, media_item_id FROM photos WHERE id=?", (dup["id"],)).fetchone()
    conn.close()
    assert r["duplicate_of"] is None and r["media_item_id"], "“Não é duplicata” deixou de valer"
    print("OK: fotos em sequência são enviadas, cópias reconhecidas e “Não é duplicata” é respeitado.")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
