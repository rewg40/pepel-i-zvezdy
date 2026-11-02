#!/usr/bin/env python3
"""Бесшовная плитка земли для арены из base-color текстуры island.glb.

Остров собран одним мешем на 20×20 км с UV 0..1 на всю карту: у арены один
тексель текстуры покрывает ~5 м, поэтому земля выглядит ровным пятном.
Берём наземный участок текстуры, делаем из него бесшовную плитку (зеркальная
сборка 2×2) и кладём её в игру как repeating albedo.

    python3 tools/make_ground_tile.py            # → game/models/ground_tile.png
"""
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glb_io  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GLB = os.path.join(ROOT, "game", "models", "island.glb")
OUT = os.path.join(ROOT, "game", "models", "ground_tile.png")

# участок текстуры, который соответствует земле вокруг арены (песок/грунт
# с камешками, без воды и зелени); найден перебором однородных наземных пятен
UV_CENTER = (1920 / 4096.0 + 128 / 4096.0, 1856 / 4096.0 + 128 / 4096.0)
PATCH = 256          # текселей исходника (≈1.3 км местности)
OUT_SIZE = 512       # размер готовой плитки
TARGET_MEAN = 108    # средняя яркость плитки (0..255): на солнце не выгорает


def periodic_noise(size: int, freq: int, rng) -> np.ndarray:
    """Периодический по плитке гладкий шум (косинусная интерполяция решётки)."""
    grid = rng.normal(0.0, 1.0, (freq, freq))
    ys = np.linspace(0, freq, size, endpoint=False)
    xs = np.linspace(0, freq, size, endpoint=False)
    y0 = np.floor(ys).astype(int)
    x0 = np.floor(xs).astype(int)
    fy = ys - y0
    fx = xs - x0
    fy = (1 - np.cos(fy * np.pi)) / 2
    fx = (1 - np.cos(fx * np.pi)) / 2
    g00 = grid[np.ix_(y0 % freq, x0 % freq)]
    g10 = grid[np.ix_((y0 + 1) % freq, x0 % freq)]
    g01 = grid[np.ix_(y0 % freq, (x0 + 1) % freq)]
    g11 = grid[np.ix_((y0 + 1) % freq, (x0 + 1) % freq)]
    top = g00 * (1 - fx)[None, :] + g01 * fx[None, :]
    bot = g10 * (1 - fx)[None, :] + g11 * fx[None, :]
    return top * (1 - fy)[:, None] + bot * fy[:, None]


def make_tile(tex: np.ndarray, rng=None) -> Image.Image:
    """Плитка из случайных фрагментов наземного участка (оверлап с cos²-окном).

    Зеркальная сборка давала явный «калейдоскоп», а простой wrap — шов.
    Здесь каждый фрагмент кладётся с окном sin²·sin² и всё нормируется суммой
    весов, поэтому результат периодичен и без видимых стыков.
    """
    if rng is None:
        rng = np.random.default_rng(7)
    h, w, _ = tex.shape
    cx, cy = int(UV_CENTER[0] * w), int(UV_CENTER[1] * h)
    half = PATCH // 2
    x0, y0 = cx - half, cy - half
    src = tex[y0:y0 + PATCH, x0:x0 + PATCH]

    size = OUT_SIZE
    crop = 128
    step = crop // 2
    acc = np.zeros((size, size, 3))
    wsum = np.zeros((size, size, 1))
    ys, xs = np.meshgrid(np.arange(size), np.arange(size), indexing="ij")
    half_c = crop // 2
    for gy in range(0, size, step):
        for gx in range(0, size, step):
            sy = int(rng.integers(0, PATCH - crop))
            sx = int(rng.integers(0, PATCH - crop))
            patch = src[sy:sy + crop, sx:sx + crop]
            # знаковое расстояние по тору: фрагмент может «завернуться» за край
            dy = ((ys - gy + size // 2) % size) - size // 2
            dx = ((xs - gx + size // 2) % size) - size // 2
            inside = (np.abs(dy) < half_c) & (np.abs(dx) < half_c)
            if not inside.any():
                continue
            # окно sin² (периодично по плитке) → на стыках даёт плавный переход
            win = np.where(
                inside,
                np.sin(np.pi * (dy + half_c) / crop) ** 2 * np.sin(np.pi * (dx + half_c) / crop) ** 2,
                0.0,
            )[..., None]
            py = np.clip(dy + half_c, 0, crop - 1)
            px = np.clip(dx + half_c, 0, crop - 1)
            acc += patch[py, px] * win
            wsum += win
    arr = acc / np.maximum(wsum, 1e-6)

    # мелкая зернистость: без неё плитка выглядит мыльным пятном
    arr += (periodic_noise(size, 64, rng) * 9.0)[..., None]
    arr += (periodic_noise(size, 16, rng) * 6.0)[..., None]

    arr *= TARGET_MEAN / max(arr.mean(), 1.0)
    arr[..., 2] *= 1.06      # чуть холоднее: песок не должен быть оранжевым
    arr[..., 1] *= 1.02
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def main() -> int:
    js, blob = glb_io.load_glb(GLB)
    tex = np.asarray(glb_io.material_texture(js, blob, "baseColorTexture", 0)).astype(np.float64)
    img = make_tile(tex)
    img.save(OUT)
    arr = np.asarray(img)
    print("плитка:", OUT, arr.shape, "средний цвет", arr.reshape(-1, 3).mean(0).round(1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
