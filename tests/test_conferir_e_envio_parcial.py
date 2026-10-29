"""- Conferir com o Google Fotos: depois de limpar o histórico, descobre o que já foi enviado e deixa
  só as fotos que deram erro para enviar (sem reenviar as outras);
- o nome de cada arquivo que falhar vai para o log;
- enviar só um álbum (ex.: um ano) ou só uma pasta;
- analisar ao plugar o HD vem desligado (e é desligado uma vez em configurações antigas).

    python tests/test_conferir_e_envio_parcial.py
"""
import json
import os
import random
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="fotofaxina-conferir-"))
os.environ["FOTOFAXINA_DIR"] = str(TMP / "dados")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw  # noqa: E402

from app import db, pipeline  # noqa: E402
from app.config import CONFIG_PATH, TOKEN_PATH, Config  # noqa: E402

_APP = None


class GoogleFalso:
    """Guarda o que foi enviado com nome, dimensões e data, como a API real."""
    albums: dict = {}
    items: dict = {}
    pend: dict = {}
    falhar: set = set()
    n = 0

    @classmethod
    def zera(cls):
        cls.albums, cls.items, cls.pend, cls.falhar, cls.n = {}, {}, {}, set(), 0

    def connect(self, interactive=True):
        pass

    def upload_bytes(self, path, mime):
        GoogleFalso.n += 1
        tok = f"t{GoogleFalso.n}"
        with Image.open(path) as im:
            w, h = im.size
            raw = im.getexif().get_ifd(0x8769).get(36867)
        dt = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S").astimezone(timezone.utc)
        GoogleFalso.pend[tok] = {"width": w, "height": h,
                                 "creationTime": dt.strftime("%Y-%m-%dT%H:%M:%SZ")}
        return tok

    def create_album(self, title):
        GoogleFalso.n += 1
        aid = f"alb{GoogleFalso.n}"
        GoogleFalso.albums[aid] = {"title": title, "items": []}
        return aid, None

    def rename_album(self, *a):
        pass

    def batch_create(self, aid, pairs):
        out = {}
        for tok, name in pairs:
            if name in GoogleFalso.falhar:
                out[tok] = (False, "Erro interno do Google")
                continue
            mid = "m" + tok
            GoogleFalso.items[mid] = {"id": mid, "filename": name, **GoogleFalso.pend[tok]}
            GoogleFalso.albums[aid]["items"].append(mid)
            out[tok] = (True, mid)
        return out

    def list_albums(self):
        return [{"id": k, "title": v["title"], "productUrl": None, "mediaItemsCount": len(v["items"])}
                for k, v in GoogleFalso.albums.items()]

    def album_items(self, aid):
        return list(GoogleFalso.albums[aid]["items"])

    def list_media_items(self):
        return [dict(v) for v in GoogleFalso.items.values()]

    def add_to_album(self, aid, ids):
        GoogleFalso.albums[aid]["items"].extend(ids)

    def remove_from_album(self, aid, ids):
        GoogleFalso.albums[aid]["items"] = [m for m in GoogleFalso.albums[aid]["items"] if m not in ids]


def foto(path, seed, dt, size=(900, 700)):
    rnd = random.Random(seed)
    im = Image.new("RGB", size, tuple(rnd.randint(0, 255) for _ in range(3)))
    d = ImageDraw.Draw(im)
    for _ in range(10):
        x, y = rnd.randint(0, size[0] - 100), rnd.randint(0, size[1] - 100)
        d.rectangle([x, y, x + 90, y + 90], fill=tuple(rnd.randint(0, 255) for _ in range(3)))
    ex = Image.Exif()
    ex[271], ex[272] = "Samsung", "S21"
    ex.get_ifd(0x8769)[36867] = dt.strftime("%Y:%m:%d %H:%M:%S")
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, exif=ex)


def reset():
    conn = db.connect()
    db.forget_all(conn)
    conn.execute("DELETE FROM ignored_albums")
    conn.commit()
    conn.close()
    GoogleFalso.zera()


def cfg_ano():
    cfg = Config.load()
    cfg.album_mode, cfg.use_ai = "ano", False
    return cfg


# ------------------------------------------------------------------ casos
def conferir_depois_de_limpar():
    reset()
    cfg = cfg_ano()
    hd = TMP / "hd1"
    for i in range(8):
        foto(hd / f"IMG_{i:04d}.jpg", i, datetime(2023, 4, 1, 10) + timedelta(days=i))
    GoogleFalso.falhar = {"IMG_0003.jpg", "IMG_0006.jpg"}
    pipeline.processar(str(hd), cfg)
    logs = []
    res = pipeline.enviar(cfg, log=logs.append)
    assert res["enviados_agora"] == 6 and res["erros_agora"] == 2, res
    nao = [m for m in logs if str(m).startswith("Não enviada")]
    assert len(nao) == 2 and any("IMG_0003.jpg" in m for m in nao), nao  # nomes no log

    conn = db.connect()  # o usuário limpa o histórico (com os 2 erros pendentes)
    db.forget_all(conn)
    conn.close()
    GoogleFalso.falhar = set()

    r = pipeline.conferir(str(hd), cfg)
    assert r["marcadas"] == 6, r
    assert r["pasta"]["a_enviar"] == 2 and r["pasta"]["ja_no_google"] == 6, r["pasta"]
    res = pipeline.enviar(cfg)
    assert res["enviados_agora"] == 2, res
    assert len(GoogleFalso.items) == 8, "fotos já enviadas subiram de novo"
    assert [a["title"] for a in GoogleFalso.albums.values()] == ["Fotos 2023"], GoogleFalso.albums


def mesmo_nome_outra_foto():
    reset()
    cfg = cfg_ano()
    a, b = TMP / "cam_a", TMP / "cam_b"
    foto(a / "IMG_0001.jpg", 100, datetime(2015, 1, 1), size=(900, 700))
    foto(b / "IMG_0001.jpg", 200, datetime(2019, 6, 1), size=(800, 600))
    pipeline.processar(str(a), cfg)
    pipeline.enviar(cfg)  # só a da câmera A foi enviada
    conn = db.connect()
    db.forget_all(conn)
    conn.close()
    pipeline.processar(str(a), cfg)
    r = pipeline.conferir(str(b), cfg)
    assert r["marcadas"] == 1, r
    conn = db.connect()
    sent = {os.path.dirname(x["path"]): bool(x["media_item_id"]) for x in conn.execute("SELECT * FROM photos")}
    conn.close()
    assert sent == {str(a): True, str(b): False}, sent


def videos_ja_enviados():
    """Vídeo: a data do arquivo no PC é a da cópia; a do Google é a da gravação. Mesmo assim, com
    nome único dos dois lados, é o mesmo vídeo e não pode ser reenviado."""
    reset()
    cfg = cfg_ano()
    pasta = TMP / "videos"
    pasta.mkdir()
    for nome in ("VID_20190101_120000.mp4", "familia.mp4", "repetido.mp4"):
        (pasta / nome).write_bytes(b"\0\0\0\x08mdat" + nome.encode() * 50)
    (TMP / "videos2").mkdir()
    (TMP / "videos2" / "repetido.mp4").write_bytes(b"\0\0\0\x08mdat" + b"outro" * 50)
    pipeline.processar(str(TMP / "videos2"), cfg)
    GoogleFalso.albums["alb1"] = {"title": "Fotos sem data", "items": []}
    for i, nome in enumerate(("VID_20190101_120000.mp4", "familia.mp4", "repetido.mp4")):
        mid = f"v{i}"
        GoogleFalso.items[mid] = {"id": mid, "filename": nome, "width": 1920, "height": 1080,
                                  "creationTime": "2016-03-10T15:00:00Z"}  # gravação antiga
        GoogleFalso.albums["alb1"]["items"].append(mid)
    r = pipeline.conferir(str(pasta), cfg)
    conn = db.connect()
    sent = {os.path.basename(x["path"]) + ("@2" if "videos2" in x["path"] else ""): bool(x["media_item_id"])
            for x in conn.execute("SELECT path, media_item_id FROM photos")}
    conn.close()
    # nomes únicos: reconhecidos; "repetido.mp4" existe 2x no HD e a data não bate: não arrisca
    assert sent == {"VID_20190101_120000.mp4": True, "familia.mp4": True,
                    "repetido.mp4": False, "repetido.mp4@2": False}, sent
    assert r["marcadas"] == 2, r


def enviar_so_um_ano():
    reset()
    cfg = cfg_ano()
    hd = TMP / "anos"
    for i in range(3):
        foto(hd / f"a22_{i}.jpg", 300 + i, datetime(2022, 3, 1) + timedelta(days=i))
        foto(hd / f"a23_{i}.jpg", 400 + i, datetime(2023, 3, 1) + timedelta(days=i))
    pipeline.processar(str(hd), cfg)
    res = pipeline.enviar(cfg, keys=["ano-2023"])
    assert res["enviados_agora"] == 3, res
    assert [a["title"] for a in GoogleFalso.albums.values()] == ["Fotos 2023"]
    assert pipeline.enviar(cfg)["enviados_agora"] == 3  # depois, o resto


def enviar_so_uma_pasta():
    reset()
    cfg = cfg_ano()
    for i in range(2):
        foto(TMP / "pA" / f"pa_{i}.jpg", 500 + i, datetime(2021, 5, 1) + timedelta(days=i))
        foto(TMP / "pB" / f"pb_{i}.jpg", 600 + i, datetime(2021, 6, 1) + timedelta(days=i))
    pipeline.processar(str(TMP / "pA"), cfg)
    pipeline.processar(str(TMP / "pB"), cfg)
    res = pipeline.enviar(cfg, folder=str(TMP / "pA"))
    assert res["enviados_agora"] == 2, res
    assert {v["filename"] for v in GoogleFalso.items.values()} == {"pa_0.jpg", "pa_1.jpg"}


def analise_automatica_desligada():
    antigo = Config.load()
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    data["auto_scan_on_drive"] = True
    data.pop("settings_version", None)  # configuração salva por versão anterior
    CONFIG_PATH.write_text(json.dumps(data), encoding="utf-8")
    cfg = Config.load()
    assert cfg.auto_scan_on_drive is False and cfg.settings_version == 1
    cfg.auto_scan_on_drive = True  # o usuário liga de novo: tem que continuar ligado
    cfg.save()
    assert Config.load().auto_scan_on_drive is True
    antigo.auto_scan_on_drive = False
    antigo.settings_version = 1
    antigo.save()


def hd_plugado_nao_analisa_sozinho():
    from PySide6.QtWidgets import QApplication

    from app.gui.main_window import MainWindow

    global _APP
    _APP = QApplication.instance() or QApplication([])
    cfg = Config.load()
    cfg.welcome_done = True
    win = MainWindow(cfg)
    hd = TMP / "hd-novo"
    hd.mkdir()
    win.on_drive_added(str(hd), "HD novo")
    _APP.processEvents()
    assert win.job is None and win.root != str(hd), "começou a analisar sozinho"
    assert win.inicio.btn_check.isEnabled() and win.inicio.btn_upload_folder.isEnabled()
    win.quitting = True
    win.close()
    win.deleteLater()
    _APP.processEvents()


def main():
    pipeline.GooglePhotos = GoogleFalso
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text("{}")
    casos = [conferir_depois_de_limpar, mesmo_nome_outra_foto, videos_ja_enviados, enviar_so_um_ano, enviar_so_uma_pasta,
             analise_automatica_desligada, hd_plugado_nao_analisa_sozinho]
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
    print(f"OK: {len(casos)} casos (conferir, envio parcial, HD sem análise automática).")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
