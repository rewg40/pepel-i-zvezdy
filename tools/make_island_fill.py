#!/usr/bin/env python3
"""Заплатки земли в дырах меша острова → game/models/island_fill.glb.

Меш терраина island.glb не сплошной: участки без единого треугольника есть и
у арены (13.8 % площади heightmap), и по всему острову (~5 % суши). Сквозь них
видно пустоту — на кадрах это чёрные «стрелки» посреди песка.

Здесь считаем покрытие меша в двух сетках и строим геометрию только по дырам:

* внутренняя — 1 м, ровно по heightmap.f32 (там же, где коллизия), поэтому
  заплатка точно совпадает с землёй, по которой ходит игрок;
* внешняя — 4 м в радиусе 900 м от арены, высоты по мешу с заливкой от
  соседних клеток (дальние дыры на горизонте).

UV — та же аффинная развёртка, что у острова (u = x*5e-5+0.499974,
v = z*7e-5+0.505151), материал игра назначает сама (shaders/ground.gdshader).

    python3 tools/make_island_fill.py      # → game/models/island_fill.glb
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glb_io  # noqa: E402
import glbw  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GLB = os.path.join(ROOT, "game", "models", "island.glb")
HM_JSON = os.path.join(ROOT, "game", "models", "heightmap.json")
HM_F32 = os.path.join(ROOT, "game", "models", "heightmap.f32")
OUT = os.path.join(ROOT, "game", "models", "island_fill.glb")

UV_U_PER_M, UV_U_OFFSET = 5.0e-5, 0.499974
UV_V_PER_M, UV_V_OFFSET = 7.0e-5, 0.505151

INNER_DILATE = 2        # клеток: заплатка заходит под соседние треугольники
OUTER_CELL = 4.0        # м
OUTER_RADIUS = 900.0    # м от центра арены
SINK = 0.15             # м ниже меша, чтобы не мерцать на стыках
MIN_LAND_Y = 60.0       # ниже — считаем водой, дыры там не нужны


def raster(P, I, x0, z0, cell, nx, nz):
    """Покрытие и максимальная высота меша по клеткам сетки."""
    cov = np.zeros((nz, nx), bool)
    hmax = np.full((nz, nx), -1e9)
    xs = x0 + (np.arange(nx) + 0.5) * cell
    zs = z0 + (np.arange(nz) + 0.5) * cell
    for t in P[I]:
        if t[:, 1].max() < 0.0:
            continue
        ix0 = max(int((t[:, 0].min() - x0) / cell) - 1, 0)
        ix1 = min(int((t[:, 0].max() - x0) / cell) + 2, nx)
        iz0 = max(int((t[:, 2].min() - z0) / cell) - 1, 0)
        iz1 = min(int((t[:, 2].max() - z0) / cell) + 2, nz)
        if ix1 <= ix0 or iz1 <= iz0:
            continue
        PX, PZ = np.meshgrid(xs[ix0:ix1], zs[iz0:iz1])
        d = (t[1, 0] - t[0, 0]) * (t[2, 2] - t[0, 2]) - (t[2, 0] - t[0, 0]) * (t[1, 2] - t[0, 2])
        if abs(d) < 1e-12:
            continue
        b1 = ((PX - t[0, 0]) * (t[2, 2] - t[0, 2]) - (t[2, 0] - t[0, 0]) * (PZ - t[0, 2])) / d
        b2 = ((t[1, 0] - t[0, 0]) * (PZ - t[0, 2]) - (PX - t[0, 0]) * (t[1, 2] - t[0, 2])) / d
        b0 = 1 - b1 - b2
        m = (b0 >= -1e-6) & (b1 >= -1e-6) & (b2 >= -1e-6)
        if not m.any():
            continue
        y = b0 * t[0, 1] + b1 * t[1, 1] + b2 * t[2, 1]
        sub = hmax[iz0:iz1, ix0:ix1]
        sub[m] = np.maximum(sub[m], y[m])
        cov[iz0:iz1, ix0:ix1] |= m
    return cov, hmax


def dilate(mask, n):
    out = mask.copy()
    for _ in range(n):
        g = out.copy()
        g[1:] |= out[:-1]
        g[:-1] |= out[1:]
        g[:, 1:] |= out[:, :-1]
        g[:, :-1] |= out[:, 1:]
        out = g
    return out


def fill_nearest(h, valid):
    """Заливка высот от соседних валидных клеток (без scipy).

    Возвращает (высоты, расстояние до ближайшей валидной клетки в клетках):
    по расстоянию отбрасываем клетки, где высота «приехала» издалека — из
    таких получаются вертикальные простыни вместо земли.
    """
    h = h.copy()
    known = valid.copy()
    dist = np.where(valid, 0.0, np.inf)
    for _ in range(128):
        if known.all():
            break
        acc = np.zeros_like(h)
        cnt = np.zeros_like(h)
        nd = np.full_like(h, np.inf)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sh = np.roll(np.roll(h, dy, 0), dx, 1)
            sk = np.roll(np.roll(known, dy, 0), dx, 1)
            sd = np.roll(np.roll(dist, dy, 0), dx, 1)
            acc += np.where(sk, sh, 0.0)
            cnt += sk
            nd = np.minimum(nd, np.where(sk, sd, np.inf))
        grow = (~known) & (cnt > 0)
        h[grow] = acc[grow] / cnt[grow]
        dist[grow] = nd[grow] + 1.0
        known |= grow
    return h, dist


def smooth_holes(h, valid, iters=60):
    """Сглаживание восстановленных высот внутри дыр (границы не трогаем):
    без него в больших дырах остаются ступеньки и «простыни»."""
    h = h.copy()
    for _ in range(iters):
        nb = (np.roll(h, 1, 0) + np.roll(h, -1, 0)
              + np.roll(h, 1, 1) + np.roll(h, -1, 1)) / 4.0
        h = np.where(valid, h, nb)
    return h


def limit_slope(h, valid, cell, max_step=1.5, iters=80):
    """Ограничиваем уклон восстановленных высот: клетка не может отличаться от
    соседей больше чем на max_step клеток. Так вместо вертикальных простыней
    получается пологий склон, и ни одну клетку не нужно выбрасывать."""
    h = h.copy()
    lim = max_step * cell
    for _ in range(iters):
        nb = [np.roll(h, 1, 0), np.roll(h, -1, 0), np.roll(h, 1, 1), np.roll(h, -1, 1)]
        mn = np.minimum.reduce(nb)
        mx = np.maximum.reduce(nb)
        h = np.where(valid, h, np.clip(h, mn - lim, mx + lim))
    return h


def build_mesh(cells, h, cell, nx, nz, x0, z0, name, dist=None,
               max_dist=6.0, max_step=3.0):
    """Квады по клеткам-дырам.

    Клетка пропускается, если её высота восстановлена слишком далеко от меша
    (dist > max_dist клеток) или перепад на клетке больше max_step её размеров:
    из таких получаются вертикальные простыни и иглы.
    """
    verts = np.zeros((nz * nx, 3), np.float32)
    uvs = np.zeros((nz * nx, 2), np.float32)
    for iz in range(nz):
        z = z0 + iz * cell
        for ix in range(nx):
            x = x0 + ix * cell
            k = iz * nx + ix
            verts[k] = (x, h[iz, ix] - SINK, z)
            uvs[k] = (x * UV_U_PER_M + UV_U_OFFSET, z * UV_V_PER_M + UV_V_OFFSET)
    gy, gx = np.gradient(h, cell)
    normals = np.zeros_like(verts)
    normals[:, 0] = (-gx).reshape(-1)
    normals[:, 1] = 1.0
    normals[:, 2] = (-gy).reshape(-1)
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-9)

    limit = max_step * cell
    quads = []
    skipped = 0
    for iz in range(nz - 1):
        for ix in range(nx - 1):
            if not cells[iz, ix]:
                continue
            corners = [h[iz, ix], h[iz, ix + 1], h[iz + 1, ix], h[iz + 1, ix + 1]]
            if max(corners) - min(corners) > limit:
                skipped += 1
                continue
            if dist is not None:
                d = [dist[iz, ix], dist[iz, ix + 1], dist[iz + 1, ix], dist[iz + 1, ix + 1]]
                if max(d) > max_dist:
                    skipped += 1
                    continue
            a = iz * nx + ix
            quads.append((a, a + nx, a + 1, a + 1, a + nx, a + nx + 1))
    if not quads:
        print("  %-14s пусто" % name)
        return None
    F = np.array(quads, np.uint32).reshape(-1, 3)
    used = np.unique(F)
    remap = np.full(len(verts), -1, np.int64)
    remap[used] = np.arange(len(used))
    V, N, U = verts[used], normals[used], uvs[used]
    F = remap[F]
    print("  %-14s клеток %6d (пропущено крутых %4d), треугольников %6d"
          % (name, len(quads), skipped, len(F)))
    return {'attributes': {'POSITION': V, 'NORMAL': N, 'TEXCOORD_0': U},
            'indices': F.reshape(-1)}


def main() -> int:
    js, blob = glb_io.load_glb(GLB)
    pr = js["meshes"][0]["primitives"][0]
    P = glb_io.accessor(js, blob, pr["attributes"]["POSITION"]).astype(np.float64)
    I = glb_io.accessor(js, blob, pr["indices"]).reshape(-1, 3).astype(np.int64)

    hm = json.load(open(HM_JSON))
    res = int(hm["res"])
    hx0, hz0, hcell = float(hm["x0"]), float(hm["z0"]), float(hm["cell"])
    hx1 = hx0 + (res - 1) * hcell
    hz1 = hz0 + (res - 1) * hcell
    heights = np.fromfile(HM_F32, dtype="<f4").astype(np.float64).reshape(res, res)

    with open(os.path.join(ROOT, "game", "models", "arena.json")) as fh:
        arena = json.load(fh)
    ax, az = float(arena["x"]), float(arena["z"])

    print("внутренняя сетка (1 м, высоты из heightmap.f32)")
    cov, _ = raster(P, I, hx0, hz0, hcell, res, res)
    inner_holes = dilate(~cov, INNER_DILATE)
    inner_cells = inner_holes[:res - 1, :res - 1]
    print("  дыр %d из %d клеток" % (int((~cov).sum()), cov.size))

    print("внешняя сетка (%g м, радиус %g м)" % (OUTER_CELL, OUTER_RADIUS))
    ox0 = ax - OUTER_RADIUS
    oz0 = az - OUTER_RADIUS
    onx = onz = int(round(2 * OUTER_RADIUS / OUTER_CELL))
    cov_o, h_o = raster(P, I, ox0, oz0, OUTER_CELL, onx, onz)
    valid = cov_o
    h_filled, fill_dist = fill_nearest(np.where(valid, h_o, 0.0), valid)
    fill_dist = np.where(cov_o, 0.0, fill_dist)
    h_filled = smooth_holes(h_filled, cov_o)
    h_filled = limit_slope(h_filled, cov_o, OUTER_CELL)
    # дыры только там, где рядом суша (иначе это океан и он закрыт водой)
    land = h_filled > MIN_LAND_Y
    # все непокрытые клетки суши: крупные дыры целиком (раньше внутренность
    # больших дыр отбрасывалась и на кадрах оставались чёрные «стрелки»)
    holes_o = (~valid) & land
    # внутренний прямоугольник отдаём 1-м заплатке
    xs = ox0 + (np.arange(onx) + 0.5) * OUTER_CELL
    zs = oz0 + (np.arange(onz) + 0.5) * OUTER_CELL
    inside_inner = ((xs[None, :] > hx0) & (xs[None, :] < hx1)
                    & (zs[:, None] > hz0) & (zs[:, None] < hz1))
    outer_cells = (holes_o & ~inside_inner)[:onz - 1, :onx - 1]
    print("  дыр-клеток %d, из них в зоне арены %d"
          % (int(holes_o.sum()), int((holes_o & inside_inner).sum())))

    g = glbw.GLB("IslandFill")
    prims = []
    inner = build_mesh(inner_cells, heights, hcell, res, res, hx0, hz0,
                       "fill_inner", max_dist=None, max_step=1e6)  # высоты из heightmap — не отбрасываем
    if inner:
        prims.append(inner)
    outer = build_mesh(outer_cells, h_filled, OUTER_CELL, onx, onz, ox0, oz0,
                       "fill_outer", dist=fill_dist, max_dist=30.0, max_step=6.0)
    if outer:
        prims.append(outer)
    if not prims:
        raise SystemExit("заплаток нет — дыры не найдены?")
    mesh = g.mesh("IslandFill", prims)
    root = g.node("IslandFill", mesh=mesh)
    g.g["scenes"][0]["nodes"] = [root]
    size = g.write(OUT)
    print("island_fill.glb", round(size / 1e6, 2), "МБ →", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
