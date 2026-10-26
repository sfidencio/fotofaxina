"""Álbuns do Google Fotos criados pelo FotoFaxina:

- depois de limpar o histórico, o álbum com o mesmo nome é reaproveitado (sem "parte 2");
- criar um álbum novo pelo app e escolher para onde vão as fotos (inclusive mover já enviadas);
- juntar álbuns;
- álbum cheio (limite do Google) continua sozinho em "Título (2)";
- login de versão antiga (sem a permissão de leitura): o envio continua funcionando.

    python tests/test_albuns_google.py
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
TMP = Path(tempfile.mkdtemp(prefix="fotofaxina-albuns-"))
os.environ["FOTOFAXINA_DIR"] = str(TMP / "dados")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw  # noqa: E402

from app import albums, db, google_photos, pipeline  # noqa: E402
from app.config import TOKEN_PATH, Config  # noqa: E402

_APP = None


class GoogleFalso:
    """Google Fotos de mentira que guarda álbuns e itens, como a API real (só o que o app criou)."""
    albums: dict = {}
    media: set = set()
    n = 0
    sem_permissao = False

    @classmethod
    def zera(cls):
        cls.albums, cls.media, cls.n, cls.sem_permissao = {}, set(), 0, False

    def connect(self, interactive=True):
        pass

    def upload_bytes(self, path, mime):
        GoogleFalso.n += 1
        return f"t{GoogleFalso.n}"

    def create_album(self, title):
        GoogleFalso.n += 1
        aid = f"alb{GoogleFalso.n}"
        GoogleFalso.albums[aid] = {"title": title, "items": []}
        return aid, f"https://photos.google.com/lr/album/{aid}"

    def rename_album(self, aid, title):
        GoogleFalso.albums[aid]["title"] = title

    def batch_create(self, aid, items):
        out = {}
        for tok, _name in items:
            mid = "m" + tok
            GoogleFalso.media.add(mid)
            GoogleFalso.albums[aid]["items"].append(mid)
            out[tok] = (True, mid)
        return out

    def list_albums(self):
        if GoogleFalso.sem_permissao:
            raise google_photos.NeedsReconnect("reconecte")
        return [{"id": k, "title": v["title"], "productUrl": None, "mediaItemsCount": len(v["items"])}
                for k, v in GoogleFalso.albums.items()]

    def album_items(self, aid):
        return list(GoogleFalso.albums[aid]["items"])

    def add_to_album(self, aid, ids):
        assert all(m in GoogleFalso.media for m in ids), "só itens criados pelo app"
        for m in ids:
            if m not in GoogleFalso.albums[aid]["items"]:
                GoogleFalso.albums[aid]["items"].append(m)

    def remove_from_album(self, aid, ids):
        GoogleFalso.albums[aid]["items"] = [m for m in GoogleFalso.albums[aid]["items"] if m not in ids]


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


SEED = [1000]


def fotos(pasta, n, inicio):
    for i in range(n):
        SEED[0] += 1
        foto(TMP / pasta / f"{pasta}_{i}.jpg", SEED[0], inicio + timedelta(days=i))
    return str(TMP / pasta)


def reset():
    conn = db.connect()
    db.forget_all(conn)
    conn.execute("DELETE FROM ignored_albums")
    conn.commit()
    conn.close()
    GoogleFalso.zera()


def cfg_ano():
    cfg = Config.load()
    cfg.album_mode, cfg.use_ai, cfg.reuse_same_name = "ano", False, True
    return cfg


def no_google(titulo):
    return [a for a in GoogleFalso.albums.values() if a["title"] == titulo]


# ------------------------------------------------------------------ casos
def mesmo_nome_depois_de_limpar():
    reset()
    cfg = cfg_ano()
    pipeline.processar(fotos("p1", 5, datetime(2023, 3, 1)), cfg)
    pipeline.enviar(cfg)
    conn = db.connect()
    db.forget_all(conn)  # o usuário limpa o histórico
    conn.close()
    pipeline.processar(fotos("p2", 4, datetime(2023, 9, 1)), cfg)
    pipeline.enviar(cfg)
    alb = no_google("Fotos 2023")
    assert len(alb) == 1, f"criou outro “Fotos 2023”: {GoogleFalso.albums}"
    assert len(alb[0]["items"]) == 9


def opcao_desligada_cria_outro():
    reset()
    cfg = cfg_ano()
    pipeline.processar(fotos("q1", 2, datetime(2019, 1, 1)), cfg)
    pipeline.enviar(cfg)
    conn = db.connect()
    db.forget_all(conn)
    conn.close()
    cfg.reuse_same_name = False
    pipeline.processar(fotos("q2", 2, datetime(2019, 6, 1)), cfg)
    pipeline.enviar(cfg)
    assert len(no_google("Fotos 2019")) == 2


def criar_escolher_e_mover():
    reset()
    cfg = cfg_ano()
    pasta = fotos("viagem", 5, datetime(2022, 7, 1))
    pipeline.processar(pasta, cfg)
    pipeline.enviar(cfg)  # tudo em "Fotos 2022"
    novas = fotos("viagem2", 3, datetime(2022, 7, 20))
    pipeline.processar(novas, cfg)

    key = pipeline.criar_album("Viagem 2022")  # criado na hora e já na lista
    assert no_google("Viagem 2022") and key.startswith("g-")
    conn = db.connect()
    assert any(r["key"] == key for r in albums.google_albums(conn))
    ids_novas = db.ids_under(conn, novas)
    ja_enviada = db.ids_under(conn, pasta)[0]
    a_enviar, a_mover = albums.pin(conn, ids_novas + [ja_enviada], key)
    conn.close()
    assert (a_enviar, a_mover) == (3, 1)

    pipeline.enviar(cfg)
    viagem, ano = no_google("Viagem 2022")[0], no_google("Fotos 2022")[0]
    assert len(viagem["items"]) == 4, viagem   # 3 novas + 1 movida
    assert len(ano["items"]) == 4, ano          # 5 - 1 movida
    conn = db.connect()
    assert conn.execute("SELECT album_key FROM photos WHERE id=?", (ja_enviada,)).fetchone()[0] == key
    conn.close()
    pipeline.processar(novas, cfg)  # reanalisar não desfaz a escolha
    pipeline.enviar(cfg)
    assert len(no_google("Viagem 2022")[0]["items"]) == 4


def juntar_albuns():
    reset()
    cfg = Config.load()
    cfg.album_mode, cfg.use_ai = "mes", False
    pipeline.processar(fotos("jun", 3, datetime(2020, 6, 1)), cfg)
    pipeline.processar(fotos("jul", 2, datetime(2020, 7, 1)), cfg)
    pipeline.enviar(cfg)
    conn = db.connect()
    keys = {r["title"]: r["key"] for r in conn.execute("SELECT key, title FROM albums WHERE google_id IS NOT NULL")}
    conn.close()
    res = pipeline.juntar_albuns(keys["Junho de 2020"], [keys["Julho de 2020"]])
    assert res["movidas"] == 2 and [t for t, _u in res["vazios"]] == ["Julho de 2020"], res
    assert len(no_google("Junho de 2020")[0]["items"]) == 5
    assert no_google("Julho de 2020")[0]["items"] == []
    pipeline.buscar_albuns()  # o álbum vazio não volta para a lista
    conn = db.connect()
    titulos = [r["title"] for r in albums.google_albums(conn)]
    conn.close()
    assert "Julho de 2020" not in titulos, titulos


def album_cheio_continua():
    reset()
    cfg = cfg_ano()
    orig = pipeline.ALBUM_LIMIT
    pipeline.ALBUM_LIMIT = 3
    try:
        pipeline.processar(fotos("cheio", 7, datetime(2021, 2, 1)), cfg)
        pipeline.enviar(cfg)
    finally:
        pipeline.ALBUM_LIMIT = orig
    tam = {v["title"]: len(v["items"]) for v in GoogleFalso.albums.values()}
    assert tam == {"Fotos 2021": 3, "Fotos 2021 (2)": 3, "Fotos 2021 (3)": 1}, tam


def login_antigo_continua_enviando():
    reset()
    cfg = cfg_ano()
    GoogleFalso.sem_permissao = True
    logs = []
    pipeline.processar(fotos("antigo", 2, datetime(2018, 1, 1)), cfg)
    res = pipeline.enviar(cfg, log=logs.append)
    assert res["enviados_agora"] == 2, res
    assert any("reconecte" in str(m) for m in logs), logs


def login_antigo_mantem_permissoes():
    from google.oauth2.credentials import Credentials

    antigas = google_photos.SCOPES[:2]
    creds = Credentials(token="t", refresh_token="r", client_id="c", client_secret="s",
                        token_uri="https://oauth2.googleapis.com/token", scopes=antigas)
    google_photos.save_credentials(creds)
    # pedir a permissão nova ao renovar faria o Google recusar e o envio parar
    assert list(google_photos.load_credentials().scopes) == antigas
    TOKEN_PATH.write_text("{}")


def telas():
    from PySide6.QtWidgets import QApplication

    from app.gui.tabs import AlbumPicker, AlbunsTab

    global _APP
    _APP = QApplication.instance() or QApplication([])  # guardar a referência: sem ela o Qt pode cair
    reset()
    cfg = cfg_ano()
    pipeline.processar(fotos("tela", 2, datetime(2017, 1, 1)), cfg)
    pipeline.enviar(cfg)
    pipeline.buscar_albuns()
    tab = AlbunsTab()
    tab.reload()
    titulos = [tab.table.item(r, 0).text() for r in range(tab.table.rowCount())]
    assert titulos.count("Fotos 2017") == 1, titulos  # não aparece duas vezes
    dlg = AlbumPicker()
    assert dlg.list.count() == 1 and dlg.selected_key()
    dlg.deleteLater()
    tab.deleteLater()
    _APP.processEvents()


def main():
    pipeline.GooglePhotos = GoogleFalso
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text("{}")
    casos = [mesmo_nome_depois_de_limpar, opcao_desligada_cria_outro, criar_escolher_e_mover, juntar_albuns,
             album_cheio_continua, login_antigo_continua_enviando, login_antigo_mantem_permissoes, telas]
    falhas = 0
    for caso in casos:
        try:
            caso()
            print(f"ok    {caso.__name__}")
        except Exception as e:
            import traceback

            falhas += 1
            print(f"FALHA {caso.__name__}: {e!r}")
            traceback.print_exc()
            if os.environ.get("GITHUB_ACTIONS"):
                onde = traceback.extract_tb(e.__traceback__)[-1]
                print(f"::error title={caso.__name__}::{e!r} em {Path(onde.filename).name}:{onde.lineno}")
    if falhas:
        raise SystemExit(f"{falhas} caso(s) falharam")
    print(f"OK: {len(casos)} casos de álbuns do Google Fotos.")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
