"""Correções de robustez — cada função cobre um problema real encontrado na revisão:

- IA ligada/baixada depois reclassifica o que foi decidido sem ela;
- HD desplugado não vira "erro" no envio;
- falha de rede/Google num lote não derruba o envio; internet oscilando é retentada;
- login expirado: token apagado e mensagem clara;
- limpar o histórico no meio de um envio não quebra a tarefa;
- HD com outra letra não é lido inteiro de novo;
- data de gravação de vídeos MP4/MOV;
- login salvo protegido; modelo baixado conferido pela soma de verificação;
- HD plugado durante outra tarefa entra na fila; botões perigosos bloqueados durante tarefas.

    python tests/test_robustez.py
"""
import hashlib
import io
import os
import shutil
import struct
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="fotofaxina-robustez-"))
os.environ["FOTOFAXINA_DIR"] = str(TMP / "dados")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw  # noqa: E402

from app import classifier, db, google_photos, pipeline, scanner  # noqa: E402
from app.config import TOKEN_PATH, Config  # noqa: E402


# ---------------------------------------------------------------- utilidades
def foto(path, seed, camera=True, dt=datetime(2022, 3, 5, 14)):
    import random

    rnd = random.Random(seed)
    im = Image.new("RGB", (1000, 750), tuple(rnd.randint(0, 255) for _ in range(3)))
    d = ImageDraw.Draw(im)
    for _ in range(12):
        x, y = rnd.randint(0, 900), rnd.randint(0, 650)
        d.rectangle([x, y, x + rnd.randint(30, 200), y + rnd.randint(30, 200)],
                    fill=tuple(rnd.randint(0, 255) for _ in range(3)))
    path.parent.mkdir(parents=True, exist_ok=True)
    if camera:
        ex = Image.Exif()
        ex[271], ex[272] = "Samsung", "Galaxy"
        ex.get_ifd(0x8769)[36867] = dt.strftime("%Y:%m:%d %H:%M:%S")
        im.save(path, exif=ex)
    else:
        im.save(path)


class GoogleFalso:
    """Google Fotos de mentira. falhar_lotes: quantos batchCreate devem falhar com erro do Google."""
    n = 0
    falhar_lotes = 0
    ao_enviar = None

    def connect(self, interactive=True):
        pass

    def upload_bytes(self, path, mime):
        if GoogleFalso.ao_enviar:
            f, GoogleFalso.ao_enviar = GoogleFalso.ao_enviar, None
            f()
        GoogleFalso.n += 1
        return f"t{GoogleFalso.n}"

    def create_album(self, title):
        GoogleFalso.n += 1
        return f"alb{GoogleFalso.n}", None

    def rename_album(self, *a):
        pass

    def batch_create(self, album_id, items):
        if GoogleFalso.falhar_lotes:
            GoogleFalso.falhar_lotes -= 1
            raise google_photos.GooglePhotosError("Falha após várias tentativas (503): backend error")
        return {t: (True, "m" + t) for t, _ in items}


def reset():
    """Começa cada caso com banco vazio."""
    conn = db.connect()
    db.forget_all(conn)
    conn.close()
    GoogleFalso.falhar_lotes = 0
    GoogleFalso.ao_enviar = None


def cfg_base():
    cfg = Config.load()
    cfg.use_ai = False
    cfg.album_mode = "mes"
    return cfg


# ---------------------------------------------------------------- casos
def ia_depois_reclassifica():
    reset()
    hd = TMP / "ia"
    foto(hd / "WhatsApp Images" / "IMG-20220305-WA0001.jpg", 1, camera=False)
    foto(hd / "WhatsApp Images" / "IMG-20220305-WA0002.jpg", 2, camera=False)
    cfg = cfg_base()
    cfg.use_ai = True  # IA ligada, mas o modelo ainda não foi baixado
    orig = classifier.ai_available, classifier.get_clip
    try:
        classifier.ai_available = lambda: False
        classifier.get_clip = lambda log: None
        pipeline.processar(str(hd), cfg)
        conn = db.connect()
        cats = {r["category"] for r in conn.execute("SELECT category FROM photos")}
        # simula registro de versão antiga (gravava "regra" em vez de "sem_ia")
        conn.execute("UPDATE photos SET category_by='regra' WHERE path LIKE '%WA0002%'")
        conn.commit()
        conn.close()
        assert cats == {"outro"}, cats

        class ClipFalso:
            def classify(self, paths):
                return [("foto", 0.92) for _ in paths]

        classifier.ai_available = lambda: True  # modelo baixado
        classifier.get_clip = lambda log: ClipFalso()
        res = pipeline.processar(str(hd), cfg)  # nenhum arquivo mudou no disco
    finally:
        classifier.ai_available, classifier.get_clip = orig
    conn = db.connect()
    rows = conn.execute("SELECT category, category_by FROM photos").fetchall()
    conn.close()
    assert all(r["category"] == "foto" and r["category_by"] == "ia" for r in rows), [tuple(r) for r in rows]
    assert res["pasta"]["a_enviar"] == 2, res["pasta"]


def hd_desplugado_nao_vira_erro():
    reset()
    a, b = TMP / "hdA", TMP / "hdB"
    for i in range(3):
        foto(a / f"A_{i}.jpg", 10 + i)
        foto(b / f"B_{i}.jpg", 20 + i)
    cfg = cfg_base()
    pipeline.processar(str(a), cfg)
    pipeline.processar(str(b), cfg)
    conn = db.connect()  # erro gravado por versão antiga para um arquivo do HD A
    conn.execute("UPDATE photos SET status='error', error='Arquivo indisponível (HD desconectado?)' "
                 "WHERE path LIKE '%A_0.jpg'")
    conn.commit()
    conn.close()
    a.rename(TMP / "hdA-guardado")  # HD A desplugado
    res = pipeline.enviar(cfg)
    assert res["enviados_agora"] == 3 and res["erros_agora"] == 0, res
    assert res["ausentes_agora"] == 3, res
    conn = db.connect()
    st = {r["status"] for r in conn.execute("SELECT status FROM photos WHERE path LIKE '%A\\_%' ESCAPE '\\'")}
    conn.close()
    assert st == {"classified"}, st  # continuam na fila, sem erro
    (TMP / "hdA-guardado").rename(a)  # plugou de novo
    res = pipeline.enviar(cfg)
    assert res["enviados_agora"] == 3 and res["ausentes_agora"] == 0, res


def falha_num_lote_nao_derruba_envio():
    reset()
    hd = TMP / "lotes"
    for m in range(1, 4):  # 3 meses = 3 álbuns = 3 lotes
        for i in range(2):
            foto(hd / f"{m}_{i}.jpg", 100 * m + i, dt=datetime(2021, m, 10, 12, i))
    cfg = cfg_base()
    pipeline.processar(str(hd), cfg)
    GoogleFalso.falhar_lotes = 1
    res = pipeline.enviar(cfg)
    assert res["enviados_agora"] == 4 and res["erros_agora"] == 2, res
    assert pipeline.tentar_erros_novamente() == 2
    assert pipeline.enviar(cfg)["enviados_agora"] == 2


def internet_oscilando_e_login_expirado():
    import requests
    from google.auth.exceptions import RefreshError

    class Resp:
        status_code, text = 200, "token-ok"

    chamadas = []

    class Sessao:
        def request(self, method, url, **kw):
            chamadas.append(url)
            if len(chamadas) <= 2:
                raise requests.ConnectionError("rede caiu")
            return Resp()

    orig_sleep = google_photos.time.sleep
    google_photos.time.sleep = lambda s: None
    try:
        gp = google_photos.GooglePhotos()
        gp.session = Sessao()
        assert gp._request("GET", "https://x") .text == "token-ok" and len(chamadas) == 3

        class SessaoExpirada:
            def request(self, *a, **k):
                raise RefreshError("invalid_grant: Token has been expired or revoked.")

        TOKEN_PATH.write_text("{}")
        gp.session = SessaoExpirada()
        try:
            gp._request("GET", "https://x")
            raise AssertionError("deveria avisar que o login expirou")
        except google_photos.NotConnected as e:
            assert "7" in str(e)
        assert not TOKEN_PATH.exists(), "o token expirado deveria ser apagado (a tela dizia 'conectada')"
    finally:
        google_photos.time.sleep = orig_sleep
        TOKEN_PATH.write_text("{}")


def limpar_historico_durante_envio():
    reset()
    hd = TMP / "limpar"
    for m in (1, 2):
        foto(hd / f"L{m}.jpg", 300 + m, dt=datetime(2020, m, 1, 9))
    cfg = cfg_base()
    pipeline.processar(str(hd), cfg)

    def limpa():
        conn = db.connect()
        db.forget_all(conn)
        conn.close()

    GoogleFalso.ao_enviar = limpa  # usuário clica "Limpar todo o histórico" no meio do envio
    pipeline.enviar(cfg)  # não pode quebrar


def hd_com_outra_letra_nao_le_tudo_de_novo():
    reset()
    e = TMP / "E" / "Fotos"
    for i in range(4):
        foto(e / f"IMG_{i}.jpg", 400 + i)
    cfg = cfg_base()
    pipeline.processar(str(TMP / "E"), cfg)
    pipeline.enviar(cfg)
    shutil.move(str(TMP / "E"), str(TMP / "F"))  # o Windows montou o HD como F:
    lidos = []
    orig = scanner.sha256_of
    scanner.sha256_of = lambda p: lidos.append(p) or orig(p)
    try:
        res = pipeline.processar(str(TMP / "F"), cfg)
    finally:
        scanner.sha256_of = orig
    assert not lidos, f"{len(lidos)} arquivos foram lidos inteiros de novo"
    assert res["pasta"]["ja_no_google"] == 4, res["pasta"]
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 4
    conn.close()


def data_de_video():
    def box(kind, payload):
        return struct.pack(">I4s", 8 + len(payload), kind) + payload

    quando = datetime(2021, 5, 2, 15, 30, 0)
    ts = int(quando.timestamp()) + scanner.MP4_EPOCH
    for versao, campo in ((0, struct.pack(">II", ts, ts)), (1, struct.pack(">QQ", ts, ts))):
        mvhd = box(b"mvhd", bytes([versao, 0, 0, 0]) + campo + b"\0" * 80)
        dados = box(b"ftyp", b"qt  \0\0\0\0qt  ") + box(b"mdat", b"\0" * 5000) + box(b"moov", mvhd)
        p = TMP / f"IMG_1234_v{versao}.MOV"
        p.write_bytes(dados)
        info = scanner.analyze(str(p), os.stat(p))
        assert info["date_source"] == "video", info
        assert info["taken_at"] == quando.isoformat(timespec="seconds"), info["taken_at"]
    lixo = TMP / "quebrado.mp4"
    lixo.write_bytes(b"\0\0\0\x02xx")
    assert scanner.video_created(str(lixo)) is None


def login_protegido():
    from google.oauth2.credentials import Credentials

    from app import secure_store

    dado = b'{"refresh_token": "segredo"}'
    assert secure_store.unprotect(secure_store.protect(dado)) == dado
    creds = Credentials(token="t", refresh_token="r-123", client_id="c", client_secret="s",
                        token_uri="https://oauth2.googleapis.com/token", scopes=google_photos.SCOPES)
    google_photos.save_credentials(creds)
    if sys.platform == "win32":
        assert b"r-123" not in TOKEN_PATH.read_bytes(), "o login ficou legível no arquivo"
    else:
        assert (TOKEN_PATH.stat().st_mode & 0o077) == 0, "o arquivo do login pode ser lido por outros"
    assert google_photos.load_credentials().refresh_token == "r-123"
    TOKEN_PATH.write_text(creds.to_json())  # token em texto de versão antiga continua funcionando
    assert google_photos.load_credentials().refresh_token == "r-123"
    if sys.platform == "win32":
        assert secure_store.is_protected(TOKEN_PATH.read_bytes()), "token antigo não foi protegido"
    TOKEN_PATH.write_text("{}")


def modelo_conferido():
    from app import model_download

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in model_download.FILES:
            zf.writestr(f"models/{name}", b"conteudo " + name.encode())
    zbytes = buf.getvalue()

    class R:
        def __init__(self, status, body):
            self.status_code, self.body = status, body
            self.headers = {"content-length": str(len(body))}
            self.text = body.decode("latin-1")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, n):
            yield self.body

    import requests

    soma = {"valor": hashlib.sha256(zbytes).hexdigest()}
    orig = requests.get
    requests.get = lambda url, **k: (R(200, f"{soma['valor']}  fotofaxina-ia-modelo.zip\n".encode())
                                     if url.endswith("SHA256SUMS.txt") else R(200, zbytes))
    try:
        assert model_download.download_model() is True
        soma["valor"] = "0" * 64
        try:
            model_download.download_model()
            raise AssertionError("modelo corrompido foi aceito")
        except RuntimeError as e:
            assert "corrompido" in str(e) or "corrupted" in str(e)
    finally:
        requests.get = orig
        shutil.rmtree(TMP / "dados" / "models", ignore_errors=True)
        classifier.reset()


def migracao_uma_vez():
    conn = db.connect()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(photos)")}
    conn.close()
    assert "not_duplicate" in cols


def janela_fila_de_hd_e_botoes():
    from PySide6.QtWidgets import QApplication

    from app.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    cfg = Config.load()
    cfg.welcome_done = True
    cfg.auto_scan_on_drive = True
    win = MainWindow(cfg)
    hd = TMP / "hd-fila"
    hd.mkdir()

    class TarefaFalsa:
        pass

    win.job = TarefaFalsa()
    win._set_busy(True)
    assert not win.revisao.btn_forget.isEnabled(), "“Esquecer selecionadas” ativo durante a tarefa"
    assert not any(b.isEnabled() for b in win.config_tab._busy_buttons), "“Limpar histórico” ativo"
    win.on_drive_added(str(hd), "HD da fila")
    assert win.pending_drive == (str(hd), "HD da fila")
    win._clear_job()  # tarefa anterior terminou
    for _ in range(20):
        app.processEvents()
    assert win.root == str(hd), "o HD que estava na fila não foi analisado"
    win.pool.waitForDone(10000)
    app.processEvents()
    win.quitting = True
    win.close()


def main():
    pipeline.GooglePhotos = GoogleFalso
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text("{}")
    casos = [ia_depois_reclassifica, hd_desplugado_nao_vira_erro, falha_num_lote_nao_derruba_envio,
             internet_oscilando_e_login_expirado, limpar_historico_durante_envio,
             hd_com_outra_letra_nao_le_tudo_de_novo, data_de_video, login_protegido, modelo_conferido,
             migracao_uma_vez, janela_fila_de_hd_e_botoes]
    falhas = 0
    for caso in casos:
        try:
            caso()
            print(f"ok    {caso.__name__}")
        except Exception as e:  # mostra todos os casos, não só o primeiro que falhar
            import traceback

            falhas += 1
            print(f"FALHA {caso.__name__}: {e!r}")
            traceback.print_exc()
            if os.environ.get("GITHUB_ACTIONS"):  # aparece no resumo do Actions
                onde = traceback.extract_tb(e.__traceback__)[-1]
                print(f"::error title={caso.__name__}::{e!r} em {Path(onde.filename).name}:{onde.lineno}")
    if falhas:
        raise SystemExit(f"{falhas} caso(s) falharam")
    print(f"OK: {len(casos)} casos de robustez.")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
