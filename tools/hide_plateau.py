#!/usr/bin/env python3
"""Скрыть меш острова внутри площадки heightmap (на его месте — ровная сетка).

У арены в island.glb наложены несколько слоёв поверхности и есть складки: сверху
они читаются как светлые плиты и стенки. Игра рисует здесь сетку 1 м
(tools/make_island_fill.py) по карте высот, поэтому исходный меш внутри площадки
не нужен — схлопываем его треугольники в вырожденные.

Запускать ПОСЛЕ tools/rebake_heightmap.py (иначе перепечённая карта потеряет
высоты этой зоны) и после tools/fix_terrain_normals.py.

    python3 tools/hide_plateau.py
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fix_terrain_normals import (  # noqa: E402
    GLB, HM_JSON, TERRAIN_MESH, accessor_offset, read_glb, write_glb,
)


def main() -> int:
    js, blob = read_glb(GLB)
    prim = js["meshes"][TERRAIN_MESH]["primitives"][0]
    pos_off, count = accessor_offset(js, prim["attributes"]["POSITION"])
    idx_acc = js["accessors"][prim["indices"]]
    idx_view = js["bufferViews"][idx_acc["bufferView"]]
    idx_off = idx_view["byteOffset"] + idx_acc.get("byteOffset", 0)
    iw = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32}[idx_acc["componentType"]]

    P = np.frombuffer(bytes(blob[pos_off:pos_off + count * 12]), np.float32).reshape(-1, 3)
    F = np.frombuffer(bytes(blob[idx_off:idx_off + idx_acc["count"] * 4]), iw).astype(np.int64).reshape(-1, 3)
    meta = json.load(open(HM_JSON))
    res = int(meta["res"])
    cell = float(meta["cell"])
    x0, x1 = float(meta["x0"]), float(meta["x0"]) + (res - 1) * cell
    z0, z1 = float(meta["z0"]), float(meta["z0"]) + (res - 1) * cell

    c = P[F].mean(1)
    inside = (c[:, 0] > x0) & (c[:, 0] < x1) & (c[:, 2] > z0) & (c[:, 2] < z1)
    print("внутри площадки %.0f×%.0f м: %d треугольников из %d"
          % (x1 - x0, z1 - z0, int(inside.sum()), len(F)))
    F[inside] = F[inside][:, :1].repeat(3, axis=1)
    raw = F.astype(iw).tobytes()
    blob[idx_off:idx_off + len(raw)] = raw
    write_glb(GLB, js, blob)
    print("записан", GLB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
