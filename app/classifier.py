"""Classificação: regras rápidas primeiro, IA leve (CLIP em ONNX) só para o que sobrar.

A IA roda com o ONNX Runtime (~15 MB) em vez do PyTorch (~2 GB). As frases de cada
categoria já vêm convertidas em vetores (models/clip_text.npy), então em tempo de uso
só a parte de imagem do modelo é executada, na CPU, sem placa de vídeo.
"""
from __future__ import annotations

import json
import os

import numpy as np
from PIL import Image, ImageOps

from . import db
from .ai_prompts import IMAGE_SIZE, MEAN, STD
from .config import APP_DIR, resource
from .i18n import _

MODEL_FILES = ("clip_image.onnx", "clip_text.npy", "clip_labels.json")


def model_dir():
    """Modelo embutido no instalador, na pasta do projeto ou na pasta de dados do usuário."""
    for d in (resource("models"), APP_DIR / "models"):
        if all((d / f).exists() for f in MODEL_FILES):
            return d
    return None


def runtime_installed() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def ai_available() -> bool:
    return runtime_installed() and model_dir() is not None


def rule_based(r, cfg) -> tuple[str | None, float]:
    """Retorna (categoria, confiança) ou (None, 0) quando precisa da IA."""
    if r["is_video"]:
        return "video", 0.9
    if r["source"] == "print":
        return "print", 0.95
    w, h = r["width"] or 0, r["height"] or 0
    if w and h and min(w, h) < cfg.min_image_side:
        return "outro", 0.8
    ext = os.path.splitext(r["path"])[1].lower()
    if ext == ".gif":
        return "meme", 0.7
    if ext == ".webp" and r["source"] == "whatsapp":
        return "meme", 0.85  # figurinhas do WhatsApp
    if ext == ".png" and not r["camera"] and w and h and max(w, h) / min(w, h) >= 1.9:
        return "print", 0.8
    return None, 0.0


def fallback(r) -> tuple[str, float]:
    """Sem IA: câmera vira foto, o resto fica para revisão."""
    if r["source"] == "camera":
        return "foto", 0.6
    return "outro", 0.3


def load_for_ai(path: str) -> Image.Image | None:
    """Abre já reduzida (JPEG decodifica em escala menor: bem mais rápido)."""
    try:
        with Image.open(path) as im:
            im.draft("RGB", (IMAGE_SIZE * 2, IMAGE_SIZE * 2))
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.load()
            return im
    except Exception:
        return None


def preprocess(im: Image.Image) -> np.ndarray:
    """Mesmo pré-processamento do CLIP: lado menor = 224, recorte central, normalização."""
    # mesmas contas do CLIPImageProcessor (transformers): lado maior truncado, recorte com //
    w, h = im.size
    if w <= h:
        new_w, new_h = IMAGE_SIZE, int(IMAGE_SIZE * h / w)
    else:
        new_w, new_h = int(IMAGE_SIZE * w / h), IMAGE_SIZE
    im = im.resize((new_w, new_h), Image.Resampling.BICUBIC)
    left, top = (new_w - IMAGE_SIZE) // 2, (new_h - IMAGE_SIZE) // 2
    im = im.crop((left, top, left + IMAGE_SIZE, top + IMAGE_SIZE))
    arr = np.asarray(im, dtype=np.float32) / 255.0
    arr = (arr - np.array(MEAN, dtype=np.float32)) / np.array(STD, dtype=np.float32)
    return arr.transpose(2, 0, 1)  # HWC -> CHW


class OnnxClip:
    def __init__(self, directory):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, (os.cpu_count() or 2) // 2)  # deixa a máquina usável
        self.session = ort.InferenceSession(
            str(directory / "clip_image.onnx"), opts, providers=["CPUExecutionProvider"]
        )
        meta = json.loads((directory / "clip_labels.json").read_text(encoding="utf-8"))
        self.labels: list[str] = meta["labels"]
        self.logit_scale = float(meta.get("logit_scale", 100.0))
        self.text = np.load(directory / "clip_text.npy").astype(np.float32)
        self.input_name = self.session.get_inputs()[0].name

    def embed(self, images: list[Image.Image]) -> np.ndarray:
        batch = np.stack([preprocess(im) for im in images]).astype(np.float32)
        emb = self.session.run(None, {self.input_name: batch})[0]
        return emb / np.linalg.norm(emb, axis=-1, keepdims=True)

    def scores(self, emb: np.ndarray) -> list[dict[str, float]]:
        logits = self.logit_scale * emb @ self.text.T
        logits -= logits.max(axis=-1, keepdims=True)
        probs = np.exp(logits)
        probs /= probs.sum(axis=-1, keepdims=True)
        out = []
        for row in probs:
            per_cat: dict[str, float] = {}
            for label, p in zip(self.labels, row):
                per_cat[label] = per_cat.get(label, 0.0) + float(p)
            out.append(per_cat)
        return out

    def classify(self, paths: list[str]) -> list[tuple[str, float] | None]:
        images, idx = [], []
        for i, p in enumerate(paths):
            im = load_for_ai(p)
            if im is not None:
                images.append(im)
                idx.append(i)
        out: list[tuple[str, float] | None] = [None] * len(paths)
        if not images:
            return out
        for i, per_cat in zip(idx, self.scores(self.embed(images))):
            cat = max(per_cat, key=per_cat.get)
            out[i] = (cat, per_cat[cat])
        return out


_clip: OnnxClip | None = None
_clip_error: str | None = None


def reset() -> None:
    """Esquece o modelo carregado (ex.: depois de baixar um novo)."""
    global _clip, _clip_error
    _clip = None
    _clip_error = None


def get_clip(log) -> OnnxClip | None:
    global _clip, _clip_error
    if _clip is not None or _clip_error is not None:
        return _clip
    d = model_dir()
    if d is None:
        _clip_error = _("Modelo de IA não encontrado. Usando só as regras.")
        log(_clip_error)
        return None
    try:
        _clip = OnnxClip(d)
        log(_("IA leve carregada."))
    except Exception as e:
        _clip_error = _("IA indisponível ({erro}). Usando só as regras.").format(erro=e)
        log(_clip_error)
    return _clip


def needs_ai(r, cfg) -> bool:
    """A regra não decidiu e o item é do tipo que passa pela IA."""
    return rule_based(r, cfg)[0] is None and not (r["source"] == "camera" and not cfg.ai_on_camera)


def classify(cfg, progress=None, log=None, stop=None, batch_size: int = 16) -> int:
    """Classifica o que está pendente. category_by: regra | ia | manual | sem_ia (precisava da IA,
    mas ela estava desligada ou sem modelo) | ia_falhou (a IA não conseguiu abrir a imagem)."""
    progress = progress or (lambda *a: None)
    log = log or (lambda *a: None)
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM photos WHERE status='scanned' AND duplicate_of IS NULL ORDER BY id"
    ).fetchall()
    # duplicatas não precisam de IA
    conn.execute("UPDATE photos SET status='classified' WHERE status='scanned' AND duplicate_of IS NOT NULL")

    # IA ligada depois (modelo baixado, opção marcada): o que foi decidido sem ela é refeito.
    # Inclui registros de versões antigas, que gravavam esses casos como "regra".
    redo = []
    if cfg.use_ai and ai_available():
        redo = [r for r in conn.execute(
            "SELECT * FROM photos WHERE status='classified' AND media_item_id IS NULL "
            "AND duplicate_of IS NULL AND category_by IN ('sem_ia', 'regra') ORDER BY id")
            if r["category_by"] == "sem_ia" or needs_ai(r, cfg)]
        if redo:
            log(_("A IA está disponível: reclassificando {n} itens que antes foram decididos sem ela.").format(
                n=len(redo)))
    total = len(rows) + len(redo)
    if not total:
        conn.commit()
        conn.close()
        return 0
    if rows:
        log(_("Classificando {n} arquivos...").format(n=len(rows)))
    stage = _("Classificando")

    def save(r, cat, conf, by):
        if r["category_by"] == "manual":
            cat, conf, by = r["category"], 1.0, "manual"
        conn.execute(
            "UPDATE photos SET category=?, confidence=?, category_by=?, status='classified' WHERE id=?",
            (cat, round(conf, 3), by, r["id"]),
        )

    need_ai = list(redo)
    for r in rows:
        cat, conf = rule_based(r, cfg)
        if cat:
            save(r, cat, conf, "regra")
        elif r["source"] == "camera" and not cfg.ai_on_camera:
            # foto de câmera quase sempre é foto mesmo: poupa tempo
            save(r, "foto", 0.6, "regra")
        elif not cfg.use_ai:
            cat, conf = fallback(r)
            save(r, cat, conf, "sem_ia")
        else:
            need_ai.append(r)
    conn.commit()
    done = total - len(need_ai)
    progress(stage, done, total, _("regras"))

    clip = get_clip(log) if need_ai else None
    for start in range(0, len(need_ai), batch_size):
        if stop is not None and stop.is_set():
            break
        batch = need_ai[start:start + batch_size]
        try:
            results = clip.classify([r["path"] for r in batch]) if clip else [None] * len(batch)
        except Exception as e:  # um arquivo estranho não pode parar tudo
            log(_("Falha na IA: {erro}").format(erro=e))
            results = [None] * len(batch)
        for r, res in zip(batch, results):
            if res is None:
                cat, conf = fallback(r)
                save(r, cat, conf, "ia_falhou" if clip else "sem_ia")
                continue
            cat, conf = res
            # foto de câmera só muda de categoria se a IA estiver segura
            if r["source"] == "camera" and cat in ("meme", "print") and conf < 0.7:
                cat, conf = "foto", 0.5
            save(r, cat, conf, "ia")
        conn.commit()
        done += len(batch)
        progress(stage, done, total, _("IA") if clip else _("regras"))
    conn.close()
    return total
