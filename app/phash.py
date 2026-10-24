"""Hash perceptual (pHash) só com NumPy — mesmo resultado do imagehash.phash, sem SciPy."""
from __future__ import annotations

import numpy as np
from PIL import Image

_N = 32
# matriz da DCT tipo II (mesma escala da scipy.fftpack.dct sem normalização)
_k = np.arange(_N).reshape(-1, 1)
_n = np.arange(_N).reshape(1, -1)
_DCT = 2.0 * np.cos(np.pi * _k * (2 * _n + 1) / (2 * _N))


def phash(img: Image.Image, hash_size: int = 8) -> str:
    small = img.convert("L").resize((_N, _N), Image.Resampling.LANCZOS)
    pixels = np.asarray(small, dtype=np.float64)
    dct = _DCT @ pixels @ _DCT.T          # DCT nas linhas e nas colunas
    low = dct[:hash_size, :hash_size]
    bits = (low > np.median(low)).flatten()
    value = 0
    for b in bits:
        value = (value << 1) | int(b)
    return f"{value:0{hash_size * hash_size // 4}x}"
