#!/usr/bin/env python3
"""Починить нормали терраина острова (game/models/island.glb) на месте.

В исходном меше почти половина треугольников (231 585 из 500 000, 46 %)
закручена в обратную сторону: геометрическая нормаль смотрит вниз, а
усреднённые по вершинам нормали получаются мусорными. Из-за этого земля
освещается с изнанки — на кадрах это чёрные «стрелки» посреди песка и общий
пересвет рядом с ними.

Терраин — это поверхность высот, поэтому правильная нормаль всегда смотрит
вверх. Делаем две вещи:

1. разворачиваем обход (winding) у треугольников, чья геометрическая нормаль
   смотрит вниз, — иначе движок считает их изнанкой и переворачивает нормаль,
   отчего они всё равно освещаются снизу и рисуются тёмными;
2. пересчитываем NORMAL по вершинам, взвешивая площадью, — получаем гладкое
   освещение, согласованное с рельефом.

Позиции не меняются: правим только буферы индексов и нормалей.

Заодно убираем второй, нижний слой поверхности: в зоне heightmap часть
треугольников лежит на 10–45 м ниже настоящей земли. Сверху они выглядят
чёрными плитами (дно/подложка), сквозь них не видно песка. Такие треугольники
схлопываем в вырожденные (все индексы в одну вершину) — они перестают
рисоваться, а дыры закрывает заплатка tools/make_island_fill.py.

    python3 tools/fix_terrain_normals.py            # правит island.glb
    python3 tools/fix_terrain_normals.py --check    # только отчёт
"""
import json
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glb_io  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GLB = os.path.join(ROOT, "game", "models", "island.glb")
HM_JSON = os.path.join(ROOT, "game", "models", "heightmap.json")
HM_F32 = os.path.join(ROOT, "game", "models", "heightmap.f32")
LOWER_LAYER_DEPTH = 10.0   # м ниже карты высот — это не земля
TERRAIN_MESH = 0


def read_glb(path):
    raw = open(path, "rb").read()
    magic, version, length = struct.unpack_from("<4sII", raw, 0)
    assert magic == b"glTF" and version == 2, "не GLB v2"
    off = 12
    js = bin_chunk = None
    while off < length:
        clen, ctype = struct.unpack_from("<II", raw, off)
        data = raw[off + 8:off + 8 + clen]
        if ctype == 0x4E4F534A:
            js = json.loads(data.decode("utf-8"))
        elif ctype == 0x004E4942:
            bin_chunk = bytearray(data)
        off += 8 + clen
    return js, bin_chunk


def write_glb(path, js, bin_chunk):
    payload = json.dumps(js, separators=(",", ":")).encode()
    while len(payload) % 4:
        payload += b" "
    while len(bin_chunk) % 4:
        bin_chunk += b"\0"
    total = 12 + 8 + len(payload) + 8 + len(bin_chunk)
    out = bytearray(struct.pack("<4sII", b"glTF", 2, total))
    out += struct.pack("<II", len(payload), 0x4E4F534A) + payload
    out += struct.pack("<II", len(bin_chunk), 0x004E4942) + bytes(bin_chunk)
    with open(path, "wb") as fh:
        fh.write(out)


def accessor_offset(js, index):
    acc = js["accessors"][index]
    view = js["bufferViews"][acc["bufferView"]]
    assert acc["componentType"] == 5126 and acc["type"] == "VEC3", "ожидались float32 vec3"
    assert "byteStride" not in view, "ожидался плотно упакованный буфер"
    assert view["buffer"] == 0
    return view["byteOffset"] + acc.get("byteOffset", 0), acc["count"]


def main() -> int:
    check = "--check" in sys.argv
    js, blob = read_glb(GLB)
    prim = js["meshes"][TERRAIN_MESH]["primitives"][0]
    pos_off, count = accessor_offset(js, prim["attributes"]["POSITION"])
    nrm_off, n_count = accessor_offset(js, prim["attributes"]["NORMAL"])
    idx_acc = js["accessors"][prim["indices"]]
    idx_view = js["bufferViews"][idx_acc["bufferView"]]
    idx_off = idx_view["byteOffset"] + idx_acc.get("byteOffset", 0)
    iw = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32}[idx_acc["componentType"]]

    P = np.frombuffer(bytes(blob[pos_off:pos_off + count * 12]), np.float32).reshape(-1, 3).astype(np.float64)
    F = np.frombuffer(bytes(blob[idx_off:idx_off + idx_acc["count"] * 4]), iw).astype(np.int64).reshape(-1, 3)
    assert n_count == count

    T = P[F]
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    flipped = n[:, 1] < 0
    print("треугольников %d, из них с нормалью вниз %d (%.0f %%)"
          % (len(F), int(flipped.sum()), 100.0 * flipped.mean()))
    if check:
        return 0

    # 1. разворот обхода: у таких треугольников движок включает изнанку
    F[flipped] = F[flipped][:, [0, 2, 1]]
    n[flipped] *= -1.0

    # 2. нижний слой поверхности под землёй — схлопываем в вырожденные
    hm = json.load(open(HM_JSON))
    res = int(hm["res"])
    hx0, hz0, hcell = float(hm["x0"]), float(hm["z0"]), float(hm["cell"])
    H = np.fromfile(HM_F32, dtype="<f4").astype(np.float64).reshape(res, res)
    c = T.mean(1)
    ix = np.round((c[:, 0] - hx0) / hcell).astype(int)
    iz = np.round((c[:, 2] - hz0) / hcell).astype(int)
    inb = (ix >= 0) & (iz >= 0) & (ix < res) & (iz < res)
    ref = np.zeros(len(T))
    ref[inb] = H[iz[inb], ix[inb]]
    # внутри площадки heightmap меш не рисуем вовсе: там наложенные слои,
    # дыры и складки, а заплатка tools/make_island_fill.py строит по этой же
    # карте ровную сетку 1 м (её края совпадают с мешем по высоте)
    lower = inb
    print("внутри площадки heightmap скрыто %d треугольников (сетка на их месте)"
          % int(lower.sum()))
    F[lower] = F[lower][:, :1].repeat(3, axis=1)

    raw = F.astype(iw).tobytes()
    blob[idx_off:idx_off + len(raw)] = raw

    # 3. нормали по вершинам, взвешенные площадью
    VN = np.zeros_like(P)
    for k in range(3):
        np.add.at(VN, F[:, k], n)
    ln = np.linalg.norm(VN, axis=1, keepdims=True)
    VN = VN / np.maximum(ln, 1e-12)
    # В местах, где поверхность сходится с почти вертикальными стенками
    # (каньоны, обрывы), средняя нормаль ложится на бок, и треугольник
    # рисуется чёрным. Подмешиваем «вверх» — рельеф остаётся объёмным, но
    # никакая земля не освещается с изнанки.
    VN = VN + np.array([0.0, 1.2, 0.0])
    VN = VN / np.maximum(np.linalg.norm(VN, axis=1, keepdims=True), 1e-12)
    print("нормали пересчитаны: доля с ny>0.5 — %.0f %%, ny<0.2 — %.1f %%"
          % (100.0 * (VN[:, 1] > 0.5).mean(), 100.0 * (VN[:, 1] < 0.2).mean()))
    blob[nrm_off:nrm_off + count * 12] = VN.astype(np.float32).tobytes()
    write_glb(GLB, js, blob)
    print("записан", GLB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
