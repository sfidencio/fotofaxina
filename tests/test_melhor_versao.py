"""Versão pior (ex.: reduzida pelo WhatsApp) já está no Google e o original bom está no HD: o original
NÃO vira "cópia"; ele é enviado e a versão pior entra na lista para apagar no Google. Cópias de
qualidade igual continuam sendo duplicatas, e uma "cópia" melhor que o original não pode ser excluída.

    python tests/test_melhor_versao.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="fotofaxina-melhor-"))
os.environ["FOTOFAXINA_DIR"] = str(TMP / "dados")

from PIL import Image, ImageDraw  # noqa: E402


class GoogleFalso:
    n = 0
    enviados: list = []

    def connect(self, interactive=True):
        pass

    def upload_bytes(self, path, mime):
        GoogleFalso.n += 1
        GoogleFalso.enviados.append(os.path.basename(path))
        return f"t{GoogleFalso.n}"

    def create_album(self, title):
        GoogleFalso.n += 1
        return f"alb{GoogleFalso.n}", None

    def rename_album(self, *a):
        pass

    def batch_create(self, album_id, items):
        return {t: (True, "m" + t) for t, _ in items}


def desenho(w, h):
    im = Image.new("RGB", (w, h), (30, 60, 120))
    d = ImageDraw.Draw(im)
    d.ellipse([w * 0.1, h * 0.1, w * 0.7, h * 0.8], fill=(250, 200, 40))
    d.rectangle([w * 0.5, h * 0.5, w * 0.95, h * 0.95], fill=(20, 160, 80))
    return im


def main():
    hd = TMP / "hd"
    (hd / "WhatsApp").mkdir(parents=True)
    ex = Image.Exif()
    ex[272] = "Celular"
    ex.get_ifd(0x8769)[36867] = datetime(2019, 1, 22, 10, 0).strftime("%Y:%m:%d %H:%M:%S")
    grande = desenho(4000, 2250)
    grande.save(hd / "DCIM_original.jpg", exif=ex, quality=92)
    desenho(1000, 562).save(hd / "WhatsApp" / "IMG-20190122-WA0018.jpg", quality=70)  # versão ruim

    from app import cleanup, db, pipeline
    from app.config import TOKEN_PATH, Config

    pipeline.GooglePhotos = GoogleFalso
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text("{}")
    cfg = Config.load()

    # 1) só a versão ruim está no HD e vai para o Google
    os.rename(hd / "DCIM_original.jpg", TMP / "DCIM_original.jpg")
    pipeline.processar(str(hd), cfg)
    c0 = db.connect()  # sem a IA, imagens do WhatsApp ficam como "outro": o usuário manda enviar
    c0.execute("UPDATE photos SET decision='upload'")
    c0.commit()
    c0.close()
    pipeline.enviar(cfg)
    assert GoogleFalso.enviados == ["IMG-20190122-WA0018.jpg"], GoogleFalso.enviados

    # 2) o original bom volta ao HD (ex.: restaurado da lixeira)
    shutil.move(TMP / "DCIM_original.jpg", hd / "DCIM_original.jpg")
    pipeline.processar(str(hd), cfg)
    conn = db.connect()
    rows = {os.path.basename(r["path"]): r for r in conn.execute("SELECT * FROM photos")}
    bom, ruim = rows["DCIM_original.jpg"], rows["IMG-20190122-WA0018.jpg"]
    assert bom["duplicate_of"] is None, "o original bom não pode ser tratado como cópia"
    assert bom["supersedes"] == ruim["id"], dict(bom)
    GoogleFalso.enviados.clear()
    cfg.upload_categories = list(cfg.upload_categories)
    res = pipeline.enviar(cfg)
    assert GoogleFalso.enviados == ["DCIM_original.jpg"], GoogleFalso.enviados

    # 3) agora que a melhor foi enviada, a pior entra na lista para apagar no Google
    pior = cleanup.worse_sent(conn)
    assert [os.path.basename(r["path"]) for r in pior] == ["IMG-20190122-WA0018.jpg"]
    texto = cleanup.write_report(conn).read_text(encoding="utf-8")
    assert "IMG-20190122-WA0018.jpg" in texto and "DCIM_original.jpg" in texto
    # estável: analisar de novo não muda nada
    pipeline.processar(str(hd), cfg)
    assert len(cleanup.worse_sent(conn)) == 1
    # "Já apaguei no Google": limpa a lista; a pior vira cópia da melhor na próxima análise
    assert cleanup.clear_google_pending(conn) >= 1
    pipeline.processar(str(hd), cfg)
    rows = {os.path.basename(r["path"]): r for r in conn.execute("SELECT * FROM photos")}
    assert rows["IMG-20190122-WA0018.jpg"]["duplicate_of"] == rows["DCIM_original.jpg"]["id"]
    assert not cleanup.worse_sent(conn)

    # 4) guarda: uma "cópia" claramente melhor que o original mantido não é excluída
    cid = rows["DCIM_original.jpg"]["id"]
    conn.execute("UPDATE photos SET duplicate_of=? WHERE id=?", (rows["IMG-20190122-WA0018.jpg"]["id"], cid))
    conn.execute("UPDATE photos SET duplicate_of=NULL WHERE id=?", (rows["IMG-20190122-WA0018.jpg"]["id"],))
    conn.commit()
    cleanup.mark(conn, [cid])
    r = cleanup.trash_marked(conn, trasher=lambda p: (_ for _ in ()).throw(AssertionError("não podia excluir")))
    assert r["lixeira"] == 0 and len(r["falhas"]) == 1, r
    assert (hd / "DCIM_original.jpg").exists()
    conn.close()
    print("OK: original melhor é enviado; a versão pior vai para a lista do Google; cópia melhor não é excluída.")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
