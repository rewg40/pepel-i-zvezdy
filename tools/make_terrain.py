#!/usr/bin/env python3
"""Собрать терраин острова из карты высот → game/models/island_terrain.glb.

Исходный меш island.glb после децимации непригоден для ближнего плана: половина
треугольников была вывернута, есть дыры (13.8 % площади у арены), наложенные
слои поверхности и треугольники размером в километр — у арены они «просвечивают»
сквозь любые заплатки и дают светлые плиты на песке.

Поэтому терраин рисуется заново по высотам:

* у арены — сетка 1 м по heightmap.f32 (она же коллизия, ровно то, по чему
  ходит игрок);
* остальной остров — сетка 12 м по верхней огибающей меша (максимум плоскости
  треугольников), с гармонической заливкой дыр.

UV берутся по той же аффинной развёртке, что у island.glb
(u = x·5e-5 + 0.499974, v = z·7e-5 + 0.505151), поэтому цвета атласа на месте:
песок в центре, зелень по краям.

    python3 tools/make_terrain.py        # → game/models/island_terrain.glb
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glb_io  # noqa: E402
import glbw  # noqa: E402
from make_island_fill import (  # noqa: E402
    local_surface, neighbours, raster, shift,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GLB = os.path.join(ROOT, "game", "models", "island.glb")
HM_JSON = os.path.join(ROOT, "game", "models", "heightmap.json")
HM_F32 = os.path.join(ROOT, "game", "models", "heightmap.f32")
OUT = os.path.join(ROOT, "game", "models", "island_terrain.glb")

UV_U_PER_M, UV_U_OFFSET = 5.0e-5, 0.499974
UV_V_PER_M, UV_V_OFFSET = 7.0e-5, 0.505151

COARSE_CELL = 24.0      # м, дальний план
# Терраин острова лежит на высоте ~1400 м, а Ocean/Seafloor в исходной модели
# висят на y=0 — в 1.4 км ниже, поэтому в игре «моря» не видно. За уровень воды
# берём отметку ниже самого нижнего края суши вокруг арены.
SEA_LEVEL = 1330.0      # м, всё ниже — вода
MIN_LAND = 2.0          # м над водой: ниже не строим, чтобы не лезть под воду


def harmonic_fill(h, valid, iters=2000, tol=1e-3):
    h = h.copy()
    for _ in range(iters):
        nb = sum(neighbours(h)) * 0.25
        new = np.where(valid, h, nb)
        delta = float(np.abs(new - h).max())
        h = new
        if delta < tol:
            break
    return h


def limit_slope(h, valid, cell, max_step=1.0, iters=200):
    h = h.copy()
    lim = max_step * cell
    for _ in range(iters):
        nb = neighbours(h)
        h = np.where(valid, h, np.clip(h, np.minimum.reduce(nb) - lim,
                                       np.maximum.reduce(nb) + lim))
    return h


def grid_mesh(cells, h, cell, nx, nz, x0, z0, name):
    """Квады по клеткам cells; обход против часовой → нормали вверх."""
    xs = x0 + np.arange(nx) * cell
    zs = z0 + np.arange(nz) * cell
    X, Z = np.meshgrid(xs, zs)
    V = np.stack([X.ravel(), h.ravel(), Z.ravel()], axis=1).astype(np.float32)
    U = np.stack([(X * UV_U_PER_M + UV_U_OFFSET).ravel(),
                  (Z * UV_V_PER_M + UV_V_OFFSET).ravel()], axis=1).astype(np.float32)
    N = np.zeros_like(V)
    N[:, 1] = 1.0

    quads = []
    for iz in range(nz - 1):
        row = iz * nx
        for ix in np.nonzero(cells[iz, :nx - 1])[0]:
            a = row + ix
            b = a + 1
            c = a + nx
            d = c + 1
            quads.append((a, c, b))
            quads.append((b, c, d))
    if not quads:
        print("  %-12s пусто" % name)
        return None
    F = np.array(quads, np.uint32)
    used = np.unique(F)
    remap = np.full(len(V), -1, np.int64)
    remap[used] = np.arange(len(used))
    print("  %-12s клетка %4.1f м: %d вершин, %d треугольников"
          % (name, cell, len(used), len(F)))
    return {'attributes': {'POSITION': V[used], 'NORMAL': N[used], 'TEXCOORD_0': U[used]},
            'indices': remap[F].reshape(-1)}


def main() -> int:
    js, blob = glb_io.load_glb(GLB)
    pr = js["meshes"][0]["primitives"][0]
    P = glb_io.accessor(js, blob, pr["attributes"]["POSITION"]).astype(np.float64)
    I = glb_io.accessor(js, blob, pr["indices"]).reshape(-1, 3).astype(np.int64)

    hm = json.load(open(HM_JSON))
    res = int(hm["res"])
    hcell = float(hm["cell"])
    hx0, hz0 = float(hm["x0"]), float(hm["z0"])
    hx1 = hx0 + (res - 1) * hcell
    hz1 = hz0 + (res - 1) * hcell
    fine = np.fromfile(HM_F32, dtype="<f4").astype(np.float64).reshape(res, res)

    # --- дальний план: верхняя огибающая меша на сетке 12 м
    x0, z0 = P[:, 0].min(), P[:, 2].min()
    nx = int((P[:, 0].max() - x0) / COARSE_CELL) + 1
    nz = int((P[:, 2].max() - z0) / COARSE_CELL) + 1
    print("дальний план: сетка %d×%d по %.0f м" % (nx, nz, COARSE_CELL))
    cov, hmax = raster(P, I, x0, z0, COARSE_CELL, nx, nz)
    valid = cov
    h = np.where(valid, hmax, np.nan)
    init = np.where(valid, hmax, float(np.median(hmax[valid])))
    h = harmonic_fill(init, valid, iters=1500)
    h = limit_slope(h, valid, COARSE_CELL, max_step=1.2)
    # крышки над провалами: всё, что заметно ниже локальной поверхности
    surf = local_surface(h, valid, win=5)
    pits = valid & (h < surf - 8.0)
    h = np.where(pits, surf - 0.2, h)

    inside_fine = ((x0 + np.arange(nx) * COARSE_CELL)[None, :] >= hx0) & \
                  ((x0 + np.arange(nx) * COARSE_CELL)[None, :] <= hx1) & \
                  ((z0 + np.arange(nz) * COARSE_CELL)[:, None] >= hz0) & \
                  ((z0 + np.arange(nz) * COARSE_CELL)[:, None] <= hz1)
    coarse_cells = (h > SEA_LEVEL + MIN_LAND) & ~inside_fine
    print("  суша: %d клеток, из них рисуем %d" % (int((h > SEA_LEVEL).sum()),
                                                   int(coarse_cells.sum())))

    # --- ближний план: сетка 1 м по карте высот
    fine_cells = np.ones((res - 1, res - 1), bool)
    print("ближний план: площадка %.0f×%.0f м" % (hx1 - hx0, hz1 - hz0))

    g = glbw.GLB("IslandTerrain")
    prims = []
    for name, cells, heights, cell, cnx, cnz, cx0, cz0 in (
            ("terrain_far", coarse_cells, h, COARSE_CELL, nx, nz, x0, z0),
            ("terrain_near", fine_cells, fine, hcell, res, res, hx0, hz0)):
        prim = grid_mesh(cells, heights, cell, cnx, cnz, cx0, cz0, name)
        if prim:
            prims.append(prim)
    if not prims:
        raise SystemExit("терраин пуст")
    mesh = g.mesh("IslandTerrain", prims)
    root = g.node("IslandTerrain", mesh=mesh)
    g.g["scenes"][0]["nodes"] = [root]
    size = g.write(OUT)
    print("island_terrain.glb %s МБ → %s" % (round(size / 1e6, 2), OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
