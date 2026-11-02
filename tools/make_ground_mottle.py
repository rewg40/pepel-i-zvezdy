#!/usr/bin/env python3
"""Бесшовная плитка «разводов» из родного атласа → models/ground_mottle.png.

Атлас острова — 4096² на ~20 км, то есть ~5 м на тексель: на площадке арены
это считанные тексели, поэтому шейдер земли рисовал ровное песочное пятно без
характера модели. Плитка собирается из участка того же атласа вокруг арены
(бежевые разводы/пятна) методом оверлапа с sin²-окнами, поэтому:

* цвет и характер пятен — родные, не чужая плитка;
* стыков не видно, плитка повторяется каждые ~320 м;
* яркость нормирована (среднее ≈ 1), так что она только добавляет разводы
  поверх атласа и не меняет биомы.

    python3 tools/make_ground_mottle.py      # → game/models/ground_mottle.png
"""
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glb_io  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GLB = os.path.join(ROOT, "game", "models", "island.glb")
OUT = os.path.join(ROOT, "game", "models", "ground_mottle.png")

UV_CENTER = (2048 / 4096.0, 1984 / 4096.0)   # песок вокруг арены
PATCH = 320        # текселей атласа в источнике (~1.6 км)
CROP = 96          # фрагмент-оверлап
SIZE = 1024        # сторона плитки
CONTRAST = 3.0     # усиление разводов


def overlap_tile(src: np.ndarray, rng) -> np.ndarray:
    """Бесшовная плитка из случайных фрагментов-оверлапов (окно sin²)."""
    size, chop = SIZE, CROP
    half_c, step = chop // 2, chop // 2
    acc = np.zeros((size, size, src.shape[2]) if src.ndim == 3 else (size, size))
    wsum = np.zeros((size, size))
    ys, xs = np.meshgrid(np.arange(size), np.arange(size), indexing="ij")
    for gy in range(0, size, step):
        for gx in range(0, size, step):
            sy = int(rng.integers(0, src.shape[0] - chop))
            sx = int(rng.integers(0, src.shape[1] - chop))
            patch = src[sy:sy + chop, sx:sx + chop]
            dy = ((ys - gy + size // 2) % size) - size // 2
            dx = ((xs - gx + size // 2) % size) - size // 2
            inside = (np.abs(dy) < half_c) & (np.abs(dx) < half_c)
            if not inside.any():
                continue
            win = np.where(
                inside,
                np.sin(np.pi * (dy + half_c) / chop) ** 2
                * np.sin(np.pi * (dx + half_c) / chop) ** 2, 0.0)
            py = np.clip(dy + half_c, 0, chop - 1)
            px = np.clip(dx + half_c, 0, chop - 1)
            if src.ndim == 3:
                acc += patch[py, px] * win[:, :, None]
            else:
                acc += patch[py, px] * win
            wsum += win
    return acc / np.maximum(wsum, 1e-6)[:, :, None]


def main() -> int:
    js, blob = glb_io.load_glb(GLB)
    tex = np.asarray(glb_io.material_texture(
        js, blob, "baseColorTexture", 0)).astype(np.float64) / 255.0
    h, w, _ = tex.shape
    cx, cy = int(UV_CENTER[0] * w), int(UV_CENTER[1] * h)
    src = tex[cy - PATCH // 2:cy + PATCH // 2, cx - PATCH // 2:cx + PATCH // 2]

    rng = np.random.default_rng(23)
    tile = overlap_tile(src, rng)
    # плитка — отношение к среднему цвету песка у арены: единица там, где атлас
    # совпадает с площадкой, темнее в «пятнах», светлее на выбеленных участках
    arena = tex[cy - 100:cy + 100, cx - 100:cx + 100].mean(axis=(0, 1))
    tile = (tile / arena[None, None, :] - 1.0) * CONTRAST + 1.0
    tile = np.clip(tile, 0.78, 1.16)

    img = Image.fromarray(np.clip(tile * 255.0, 0, 255).astype(np.uint8), "RGB")
    img.save(OUT)
    arr = np.asarray(img).astype(np.float64) / 255.0
    print("разводы земли:", OUT, arr.shape, "среднее", arr.mean(axis=(0, 1)).round(3),
          "std", round(float(arr.std()), 3),
          "шов", round(float(np.abs(arr[:, 0] - arr[:, -1]).mean()), 4))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
