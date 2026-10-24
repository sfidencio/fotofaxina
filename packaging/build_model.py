"""Gera a IA leve do FotoFaxina em models/ (roda no build do GitHub ou uma vez na sua máquina).

    pip install -r packaging/requirements-model.txt
    python packaging/build_model.py

Saída (~90 MB no total):
    models/clip_image.onnx   parte de imagem do CLIP, quantizada em int8
    models/clip_text.npy     vetores das frases de app/ai_prompts.py (já normalizados)
    models/clip_labels.json  categoria de cada vetor + escala

Também confere que o pré-processamento em NumPy do app bate com o oficial do CLIP e que a
versão int8 continua parecida com a original. Se algo divergir, o script falha.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw
from transformers import CLIPModel, CLIPProcessor

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.ai_prompts import IMAGE_SIZE, MODEL_ID, PROMPTS  # noqa: E402

OUT = Path(os.environ.get("FOTOFAXINA_MODEL_OUT", ROOT / "models"))


class ImageEncoder(torch.nn.Module):
    """pixel_values (N,3,224,224) -> vetor da imagem normalizado (N,512)."""

    def __init__(self, model: CLIPModel):
        super().__init__()
        self.vision = model.vision_model
        self.proj = model.visual_projection

    def forward(self, pixel_values):
        pooled = self.vision(pixel_values=pixel_values).pooler_output
        emb = self.proj(pooled)
        return emb / emb.norm(dim=-1, keepdim=True)


def sample_images() -> list[Image.Image]:
    """Imagens sintéticas só para conferir a conversão (não é teste de acerto)."""
    imgs = []
    a = Image.new("RGB", (640, 480), (40, 120, 200))
    ImageDraw.Draw(a).ellipse([200, 120, 440, 360], fill=(250, 200, 60))
    imgs.append(a)
    b = Image.new("RGB", (720, 1560), (255, 255, 255))
    d = ImageDraw.Draw(b)
    for y in range(60, 1500, 90):
        d.rounded_rectangle([40 if (y // 90) % 2 else 260, y, 460 if (y // 90) % 2 else 680, y + 60], 20,
                            fill=(220, 248, 198) if (y // 90) % 2 else (240, 240, 240))
    imgs.append(b)
    c = Image.new("RGB", (800, 800), (20, 20, 20))
    ImageDraw.Draw(c).rectangle([0, 600, 800, 800], fill=(255, 255, 255))
    imgs.append(c)
    return imgs


def main() -> None:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    import onnxruntime as ort

    from app.classifier import preprocess

    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Baixando {MODEL_ID}...")
    # atenção "eager": a exportação ONNX clássica não lida bem com a otimização sdpa
    model = CLIPModel.from_pretrained(MODEL_ID, attn_implementation="eager").eval()
    processor = CLIPProcessor.from_pretrained(MODEL_ID, use_fast=False)

    # 1) vetores das frases
    labels, texts = [], []
    for cat, prompts in PROMPTS.items():
        for p in prompts:
            labels.append(cat)
            texts.append(p)
    with torch.no_grad():
        tok = processor(text=texts, return_tensors="pt", padding=True)
        t = model.text_model(input_ids=tok["input_ids"], attention_mask=tok["attention_mask"]).pooler_output
        t = model.text_projection(t)
        t = t / t.norm(dim=-1, keepdim=True)
    np.save(OUT / "clip_text.npy", t.numpy().astype(np.float32))
    (OUT / "clip_labels.json").write_text(json.dumps({
        "model": MODEL_ID, "labels": labels, "prompts": texts,
        "logit_scale": float(model.logit_scale.exp().item()),
    }, indent=1, ensure_ascii=False), encoding="utf-8")

    # 2) exportar a parte de imagem para ONNX
    enc = ImageEncoder(model).eval()
    fp32 = OUT / "clip_image_fp32.onnx"
    dummy = torch.randn(1, 3, IMAGE_SIZE, IMAGE_SIZE)
    kwargs = dict(
        input_names=["pixel_values"], output_names=["image_embeds"],
        dynamic_axes={"pixel_values": {0: "batch"}, "image_embeds": {0: "batch"}},
        opset_version=17, do_constant_folding=True,
    )
    try:
        torch.onnx.export(enc, (dummy,), str(fp32), dynamo=False, **kwargs)
    except TypeError:  # versões antigas do torch não têm o parâmetro dynamo
        torch.onnx.export(enc, (dummy,), str(fp32), **kwargs)

    # 3) quantizar (int8): ~4x menor, quase a mesma resposta
    int8 = OUT / "clip_image.onnx"
    # só MatMul/Gemm: ConvInteger (convolução int8) não roda no ONNX Runtime de CPU; a única
    # convolução do CLIP (recorte da imagem em blocos) é pequena e fica em float
    quantize_dynamic(str(fp32), str(int8), weight_type=QuantType.QInt8, op_types_to_quantize=["MatMul", "Gemm"])
    # versão de formato compatível com ONNX Runtime mais antigos (o opset 17 cabe no IR 8)
    import onnx

    m = onnx.load(str(int8))
    if m.ir_version > 8:
        m.ir_version = 8
        onnx.save(m, str(int8))

    # 4) conferências
    imgs = sample_images()
    ours = np.stack([preprocess(im) for im in imgs]).astype(np.float32)
    official = processor(images=imgs, return_tensors="np")["pixel_values"].astype(np.float32)
    diff = float(np.abs(ours - official).max())
    report(f"Pré-processamento: diferença máxima {diff:.4f}")
    assert diff < 0.05, "O pré-processamento do app não bate com o do CLIP"

    with torch.no_grad():
        ref = enc(torch.from_numpy(official)).numpy()
    for path in (fp32, int8):
        sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        emb = sess.run(None, {"pixel_values": ours})[0]
        emb /= np.linalg.norm(emb, axis=-1, keepdims=True)
        cos = (emb * ref).sum(-1)
        report(f"{path.name}: similaridade com o PyTorch {cos.round(4).tolist()}")
        assert cos.min() > (0.99 if path == fp32 else 0.90), f"{path.name} divergiu do modelo original"
    fp32.unlink()

    sizes = {p.name: f"{p.stat().st_size / 1e6:.1f} MB" for p in OUT.iterdir()}
    report(f"Pronto: {sizes}")


def report(msg: str) -> None:
    """No GitHub Actions vira um aviso visível no resumo do build."""
    print(f"::notice title=build_model::{msg}" if os.environ.get("GITHUB_ACTIONS") else msg, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        tb = traceback.format_exc()
        if os.environ.get("GITHUB_ACTIONS"):
            # o fim do traceback costuma bastar; %0A é quebra de linha nas anotações
            print("::error title=build_model::" + tb[-3000:].replace("%", "%25").replace("\n", "%0A"), flush=True)
        raise
