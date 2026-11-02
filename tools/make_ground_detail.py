#!/usr/bin/env python3
"""Мелкая бесшовная плитка-зерно для земли (models/ground_detail.png).

Родной атлас острова даёт всего ~5 м на тексель: у ног игрока земля выглядит
мыльным пятном. Этот файл — не цвет, а множитель яркости (серый, среднее 0.5),
который шейдер `shaders/ground.gdshader` накладывает поверх атласа, поэтому
биомы (песок/трава/камень) остаются родными, а зерно появляется.

Плитка собирается из наземного участка того же атласа методом оверлапа с
sin²-окнами, так что стыков не видно.

    python3 tools/make_ground_detail.py      # → game/models/ground_detail.png
"""
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glb_io  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GLB = os.path.join(ROOT, "game", "models", "island.glb")
OUT = os.path.join(ROOT, "game", "models", "ground_detail.png")

# участок атласа: песчаный грунт вокруг арены (UV-центр и размер в текселях)
UV_CENTER = (2048 / 4096.0, 1984 / 4096.0)
PATCH = 256
SIZE = 512
CROP = 128
MEAN = 0.5      # средняя яркость плитки


def periodic_noise(size: int, freq: int, rng) -> np.ndarray:
    """Периодический по плитке гладкий шум (косинусная интерполяция решётки)."""
    grid = rng.normal(0.0, 1.0, (freq, freq))
    ys = np.linspace(0, freq, size, endpoint=False)
    xs = np.linspace(0, freq, size, endpoint=False)
    y0 = np.floor(ys).astype(int)
    x0 = np.floor(xs).astype(int)
    fy = (1 - np.cos((ys - y0) * np.pi)) / 2
    fx = (1 - np.cos((xs - x0) * np.pi)) / 2
    g00 = grid[np.ix_(y0 % freq, x0 % freq)]
    g10 = grid[np.ix_((y0 + 1) % freq, x0 % freq)]
    g01 = grid[np.ix_(y0 % freq, (x0 + 1) % freq)]
    g11 = grid[np.ix_((y0 + 1) % freq, (x0 + 1) % freq)]
    top = g00 * (1 - fx)[None, :] + g01 * fx[None, :]
    bot = g10 * (1 - fx)[None, :] + g11 * fx[None, :]
    return top * (1 - fy)[:, None] + bot * fy[:, None]


def overlap_tile(src: np.ndarray, rng) -> np.ndarray:
    """Бесшовная плитка из случайных фрагментов-оверлапов (окно sin²)."""
    size = SIZE
    half_c = CROP // 2
    step = CROP // 2
    acc = np.zeros((size, size))
    wsum = np.zeros((size, size))
    ys, xs = np.meshgrid(np.arange(size), np.arange(size), indexing="ij")
    for gy in range(0, size, step):
        for gx in range(0, size, step):
            sy = int(rng.integers(0, src.shape[0] - CROP))
            sx = int(rng.integers(0, src.shape[1] - CROP))
            patch = src[sy:sy + CROP, sx:sx + CROP]
            dy = ((ys - gy + size // 2) % size) - size // 2
            dx = ((xs - gx + size // 2) % size) - size // 2
            inside = (np.abs(dy) < half_c) & (np.abs(dx) < half_c)
            if not inside.any():
                continue
            win = np.where(
                inside,
                np.sin(np.pi * (dy + half_c) / CROP) ** 2 * np.sin(np.pi * (dx + half_c) / CROP) ** 2,
                0.0)
            py = np.clip(dy + half_c, 0, CROP - 1)
            px = np.clip(dx + half_c, 0, CROP - 1)
            acc += patch[py, px] * win
            wsum += win
    return acc / np.maximum(wsum, 1e-6)


def main() -> int:
    js, blob = glb_io.load_glb(GLB)
    tex = np.asarray(glb_io.material_texture(js, blob, "baseColorTexture", 0)).astype(np.float64) / 255.0
    h, w, _ = tex.shape
    cx, cy = int(UV_CENTER[0] * w), int(UV_CENTER[1] * h)
    src = tex[cy - PATCH // 2:cy + PATCH // 2, cx - PATCH // 2:cx + PATCH // 2]
    # яркость: зерну нужен только свет, цвет берётся из атласа
    src = src @ np.array([0.299, 0.587, 0.114])

    rng = np.random.default_rng(11)
    tile = overlap_tile(src, rng)
    # яркость → серое зерно вокруг 0.5, без цвета
    tile -= tile.mean()
    tile /= max(tile.std(), 1e-6)
    grain = MEAN + tile * 0.055
    grain += periodic_noise(SIZE, 96, rng) * 0.012
    grain += periodic_noise(SIZE, 24, rng) * 0.008

    img = Image.fromarray(np.clip(grain * 255.0, 0, 255).astype(np.uint8), "L")
    img.save(OUT)
    arr = np.asarray(img).astype(np.float64) / 255.0
    print("зерно земли:", OUT, arr.shape, "среднее", round(float(arr.mean()), 3),
          "std", round(float(arr.std()), 4),
          "шов x", round(float(np.abs(arr[:, 0] - arr[:, -1]).mean()), 4))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
