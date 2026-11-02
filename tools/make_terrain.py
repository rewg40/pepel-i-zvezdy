#!/usr/bin/env python3
"""Собрать терраин острова из ИСХОДНОГО меша → game/models/island_terrain.glb.

Почему не из game/models/island.glb: там остров уже децимирован, и децимация
оставила у арены плоскости размером в километр. Карта высот по такому мешу —
это несколько гигантских наклонных плоскостей с обрывами в десятки метров,
поэтому в игре на земле появлялись ступени и светлые «плиты», а между ними
чёрные провалы. Исходный меш (остров/2 остров улучшенный.zip) состоит из
плоских фасеток ~30-40 м — это и есть вид модели, и по нему высоты читаются
ровно.

Терраин собирается так:

* ближний план (площадка арены 220×220 м) — сетка 1 м по высотам исходного
  меша; эта же карта пишется в game/models/heightmap.f32 и используется
  для коллизии, поэтому игрок ходит ровно по нарисованному;
* остальной остров — сетка 24 м по верхней огибающей исходного меша, с
  гармонической заливкой дыр;
* нормали считаются по полю высот (свет ложится как на модели);
* UV — та же аффинная развёртка, что у исходного меша, поэтому рис багета
  (атлас с бежевыми разводами) совпадает с текстурой модели.

    python3 tools/make_terrain.py        # → game/models/island_terrain.glb
"""
import json
import os
import struct
import zipfile
import zlib

import numpy as np

import glb_io
import glbw
from PIL import Image

from make_island_fill import raster, shift

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE = [os.path.join(ROOT, "остров", "2 остров улучшенный.z01"),
           os.path.join(ROOT, "остров", "2 остров улучшенный.z02"),
           os.path.join(ROOT, "остров", "2 остров улучшенный.zip")]
SRC_CACHE = "/tmp/island_src.glb"
HM_JSON = os.path.join(ROOT, "game", "models", "heightmap.json")
HM_F32 = os.path.join(ROOT, "game", "models", "heightmap.f32")
HM_PNG = os.path.join(ROOT, "game", "models", "heightmap.png")
OUT = os.path.join(ROOT, "game", "models", "island_terrain.glb")

UV_U_PER_M, UV_U_OFFSET = 5.0e-5, 0.499974
UV_V_PER_M, UV_V_OFFSET = 7.0e-5, 0.505151

COARSE_CELL = 24.0      # м, дальний план
SEA_LEVEL = 0.0         # м, уровень воды исходной модели (Ocean стоит на y=0)
BLEND_METERS = 96.0     # плавный переход ближней сетки в дальнюю
FINE_FILL_ITERS = 800


def extract_source(dst=SRC_CACHE):
    """Склеить части zip и распаковать единственный glb внутрь (unzip не умеет
    многотомные архивы, а нам нужен только один поток deflate)."""
    if os.path.exists(dst) and os.path.getsize(dst) > 1e8:
        return dst
    data = b"".join(open(p, "rb").read() for p in ARCHIVE)
    i = data.find(b"PK\x03\x04")
    if i < 0:
        raise SystemExit("не нашли локальный заголовок zip")
    _, _, _, method, _, _, _, _, _, nl, el = struct.unpack("<IHHHHHIIIHH", data[i:i + 30])
    if method != 8:
        raise SystemExit("ожидали deflate, а там метод %d" % method)
    dec = zlib.decompressobj(-15)
    out = bytearray()
    p = i + 30 + nl + el
    while p < len(data) and not dec.eof:
        chunk = data[p:p + (1 << 22)]
        out += dec.decompress(chunk)
        p += len(chunk)
    out += dec.flush()
    open(dst, "wb").write(out)
    print("исходный остров: %s (%.0f МБ)" % (dst, len(out) / 1e6))
    return dst


def harmonic_fill(h, valid, iters=2000, tol=1e-3):
    h = h.copy()
    for _ in range(iters):
        nb = (shift(h, -1, 0) + shift(h, 1, 0) + shift(h, 0, -1) + shift(h, 0, 1)) * 0.25
        new = np.where(valid, h, nb)
        delta = float(np.abs(new - h).max())
        h = new
        if delta < tol:
            break
    return h


def grid_normals(h, cell):
    """Нормали по полю высот: центральные разности."""
    dhx = np.zeros_like(h)
    dhz = np.zeros_like(h)
    dhx[:, 1:-1] = (h[:, 2:] - h[:, :-2]) / (2 * cell)
    dhz[1:-1, :] = (h[2:, :] - h[:-2, :]) / (2 * cell)
    dhx[:, 0], dhx[:, -1] = dhx[:, 1], dhx[:, -2]
    dhz[0, :], dhz[-1, :] = dhz[1, :], dhz[-2, :]
    N = np.stack([-dhx.ravel(), np.ones(h.size), -dhz.ravel()], axis=1)
    N /= np.linalg.norm(N, axis=1, keepdims=True)
    return N.astype(np.float32)


def grid_mesh(cells, h, cell, nx, nz, x0, z0, name):
    """Квады по клеткам cells; обход против часовой → нормали вверх."""
    xs = x0 + np.arange(nx) * cell
    zs = z0 + np.arange(nz) * cell
    X, Z = np.meshgrid(xs, zs)
    V = np.stack([X.ravel(), h.ravel(), Z.ravel()], axis=1).astype(np.float32)
    U = np.stack([(X * UV_U_PER_M + UV_U_OFFSET).ravel(),
                  (Z * UV_V_PER_M + UV_V_OFFSET).ravel()], axis=1).astype(np.float32)
    N = grid_normals(h, cell)

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
    src = extract_source()
    js, blob = glb_io.load_glb(src)
    pr = js["meshes"][0]["primitives"][0]
    P = glb_io.accessor(js, blob, pr["attributes"]["POSITION"]).astype(np.float64)
    I = glb_io.accessor(js, blob, pr["indices"]).reshape(-1, 3).astype(np.int64)
    print("исходный терраин: %d вершин, %d треугольников" % (len(P), len(I)))

    hm = json.load(open(HM_JSON))
    res = int(hm["res"])
    hcell = float(hm["cell"])
    hx0, hz0 = float(hm["x0"]), float(hm["z0"])
    hx1 = hx0 + (res - 1) * hcell
    hz1 = hz0 + (res - 1) * hcell

    # --- ближний план: 1 м по высотам исходного меша (он же коллизия)
    cov, fine = raster(P, I, hx0, hz0, hcell, res, res)
    if not cov.all():
        print("  дыр в ближней карте: %d клеток" % int((~cov).sum()))
        seed = float(np.median(fine[cov]))
        fine = harmonic_fill(np.where(cov, fine, seed), cov, iters=FINE_FILL_ITERS)
    else:
        fine = np.where(cov, fine, SEA_LEVEL)
    fine = np.maximum(fine, SEA_LEVEL)
    fine.astype("<f4").tofile(HM_F32)
    # запасной путь для игры: 8-битная PNG копия той же карты
    y_min, y_max = float(fine.min()), float(fine.max())
    hm_meta = json.load(open(HM_JSON))
    hm_meta["y_min"], hm_meta["y_max"] = y_min, y_max
    json.dump(hm_meta, open(HM_JSON, "w"), indent=1)
    png = (np.clip((fine - y_min) / max(y_max - y_min, 1e-6), 0, 1) * 255.0)
    try:
        Image.fromarray(png.astype(np.uint8), "L").save(HM_PNG)
    except Exception as exc:                       # pragma: no cover
        print("  heightmap.png не переписан:", exc)
    print("  карта высот %d×%d по %.1f м: y %.1f…%.1f → %s"
          % (res, res, hcell, fine.min(), fine.max(), os.path.basename(HM_F32)))

    # --- дальний план: 24 м по верхней огибающей исходного меша
    x0 = np.floor(P[:, 0].min() / COARSE_CELL) * COARSE_CELL
    z0 = np.floor(P[:, 2].min() / COARSE_CELL) * COARSE_CELL
    nx = int(np.ceil((P[:, 0].max() - x0) / COARSE_CELL)) + 1
    nz = int(np.ceil((P[:, 2].max() - z0) / COARSE_CELL)) + 1
    print("дальний план: сетка %d×%d по %.0f м" % (nx, nz, COARSE_CELL))
    valid, hmax = raster(P, I, x0, z0, COARSE_CELL, nx, nz)
    h = harmonic_fill(np.where(valid, hmax, SEA_LEVEL), valid, iters=1500)

    # --- узлы грубой сетки внутри площадки берём из ближней карты и плавно
    #     переходим к дальнему плану за BLEND_METERS от её края
    gx = x0 + np.arange(nx) * COARSE_CELL
    gz = z0 + np.arange(nz) * COARSE_CELL
    GX, GZ = np.meshgrid(gx, gz)
    cx = np.clip(GX, hx0, hx1)
    cz = np.clip(GZ, hz0, hz1)
    fx = np.clip((cx - hx0) / hcell, 0, res - 1.0001)
    fz = np.clip((cz - hz0) / hcell, 0, res - 1.0001)
    ix, iz = np.floor(fx).astype(int), np.floor(fz).astype(int)
    tx, tz = fx - ix, fz - iz
    near_h = (fine[iz, ix] * (1 - tx) * (1 - tz) + fine[iz, ix + 1] * tx * (1 - tz)
              + fine[iz + 1, ix] * (1 - tx) * tz + fine[iz + 1, ix + 1] * tx * tz)
    dx = np.maximum(np.maximum(hx0 - GX, GX - hx1), 0)
    dz = np.maximum(np.maximum(hz0 - GZ, GZ - hz1), 0)
    dist = np.hypot(dx, dz)
    w = np.clip(1.0 - dist / BLEND_METERS, 0.0, 1.0) ** 2
    h = near_h * w + h * (1.0 - w)

    h = np.maximum(h, SEA_LEVEL)
    inside = dist <= 0.0
    coarse_cells = valid & ~inside
    print("  суша: %d клеток, рисуем %d" % (int(valid.sum()), int(coarse_cells.sum())))

    # --- ближняя сетка у самого края тоже подтягиваем к дальнему плану,
    #     чтобы на стыке не было щели
    fxg = hx0 + np.arange(res)[None, :] * hcell
    fzg = hz0 + np.arange(res)[:, None] * hcell
    d_edge = np.minimum(np.minimum(fxg - hx0, hx1 - fxg),
                        np.minimum(fzg - hz0, hz1 - fzg))
    we = np.clip(1.0 - d_edge / (hcell * 2.0), 0.0, 1.0)
    cix = np.clip(np.round((np.broadcast_to(fxg, fine.shape) - x0) / COARSE_CELL),
                  0, nx - 1).astype(int)
    ciz = np.clip(np.round((np.broadcast_to(fzg, fine.shape) - z0) / COARSE_CELL),
                  0, nz - 1).astype(int)
    fine = fine * (1.0 - we) + h[ciz, cix] * we

    g = glbw.GLB("IslandTerrain")
    prims = []
    for name, cells, heights, cell, cnx, cnz, cx0, cz0 in (
            ("terrain_far", coarse_cells, h, COARSE_CELL, nx, nz, x0, z0),
            ("terrain_near", np.ones((res - 1, res - 1), bool), fine, hcell, res, res,
             hx0, hz0)):
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
