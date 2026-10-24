"""Garantia: o FotoFaxina NUNCA altera, move ou apaga os arquivos de origem (o HD do usuário).

Monta um "HD" de teste, roda o fluxo inteiro (varredura, duplicatas, classificação, álbuns,
miniaturas, envio com um Google falso, nova varredura) e confere que todos os arquivos continuam
idênticos (conteúdo, tamanho, data de modificação) e que nenhum arquivo foi criado ou removido.

    python tests/test_origem_intocada.py
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="fotofaxina-teste-"))
os.environ["FOTOFAXINA_DIR"] = str(TMP / "dados")  # pasta de dados do app, separada do "HD"

from PIL import Image, ImageDraw  # noqa: E402


def criar_hd(raiz: Path) -> None:
    (raiz / "2021" / "Celular").mkdir(parents=True)
    (raiz / "WhatsApp" / "Media").mkdir(parents=True)
    (raiz / "Prints").mkdir()
    for i in range(10):
        im = Image.new("RGB", (1600, 1200), (20 * i, 100, 200))
        ImageDraw.Draw(im).ellipse([100 + i * 20, 100, 900, 900], fill=(250, 200, 40))
        ex = Image.Exif()
        ex[272] = "Celular Teste"
        ex.get_ifd(0x8769)[36867] = datetime(2021, 12, 24, 18, i * 5).strftime("%Y:%m:%d %H:%M:%S")
        im.save(raiz / "2021" / "Celular" / f"IMG_{i:04d}.jpg", exif=ex)
    for i in range(3):
        Image.new("RGB", (800, 800), (200, 40 * i, 60)).save(raiz / "WhatsApp" / "Media" / f"IMG-2022010{i}-WA000{i}.jpg")
    Image.new("RGB", (1080, 2400), "white").save(raiz / "Prints" / "Screenshot_20220101-101010.png")
    Image.new("RGB", (512, 512), "red").save(raiz / "WhatsApp" / "Media" / "STK-20220101-WA0001.webp")
    shutil.copy(raiz / "2021" / "Celular" / "IMG_0001.jpg", raiz / "copia-duplicada.jpg")
    (raiz / "2021" / "Celular" / "VID_20211224_190000.mp4").write_bytes(os.urandom(4096))
    os.chmod(raiz / "copia-duplicada.jpg", 0o444)  # somente leitura também não pode atrapalhar


def retrato(raiz: Path) -> dict[str, tuple]:
    out = {}
    for p in sorted(raiz.rglob("*")):
        if p.is_file():
            st = p.stat()
            out[str(p.relative_to(raiz))] = (hashlib.sha256(p.read_bytes()).hexdigest(), st.st_size, st.st_mtime_ns)
    return out


def main() -> None:
    hd = TMP / "hd"
    criar_hd(hd)
    antes = retrato(hd)

    from app import pipeline
    from app.config import THUMBS_DIR, TOKEN_PATH, Config
    from app.gui.workers import ThumbJob

    cfg = Config.load()
    cfg.album_mode = "ano"
    cfg.upload_categories = list(cfg.upload_categories) + ["meme", "print", "outro"]  # envia tudo
    cfg.save()

    # 1) análise completa
    pipeline.processar(str(hd), cfg)

    # 2) miniaturas (as únicas imagens que o app grava)
    from app import db

    conn = db.connect()
    itens = [(r["id"], r["path"]) for r in conn.execute("SELECT id, path FROM photos WHERE is_video=0")]
    conn.close()
    ThumbJob(itens)._run()
    assert any(THUMBS_DIR.iterdir()), "miniaturas deveriam ter sido criadas na pasta de dados"

    # 3) envio com um Google Photos falso
    class GoogleFalso:
        n = 0

        def connect(self, interactive=True):
            pass

        def upload_bytes(self, path, mime):
            with open(path, "rb") as fh:  # lê o arquivo como o envio real faz
                fh.read()
            GoogleFalso.n += 1
            return f"tok{GoogleFalso.n}"

        def create_album(self, title):
            return f"alb-{title}", None

        def rename_album(self, *a):
            pass

        def batch_create(self, album_id, items):
            return {t: (True, "m" + t) for t, _ in items}

    pipeline.GooglePhotos = GoogleFalso
    TOKEN_PATH.write_text("{}")
    res = pipeline.enviar(cfg)
    assert res["enviados_agora"] > 0, "o teste deveria ter enviado algo"

    # 4) segunda passada (retomada) e "tentar erros de novo"
    pipeline.processar(str(hd), cfg)
    pipeline.tentar_erros_novamente()
    pipeline.enviar(cfg)

    depois = retrato(hd)
    criados = sorted(set(depois) - set(antes))
    apagados = sorted(set(antes) - set(depois))
    alterados = sorted(k for k in set(antes) & set(depois) if antes[k] != depois[k])
    assert not criados, f"arquivos CRIADOS no HD: {criados}"
    assert not apagados, f"arquivos APAGADOS do HD: {apagados}"
    assert not alterados, f"arquivos ALTERADOS no HD: {alterados}"
    print(f"OK: {len(antes)} arquivos de origem intactos após análise, miniaturas e "
          f"{res['enviados_agora']} envios.")


if __name__ == "__main__":
    try:
        main()
    finally:
        for p in TMP.rglob("*"):
            try:
                os.chmod(p, 0o700 if p.is_dir() else 0o600)
            except OSError:
                pass
        shutil.rmtree(TMP, ignore_errors=True)
