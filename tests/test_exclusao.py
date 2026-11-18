"""Limpeza do HD: só o que o usuário marcou (e só meme/print/documento) vai para a lixeira; o que já
estava no Google Fotos entra numa lista para apagar lá (o app não consegue apagar no Google).

    python tests/test_exclusao.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="fotofaxina-exclusao-"))
os.environ["FOTOFAXINA_DIR"] = str(TMP / "dados")

from PIL import Image  # noqa: E402


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


LIXEIRA = TMP / "lixeira"


def lixeira_falsa(path):
    LIXEIRA.mkdir(exist_ok=True)
    shutil.move(path, LIXEIRA / os.path.basename(path))


def main():
    hd = TMP / "hd"
    (hd / "Prints").mkdir(parents=True)
    (hd / "Camera").mkdir()
    for i in range(3):
        ex = Image.Exif()
        ex[272] = "Celular"
        ex.get_ifd(0x8769)[36867] = datetime(2022, 3, 1 + i).strftime("%Y:%m:%d %H:%M:%S")
        Image.new("RGB", (1000, 800), (60 * i, 50, 90)).save(hd / "Camera" / f"IMG_{i}.jpg", exif=ex)
    for i in range(4):  # nomes "Screenshot_" viram "print" pelas regras
        Image.new("RGB", (1080, 2000), (10 * i, 200, 50 * i)).save(hd / "Prints" / f"Screenshot_2022030{i}-101010.png")

    from app import cleanup, db, pipeline
    from app.config import TOKEN_PATH, Config

    pipeline.GooglePhotos = GoogleFalso
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text("{}")
    cfg = Config.load()
    cfg.upload_categories = list(cfg.upload_categories) + ["print"]
    cfg.save()

    pipeline.processar(str(hd), cfg)
    conn = db.connect()
    cat = {os.path.basename(r["path"]): r for r in conn.execute("SELECT * FROM photos")}
    assert all(cat[f"Screenshot_2022030{i}-101010.png"]["category"] == "print" for i in range(4))
    fotos = [cat[f"IMG_{i}.jpg"]["id"] for i in range(3)]
    prints = [cat[f"Screenshot_2022030{i}-101010.png"]["id"] for i in range(4)]

    # só prints 0 e 1 vão para o Google; os outros ficam só no HD
    conn.executemany("UPDATE photos SET decision='skip' WHERE id=?", [(prints[2],), (prints[3],)])
    conn.commit()
    assert pipeline.enviar(cfg)["enviados_agora"] == 5  # 3 fotos + 2 prints

    # fotos pessoais não podem ser marcadas; prints podem
    assert cleanup.mark(conn, fotos) == 0
    assert cleanup.mark(conn, prints[:3]) == 3  # prints 0 e 1 (já enviados) e 2 (só no HD); o 3 não
    assert cleanup.mark(conn, [prints[1]], False) == 1  # desmarcar
    assert cleanup.mark(conn, [prints[1]]) == 1
    pv = cleanup.preview(conn)
    assert pv["n"] == 3 and pv["no_google"] == 2, pv

    # marcada para excluir não é enviada, mesmo sem ter sido enviada antes
    assert db.summary(conn, cfg)["a_excluir"] == 3

    # a categoria mudou depois de marcar: não pode apagar
    conn.execute("UPDATE photos SET category='foto' WHERE id=?", (prints[2],))
    conn.commit()
    assert cleanup.preview(conn)["n"] == 2
    conn.execute("UPDATE photos SET category='print' WHERE id=?", (prints[2],))
    conn.commit()

    # uma falha na lixeira mantém a marca e o registro
    def falha(path):
        if path.endswith("Screenshot_20220302-101010.png"):
            raise OSError("sem permissão")
        lixeira_falsa(path)

    res = cleanup.trash_marked(conn, trasher=falha)
    assert res["lixeira"] == 2 and len(res["falhas"]) == 1, res
    assert res["no_google"] == 2
    assert (hd / "Prints" / "Screenshot_20220302-101010.png").exists()
    assert not (hd / "Prints" / "Screenshot_20220300-101010.png").exists()
    assert not (hd / "Prints" / "Screenshot_20220301-101010.png").exists()
    # o que não foi marcado ficou intacto: fotos e o print 3
    assert all((hd / "Camera" / f"IMG_{i}.jpg").exists() for i in range(3))
    assert (hd / "Prints" / "Screenshot_20220303-101010.png").exists()
    assert conn.execute("SELECT delete_mark FROM photos WHERE id=?", (prints[2],)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM photos WHERE id IN (?,?)", (prints[0], prints[1])).fetchone()[0] == 0

    # lista para apagar no Google: só os dois que já estavam lá
    pend = cleanup.google_pending(conn)
    assert sorted(r["name"] for r in pend) == ["Screenshot_20220300-101010.png", "Screenshot_20220301-101010.png"]
    rel = cleanup.write_report(conn)
    texto = rel.read_text(encoding="utf-8")
    assert "Screenshot_20220300-101010.png" in texto and "Screenshot_20220303" not in texto

    # HD fora do ar: não mexe no registro nem acusa falha
    shutil.move(str(hd / "Prints"), str(TMP / "sumiu"))
    res = cleanup.trash_marked(conn, trasher=lixeira_falsa)
    assert res["lixeira"] == 0 and len(res["nao_encontrados"]) == 1, res
    assert conn.execute("SELECT delete_mark FROM photos WHERE id=?", (prints[2],)).fetchone()[0] == 1
    shutil.move(str(TMP / "sumiu"), str(hd / "Prints"))

    # arquivo alterado depois da análise: não apaga
    with open(hd / "Prints" / "Screenshot_20220302-101010.png", "ab") as fh:
        fh.write(b"x")
    res = cleanup.trash_marked(conn, trasher=lixeira_falsa)
    assert res["lixeira"] == 0 and len(res["falhas"]) == 1, res
    assert (hd / "Prints" / "Screenshot_20220302-101010.png").exists()

    # sem o módulo da lixeira: avisa uma vez, sem tentar arquivo por arquivo
    import builtins
    real = builtins.__import__

    def sem_send2trash(name, *a, **k):
        if name == "send2trash":
            raise ImportError(name)
        return real(name, *a, **k)

    builtins.__import__ = sem_send2trash
    try:
        res = cleanup.trash_marked(conn)
    finally:
        builtins.__import__ = real
    assert res.get("erro") and res["lixeira"] == 0 and not res["falhas"], res

    # "Já apaguei no Google" limpa a lista
    assert cleanup.clear_google_pending(conn) == 2
    assert cleanup.write_report(conn) is None
    conn.close()
    print("OK: só o que foi marcado foi para a lixeira; lista do Google gerada para os itens já enviados.")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
