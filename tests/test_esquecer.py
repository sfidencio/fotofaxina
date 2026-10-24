"""Esquecer registros: pasta, itens e tudo — sem tocar em arquivos — e caminhos repetidos
("C:/a" x "C:\\a") que versões antigas gravavam em dobro.

    python tests/test_esquecer.py
"""
import hashlib
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="fotofaxina-esquecer-"))
os.environ["FOTOFAXINA_DIR"] = str(TMP / "dados")

from PIL import Image  # noqa: E402


class GoogleFalso:
    n = 0
    albuns_apagados: set = set()

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
        from app.google_photos import GooglePhotosError

        if album_id in GoogleFalso.albuns_apagados:
            raise GooglePhotosError("400: Invalid album id")
        return {t: (True, "m" + t) for t, _ in items}


def hashes(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(folder).rglob("*") if p.is_file()}


def main():
    hd = TMP / "hd"
    hd.mkdir()
    for i in range(3):
        ex = Image.Exif()
        ex[272] = "Celular"
        ex.get_ifd(0x8769)[36867] = datetime(2014, 5, 1 + i).strftime("%Y:%m:%d %H:%M:%S")
        Image.new("RGB", (1000, 800), (60 * i, 50, 90)).save(hd / f"IMG_{i}.jpg", exif=ex)
    antes = hashes(hd)

    from app import db, pipeline
    from app.config import TOKEN_PATH, Config

    pipeline.GooglePhotos = GoogleFalso
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text("{}")
    cfg = Config.load()

    pipeline.processar(str(hd), cfg)
    assert pipeline.enviar(cfg)["enviados_agora"] == 3
    r = pipeline.processar(str(hd), cfg)
    assert r["pasta"]["ja_no_google"] == 3, r["pasta"]

    # caminhos com variações viram um registro só (simula o "/" x "\" do Windows)
    conn = db.connect()
    rid = conn.execute("SELECT id FROM photos LIMIT 1").fetchone()[0]
    p = conn.execute("SELECT path FROM photos WHERE id=?", (rid,)).fetchone()[0]
    torto = p.replace(os.sep + "IMG_", os.sep + "." + os.sep + "IMG_")
    conn.execute("INSERT INTO photos(path, sha256, status) SELECT ?, sha256, 'classified' FROM photos WHERE id=?",
                 (torto, rid))
    conn.commit()
    conn.close()
    conn = db.connect()  # a migração roda ao conectar
    assert conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 3, "variações de caminho não foram unidas"
    assert conn.execute("SELECT media_item_id FROM photos WHERE id=?", (rid,)).fetchone()[0], "perdeu o envio"

    # esquecer a pasta: volta tudo para "a enviar"; álbum apagado no Google é recriado
    assert db.forget(conn, db.ids_under(conn, str(hd))) == 3
    conn.close()
    r = pipeline.processar(str(hd), cfg)
    assert r["pasta"]["a_enviar"] == 3, r["pasta"]
    conn = db.connect()
    GoogleFalso.albuns_apagados = {a[0] for a in conn.execute("SELECT google_id FROM albums") if a[0]}
    conn.close()
    assert GoogleFalso.albuns_apagados, "o álbum enviado deveria ter sido mantido"
    res = pipeline.enviar(cfg)
    assert res["enviados_agora"] == 3 and res["erros_agora"] == 0, res

    # esquecer itens e tudo
    conn = db.connect()
    one = conn.execute("SELECT id FROM photos LIMIT 1").fetchone()[0]
    assert db.forget(conn, [one]) == 1
    assert db.forget_all(conn) == 2
    assert conn.execute("SELECT COUNT(*) FROM albums").fetchone()[0] == 0
    conn.close()

    assert hashes(hd) == antes, "arquivos de origem foram alterados!"
    print("OK: esquecer pasta/itens/tudo, caminhos unidos e álbum recriado — arquivos intactos.")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
