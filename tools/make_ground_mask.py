#!/usr/bin/env python3
"""Маска дыр в меше острова над площадкой арены.

Терраин острова после децимации не сплошной: у арены встречаются участки,
которых не касается ни один треугольник (13.8 % площади heightmap) — сквозь них
видно пустоту. Игра закрывает их заплаткой по heightmap, но рисовать заплатку
под всей площадью нельзя: она висит над рельефом и даёт видимую кромку.

Здесь растрируем покрытие меша в сетку heightmap (1 м) и сохраняем маску дыр,
расширенную на пару клеток, чтобы заплатка заходила под соседние треугольники.

    python3 tools/make_ground_mask.py     # → game/models/ground_mask.png
"""
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glb_io  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GLB = os.path.join(ROOT, "game", "models", "island.glb")
META = os.path.join(ROOT, "game", "models", "heightmap.json")
OUT = os.path.join(ROOT, "game", "models", "ground_mask.png")
DILATE = 2


def coverage(P, I, meta):
    res = int(meta["res"])
    x0, z0, cell = float(meta["x0"]), float(meta["z0"]), float(meta["cell"])
    x1 = x0 + (res - 1) * cell
    z1 = z0 + (res - 1) * cell
    T = P[I]
    sel = ((T[:, :, 0].max(1) > x0 - cell) & (T[:, :, 0].min(1) < x1 + cell)
           & (T[:, :, 2].max(1) > z0 - cell) & (T[:, :, 2].min(1) < z1 + cell))
    cov = np.zeros((res, res), bool)
    xs_all = x0 + (np.arange(res) + 0.5) * cell
    zs_all = z0 + (np.arange(res) + 0.5) * cell
    for t in T[sel]:
        ix0 = max(int((t[:, 0].min() - x0) / cell) - 1, 0)
        ix1 = min(int((t[:, 0].max() - x0) / cell) + 2, res)
        iz0 = max(int((t[:, 2].min() - z0) / cell) - 1, 0)
        iz1 = min(int((t[:, 2].max() - z0) / cell) + 2, res)
        if ix1 <= ix0 or iz1 <= iz0:
            continue
        PX, PZ = np.meshgrid(xs_all[ix0:ix1], zs_all[iz0:iz1])
        d = (t[1, 0] - t[0, 0]) * (t[2, 2] - t[0, 2]) - (t[2, 0] - t[0, 0]) * (t[1, 2] - t[0, 2])
        if abs(d) < 1e-12:
            continue
        b1 = ((PX - t[0, 0]) * (t[2, 2] - t[0, 2]) - (t[2, 0] - t[0, 0]) * (PZ - t[0, 2])) / d
        b2 = ((t[1, 0] - t[0, 0]) * (PZ - t[0, 2]) - (PX - t[0, 0]) * (t[1, 2] - t[0, 2])) / d
        b0 = 1 - b1 - b2
        m = (b0 >= -1e-6) & (b1 >= -1e-6) & (b2 >= -1e-6)
        cov[iz0:iz1, ix0:ix1] |= m
    return cov


def dilate(mask, n):
    out = mask.copy()
    for _ in range(n):
        grown = out.copy()
        grown[1:] |= out[:-1]
        grown[:-1] |= out[1:]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        out = grown
    return out


def main() -> int:
    js, blob = glb_io.load_glb(GLB)
    # земля — первый меш файла (материал Island, 295k вершин)
    pr = js["meshes"][0]["primitives"][0]
    P = glb_io.accessor(js, blob, pr["attributes"]["POSITION"]).astype(np.float64)
    I = glb_io.accessor(js, blob, pr["indices"]).reshape(-1, 3).astype(np.int64)
    meta = json.load(open(META))
    cov = coverage(P, I, meta)
    holes = dilate(~cov, DILATE)
    Image.fromarray((holes * 255).astype(np.uint8)).save(OUT)
    print("маска дыр:", OUT, holes.shape,
          "ячеек-дыр", int((~cov).sum()), "из", cov.size,
          "-> после расширения", int(holes.sum()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
