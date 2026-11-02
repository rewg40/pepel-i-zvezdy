#!/usr/bin/env python3
"""Перепечь карту высот из текущего game/models/island.glb.

Карта высот нужна игре для коллизии земли и для заплаток в дырах. Исходная
версия считалась до правок меша, поэтому в местах дыр там остались высоты от
давно удалённого нижнего слоя поверхности (перепад 47 м на одной клетке) — из
таких клеток в игре получались вертикальные стены.

Берём ровно тот же участок и то же разрешение, что в heightmap.json, и считаем
высоты заново: по каждому треугольнику максимум его плоскости над клеткой
(та же логика, что в tools/build_island.py).

    python3 tools/rebake_heightmap.py
"""
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glb_io  # noqa: E402

def heightmap(V, F, x0, x1, z0, z1, res):
    """Максимум плоскости каждого треугольника над клеткой (как в build_island).

    Своя копия: build_island тянет scipy, а он нужен только для дыр вне суши.
    """
    xs = np.linspace(x0, x1, res)
    zs = np.linspace(z0, z1, res)
    H = np.full((res, res), -1e9)
    tri = V[F]
    tx0, tx1 = tri[:, :, 0].min(1), tri[:, :, 0].max(1)
    tz0, tz1 = tri[:, :, 2].min(1), tri[:, :, 2].max(1)
    ty1 = tri[:, :, 1].max(1)
    ok = (tx1 > x0) & (tx0 < x1) & (tz1 > z0) & (tz0 < z1) & (ty1 > 60)
    for i in np.nonzero(ok)[0]:
        t = tri[i]
        ix0 = max(int(np.searchsorted(xs, t[:, 0].min())) - 1, 0)
        ix1 = min(int(np.searchsorted(xs, t[:, 0].max())), res - 1)
        iz0 = max(int(np.searchsorted(zs, t[:, 2].min())) - 1, 0)
        iz1 = min(int(np.searchsorted(zs, t[:, 2].max())), res - 1)
        if ix1 < ix0 or iz1 < iz0:
            continue
        a, b, c = t
        d = (b[2] - c[2]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[2] - c[2])
        if abs(d) < 1e-9:
            continue
        PX, PZ = np.meshgrid(xs[ix0:ix1 + 1], zs[iz0:iz1 + 1])
        w0 = ((b[2] - c[2]) * (PX - c[0]) + (c[0] - b[0]) * (PZ - c[2])) / d
        w1 = ((c[2] - a[2]) * (PX - c[0]) + (a[0] - c[0]) * (PZ - c[2])) / d
        w2 = 1 - w0 - w1
        m = (w0 >= -0.002) & (w1 >= -0.002) & (w2 >= -0.002)
        if not m.any():
            continue
        y = w0 * a[1] + w1 * b[1] + w2 * c[1]
        sub = H[iz0:iz1 + 1, ix0:ix1 + 1]
        sub[m] = np.maximum(sub[m], y[m])
    # дыры заливаем ближайшей известной высотой (без scipy — итерациями)
    hole = H < -1e8
    H = np.where(hole, np.nan, H)
    for _ in range(400):
        if not np.isnan(H).any():
            break
        nb = np.stack([np.roll(H, 1, 0), np.roll(H, -1, 0),
                       np.roll(H, 1, 1), np.roll(H, -1, 1)])
        with np.errstate(all="ignore"):
            med = np.nanmedian(nb, axis=0)
        H = np.where(np.isnan(H), med, H)
    if np.isnan(H).any():
        H = np.nan_to_num(H, nan=float(np.nanmedian(H)))
    return H


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GLB = os.path.join(ROOT, "game", "models", "island.glb")
META = os.path.join(ROOT, "game", "models", "heightmap.json")
OUT_PNG = os.path.join(ROOT, "game", "models", "heightmap.png")
OUT_F32 = os.path.join(ROOT, "game", "models", "heightmap.f32")


def main() -> int:
    meta = json.load(open(META))
    res = int(meta["res"])
    x0, z0 = float(meta["x0"]), float(meta["z0"])
    cell = float(meta["cell"])
    x1 = x0 + (res - 1) * cell
    z1 = z0 + (res - 1) * cell

    js, blob = glb_io.load_glb(GLB)
    pr = js["meshes"][0]["primitives"][0]
    V = glb_io.accessor(js, blob, pr["attributes"]["POSITION"]).astype(np.float64)
    F = glb_io.accessor(js, blob, pr["indices"]).reshape(-1, 3).astype(np.int64)

    H = heightmap(V, F, x0, x1, z0, z1, res)
    old = np.fromfile(OUT_F32, dtype="<f4").astype(np.float64).reshape(res, res)
    diff = np.abs(H - old)
    print("карта высот %dx%d, y %.1f..%.1f" % (res, res, H.min(), H.max()))
    print("  отличие от прежней: медиана %.2f м, p95 %.2f м, максимум %.2f м"
          % (np.median(diff), np.percentile(diff, 95), diff.max()))
    print("  клеток с перепадом >10 м к соседу: %d (было %d)"
          % (int((np.abs(np.diff(H, axis=0)) > 10).sum() + (np.abs(np.diff(H, axis=1)) > 10).sum()),
             int((np.abs(np.diff(old, axis=0)) > 10).sum() + (np.abs(np.diff(old, axis=1)) > 10).sum())))

    lo, hi = float(H.min()), float(H.max())
    Image.fromarray(((H - lo) / max(hi - lo, 1e-6) * 65535).astype(np.uint16)).save(OUT_PNG)
    H.astype("<f4").tofile(OUT_F32)
    meta.update({"y_min": lo, "y_max": hi})
    json.dump(meta, open(META, "w"), indent=1)
    print("записаны", OUT_PNG, OUT_F32, META)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
