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
OUTER_CELL = 6.0        # м
OUTER_RADIUS = 2000.0   # м от центра арены
SINK = 0.15             # м ниже меша, чтобы не мерцать на стыках
MIN_LAND_Y = 60.0       # ниже — считаем водой, дыры там не нужны


def raster(P, I, x0, z0, cell, nx, nz):
    """Покрытие и максимальная высота меша по клеткам сетки."""
    cov = np.zeros((nz, nx), bool)
    hmax = np.full((nz, nx), -1e9)
    xs = x0 + (np.arange(nx) + 0.5) * cell
    zs = z0 + (np.arange(nz) + 0.5) * cell
    a2 = np.linalg.norm(np.cross(P[I][:, 1] - P[I][:, 0], P[I][:, 2] - P[I][:, 0]), axis=1)
    for t, area in zip(P[I], a2 * 0.5):
        if area < 1.0 or t[:, 1].max() < 0.0:
            continue          # вырожденные/скрытые треугольники и вода
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


def local_surface(h, valid, win=7):
    """Локальная медиана высот по валидным клеткам (без scipy)."""
    stack = []
    half = win // 2
    for dy in range(-half, half + 1):
        for dx in range(-half, half + 1):
            sh = shift(h, dy, dx)
            sk = shift(valid.astype(float), dy, dx) > 0.5
            stack.append(np.where(sk, sh, np.nan))
    arr = np.stack(stack)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(arr, axis=0)
    return np.where(np.isnan(med), h, med)


PAD = 16


def shift(a, dy, dx):
    """Сдвиг массива с повтором краёв (np.roll заворачивает и портит границы)."""
    pad = np.pad(a, PAD, mode="edge")
    y, x = PAD + dy, PAD + dx
    return pad[y:y + a.shape[0], x:x + a.shape[1]]


def neighbours(a):
    return [shift(a, -1, 0), shift(a, 1, 0), shift(a, 0, -1), shift(a, 0, 1)]


def limit_slope(h, valid, cell, max_step=1.0, iters=200):
    """Ограничиваем перепад между соседними клетками дыры.

    Без этого в заплатке остаются ступеньки в десятки метров: получаются
    вертикальные «иглы», каждая из которых затеняет соседнюю (на кадрах —
    шахматка чёрных треугольников).
    """
    h = h.copy()
    lim = max_step * cell
    for _ in range(iters):
        nb = neighbours(h)
        mn = np.minimum.reduce(nb)
        mx = np.maximum.reduce(nb)
        h = np.where(valid, h, np.clip(h, mn - lim, mx + lim))
    return h


def harmonic_fill(h, valid, iters=2000, tol=1e-3):
    """Гармоническая интерполяция высот в дырах (решение Лапласа, Якоби).

    Копирование высот от ближайшего треугольника даёт скачок на границе дыры
    (в heightmap дыры экстраполированы и расходятся с мешем на десятки метров),
    а сглаживание в лоб — «пилу». Лаплас по построению гладкий и точно совпадает
    с мешем на границе: получается пологий лоскут без ступенек.
    """
    h = h.copy()
    for i in range(iters):
        nb = sum(neighbours(h)) * 0.25
        new = np.where(valid, h, nb)
        delta = float(np.abs(new - h).max())
        h = new
        if delta < tol:
            print("    заливка сошлась за %d итераций (d=%.1e м)" % (i + 1, delta))
            break
    return h


def build_mesh(cells, h, cell, nx, nz, x0, z0, name, dist=None,
               max_dist=30.0, max_step=4.0):
    """Квады по клеткам-дырам.

    Клетки, где высота восстановлена слишком далеко от меша (dist > max_dist),
    пропускаем. На крутых местах (перепад на клетке больше max_step её
    размеров) квад не выбрасываем, а прижимаем его вершины к нижнему углу:
    получается пологий лоскут, а не вертикальная стена.
    """
    limit = max_step * cell

    verts = np.zeros((nz * nx, 3), np.float32)
    uvs = np.zeros((nz * nx, 2), np.float32)
    for iz in range(nz):
        for ix in range(nx):
            k = iz * nx + ix
            x = x0 + ix * cell
            z = z0 + iz * cell
            verts[k] = (x, h[iz, ix] - SINK, z)
            uvs[k] = (x * UV_U_PER_M + UV_U_OFFSET, z * UV_V_PER_M + UV_V_OFFSET)
    # нормали — вверх: в дырах высоты восстановлены грубо, и градиент из них
    # даёт почти горизонтальные нормали, отчего заплатка рисуется чёрной
    normals = np.zeros_like(verts)
    normals[:, 1] = 1.0

    extra_v, extra_u = [], []
    tris = []
    skipped = 0
    flattened = 0
    for iz in range(nz - 1):
        for ix in range(nx - 1):
            if not cells[iz, ix]:
                continue
            idx = [iz * nx + ix, iz * nx + ix + 1, (iz + 1) * nx + ix, (iz + 1) * nx + ix + 1]
            if dist is not None and max(dist.reshape(-1)[i] for i in idx) > max_dist:
                skipped += 1
                continue
            ys = [verts[i][1] for i in idx]
            if max(ys) - min(ys) > limit:
                base = min(ys)
                new_idx = []
                for i in idx:
                    v = verts[i].copy()
                    if v[1] > base + limit:
                        v[1] = base + limit
                    extra_v.append(v)
                    extra_u.append(uvs[i])
                    new_idx.append(len(verts) + len(extra_v) - 1)
                idx = new_idx
                flattened += 1
            a, b, c, d = idx          # a=(ix,iz) b=(ix+1,iz) c=(ix,iz+1) d=(ix+1,iz+1)
            # обход против часовой при взгляде сверху: нормаль смотрит вверх
            # ((a,b,c) дало бы нормаль вниз и тёмные треугольники)
            tris.append((a, c, b))
            tris.append((b, c, d))
    if not tris:
        print("  %-14s пусто" % name)
        return None
    V = np.vstack([verts, np.array(extra_v, np.float32)]) if extra_v else verts
    U = np.vstack([uvs, np.array(extra_u, np.float32)]) if extra_u else uvs
    N = np.zeros_like(V)
    N[:, 1] = 1.0
    N[:len(normals)] = normals
    F = np.array(tris, np.uint32)
    used = np.unique(F)
    remap = np.full(len(V), -1, np.int64)
    remap[used] = np.arange(len(used))
    print("  %-14s квадов %6d (прижато крутых %4d, пропущено далёких %4d), треугольников %6d"
          % (name, len(tris) // 2, flattened, skipped, len(F)))
    return {'attributes': {'POSITION': V[used].astype(np.float32),
                           'NORMAL': N[used].astype(np.float32),
                           'TEXCOORD_0': U[used].astype(np.float32)},
            'indices': remap[F].reshape(-1)}


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
    cov, hmax = raster(P, I, hx0, hz0, hcell, res, res)
    # в меше есть второй, нижний слой поверхности (морское дно): клетка, где
    # треугольник лежит на десятки метров ниже карты высот, — это не земля,
    # сквозь неё просвечивает тёмное дно. Считаем такие клетки дырами.
    cov = cov & (np.abs(hmax - heights) < 3.0)
    print("  покрытие 1 м: %d клеток" % int(cov.sum()))
    inner_holes = np.ones_like(cov)          # вся площадка
    inner_cells = inner_holes[:res - 1, :res - 1]
    print("  дыр %d из %d клеток" % (int((~cov).sum()), cov.size))
    # heightmap в дырах экстраполирован и местами врёт на десятки метров
    # (перепад 47 м на одной клетке) — сглаживаем и ограничиваем уклон,
    # иначе на месте дыры встаёт вертикальная стена
    # высоты берём из самого меша (hmax), а не из карты высот: в дырах карта
    # экстраполирована и расходится с мешем на десятки метров
    # высоты — из карты высот (она перепечена из этого же меша и в дырах
    # залита гармонически), это гарантирует совпадение с коллизией
    inner_h = heights.copy()
    inner_h = limit_slope(inner_h, cov, hcell, max_step=0.5)

    print("внешняя сетка (%g м, радиус %g м)" % (OUTER_CELL, OUTER_RADIUS))
    ox0 = ax - OUTER_RADIUS
    oz0 = az - OUTER_RADIUS
    onx = onz = int(round(2 * OUTER_RADIUS / OUTER_CELL))
    cov_o_raw, h_o = raster(P, I, ox0, oz0, OUTER_CELL, onx, onz)
    cov_o = cov_o_raw
    # то же снаружи: сравниваем с локальной медианой поверхности
    cov_o = cov_o & (h_o > local_surface(h_o, cov_o) - 20.0)
    valid = cov_o
    print("  покрытие меша %d, после фильтра нижнего слоя %d" % (int(cov_o_raw.sum()), int(cov_o.sum())))
    init = np.where(valid, h_o, float(np.median(h_o[valid])))
    h_filled = harmonic_fill(init, valid, iters=1500)
    fill_dist = np.zeros_like(h_o)
    fill_dist = np.where(cov_o, 0.0, fill_dist)
    h_filled = limit_slope(h_filled, cov_o, OUTER_CELL, max_step=0.5)
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
    inner = build_mesh(inner_cells, inner_h, hcell, res, res, hx0, hz0,
                       "fill_inner", max_dist=None, max_step=1e6)
    if inner:
        prims.append(inner)
    outer = None   # внешние заплатки не нужны: дыры у арены закрывает сетка 1 м
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
