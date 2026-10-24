"""Baixa o modelo de IA pronto da página de versões do GitHub (para quem roda a partir do código
ou teve o modelo apagado). Grava só em ~/.fotofaxina/models — nada mais é tocado."""
from __future__ import annotations

import io
import shutil
import zipfile

from .config import APP_DIR
from .i18n import _

MODEL_URL = "https://github.com/sfidencio/fotofaxina/releases/latest/download/fotofaxina-ia-modelo.zip"
FILES = ("clip_image.onnx", "clip_text.npy", "clip_labels.json")


def download_model(progress=None, log=None, stop=None) -> bool:
    import requests

    progress = progress or (lambda *a: None)
    log = log or (lambda *a: None)
    stage = _("Baixando modelo de IA")
    log(_("Baixando o modelo de IA (~96 MB)…"))
    with requests.get(MODEL_URL, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length") or 0)
        buf = io.BytesIO()
        done = 0
        for chunk in resp.iter_content(1024 * 256):
            if stop is not None and stop.is_set():
                log(_("Download cancelado."))
                return False
            buf.write(chunk)
            done += len(chunk)
            progress(stage, done // 1024, total // 1024, f"{done / 1e6:.0f} MB")

    tmp = APP_DIR / "models.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    with zipfile.ZipFile(buf) as zf:
        for name in FILES:  # extrai só os arquivos esperados, sem caminhos vindos do zip
            member = next((m for m in zf.namelist() if m.rsplit("/", 1)[-1] == name), None)
            if member is None:
                raise RuntimeError(_("Arquivo do modelo incompleto: falta {nome}.").format(nome=name))
            (tmp / name).write_bytes(zf.read(member))
    dest = APP_DIR / "models"
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)

    from . import classifier

    classifier.reset()
    log(_("Modelo de IA instalado."))
    return True
