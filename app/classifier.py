"""Classificação: regras rápidas primeiro, IA local (CLIP) só para o que sobrar."""
from __future__ import annotations

import os

from PIL import Image, ImageOps

from . import db

CLIP_MODEL = "openai/clip-vit-base-patch32"

# Frases em inglês funcionam melhor com o CLIP. Cada categoria tem várias descrições.
PROMPTS: dict[str, list[str]] = {
    "foto": [
        "a photo of people", "a family photo", "a selfie", "a photo of a child",
        "a photo of friends at a party", "a photo of a pet", "a photo of a birthday celebration",
        "a photo of food on a table",
    ],
    "paisagem": [
        "a landscape photo", "a travel photo of a city", "a photo of nature",
        "a photo of a beach", "a photo of a building", "a photo of the sky at sunset",
    ],
    "meme": [
        "an internet meme", "a meme with a text caption", "a cartoon or comic strip",
        "an image with a motivational quote", "a funny picture with text on it",
        "a sticker with a cartoon character", "a good morning message image with flowers and text",
    ],
    "print": [
        "a screenshot of a phone", "a screenshot of a chat conversation",
        "a screenshot of a website", "a screenshot of a computer screen",
        "a screenshot of a social media post",
    ],
    "documento": [
        "a photo of a document", "a photo of a receipt", "a scanned paper document",
        "a photo of an ID card", "a photo of a whiteboard", "a photo of a bill or invoice",
    ],
}


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


def _tensor(out, attr):
    """Compatível com versões do transformers que devolvem tensor ou objeto de saída."""
    if hasattr(out, "norm"):
        return out
    for name in (attr, "pooler_output"):
        val = getattr(out, name, None)
        if val is not None:
            return val
    raise TypeError(f"Saída inesperada do CLIP: {type(out)}")


class ClipClassifier:
    def __init__(self):
        import torch
        from transformers import CLIPModel, CLIPProcessor

        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = CLIPModel.from_pretrained(CLIP_MODEL).to(self.device).eval()
        self.processor = CLIPProcessor.from_pretrained(CLIP_MODEL)
        self.labels: list[str] = []
        texts: list[str] = []
        for cat, prompts in PROMPTS.items():
            for p in prompts:
                self.labels.append(cat)
                texts.append(p)
        with torch.no_grad():
            tok = self.processor(text=texts, return_tensors="pt", padding=True).to(self.device)
            t = _tensor(self.model.get_text_features(**tok), "text_embeds")
            self.text_feats = t / t.norm(dim=-1, keepdim=True)

    def classify(self, paths: list[str]) -> list[tuple[str, float] | None]:
        torch = self.torch
        images, idx = [], []
        for i, p in enumerate(paths):
            try:
                with Image.open(p) as im:
                    im = ImageOps.exif_transpose(im).convert("RGB")
                    im.thumbnail((448, 448))
                    images.append(im.copy())
                    idx.append(i)
            except Exception:
                pass
        out: list[tuple[str, float] | None] = [None] * len(paths)
        if not images:
            return out
        with torch.no_grad():
            inp = self.processor(images=images, return_tensors="pt").to(self.device)
            f = _tensor(self.model.get_image_features(**inp), "image_embeds")
            f = f / f.norm(dim=-1, keepdim=True)
            probs = (100.0 * f @ self.text_feats.T).softmax(dim=-1).cpu()
        for row, i in zip(probs, idx):
            per_cat: dict[str, float] = {}
            for label, p in zip(self.labels, row.tolist()):
                per_cat[label] = per_cat.get(label, 0.0) + p
            cat = max(per_cat, key=per_cat.get)
            out[i] = (cat, per_cat[cat])
        return out


_clip: ClipClassifier | None = None
_clip_error: str | None = None


def get_clip(log) -> ClipClassifier | None:
    global _clip, _clip_error
    if _clip is not None or _clip_error is not None:
        return _clip
    try:
        log("Carregando modelo de IA (na primeira vez baixa ~600 MB)...")
        _clip = ClipClassifier()
        log(f"IA pronta ({_clip.device}).")
    except ImportError:
        _clip_error = "IA não instalada (pip install -r requirements-ia.txt). Usando só regras."
        log(_clip_error)
    except Exception as e:  # sem internet para baixar o modelo, etc.
        _clip_error = f"IA indisponível: {e}. Usando só regras."
        log(_clip_error)
    return _clip


def ai_available() -> bool:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except ImportError:
        return False


def classify(cfg, progress=None, log=None, stop=None, batch_size: int = 16) -> int:
    progress = progress or (lambda *a: None)
    log = log or (lambda *a: None)
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM photos WHERE status='scanned' AND duplicate_of IS NULL ORDER BY id"
    ).fetchall()
    # duplicatas não precisam de IA: herdam o estado depois
    conn.execute("UPDATE photos SET status='classified' WHERE status='scanned' AND duplicate_of IS NOT NULL")
    total = len(rows)
    if not total:
        conn.commit()
        return 0
    log(f"Classificando {total} arquivos...")

    def save(r, cat, conf, by):
        if r["category_by"] == "manual":
            cat, conf, by = r["category"], 1.0, "manual"
        conn.execute(
            "UPDATE photos SET category=?, confidence=?, category_by=?, status='classified' WHERE id=?",
            (cat, round(conf, 3), by, r["id"]),
        )

    need_ai = []
    for r in rows:
        cat, conf = rule_based(r, cfg)
        if cat:
            save(r, cat, conf, "regra")
        else:
            need_ai.append(r)
    conn.commit()
    done = total - len(need_ai)
    progress("Classificando", done, total, "regras")

    clip = get_clip(log) if (cfg.use_ai and need_ai) else None
    for start in range(0, len(need_ai), batch_size):
        if stop is not None and stop.is_set():
            break
        batch = need_ai[start:start + batch_size]
        results = clip.classify([r["path"] for r in batch]) if clip else [None] * len(batch)
        for r, res in zip(batch, results):
            if res is None:
                cat, conf = fallback(r)
                save(r, cat, conf, "regra")
                continue
            cat, conf = res
            # foto de câmera só muda de categoria se a IA estiver segura
            if r["source"] == "camera" and cat in ("meme", "print") and conf < 0.7:
                cat, conf = "foto", 0.5
            save(r, cat, conf, "ia")
        conn.commit()
        done += len(batch)
        progress("Classificando", done, total, "IA" if clip else "regras")
    conn.close()
    return total
