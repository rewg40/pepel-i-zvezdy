"""Island: decimate the shipped terrain/vegetation and bake a heightmap.

writes  game/models/island.glb, game/models/heightmap.png, game/models/heightmap.json
"""
import io
import json
import sys

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt
from scipy.spatial import cKDTree
import fast_simplification

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import glb_io
import glbw

# decimation targets per node kind
TERRAIN_TRIS = 500000
ISLET_KEEP = 0.22
VEG_KEEP = 0.08
VEG_MIN = 400


def node_attrs(js, binc, mi):
    pr = js['meshes'][mi]['primitives'][0]
    at = pr['attributes']
    V = glb_io.accessor(js, binc, at['POSITION']).astype(np.float64)
    N = glb_io.accessor(js, binc, at['NORMAL']).astype(np.float64) if 'NORMAL' in at else None
    UV = {}
    for k in at:
        if k.startswith('TEXCOORD'):
            UV[k] = glb_io.accessor(js, binc, at[k]).astype(np.float64)
    C = glb_io.accessor(js, binc, at['COLOR_0']).astype(np.float64) if 'COLOR_0' in at else None
    F = (glb_io.accessor(js, binc, pr['indices']).reshape(-1, 3).astype(np.int64)
         if 'indices' in pr else None)
    return V, N, UV, C, F, pr.get('material')


def decimate(V, N, UV, C, F, keep, min_tris=400):
    n = len(F)
    target = max(min_tris, int(n * keep))
    if n <= target * 1.2:
        return V, N, UV, C, F
    Vd, Fd = fast_simplification.simplify(V.astype(np.float32), F.astype(np.int32),
                                          target_reduction=float(1.0 - target / n))
    Fd = Fd[(Fd[:, 0] != Fd[:, 1]) & (Fd[:, 1] != Fd[:, 2]) & (Fd[:, 0] != Fd[:, 2])]
    _, j = cKDTree(V).query(Vd)
    return (Vd.astype(np.float64), None if N is None else N[j],
            {k: v[j] for k, v in UV.items()},
            None if C is None else C[j], Fd.astype(np.int64))


def heightmap(V, F, x0, x1, z0, z1, res):
    xs = np.linspace(x0, x1, res)
    zs = np.linspace(z0, z1, res)
    H = np.full((res, res), -1e9)
    tri = V[F]
    # only keep land: skip triangles fully below the water line
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
    hole = H < -1e8
    if hole.all():
        raise SystemExit('heightmap: no land in the requested area')
    idx = distance_transform_edt(hole, return_distances=False, return_indices=True)
    return H[tuple(idx)]


def main(src, outdir='/home/user/pepel-i-zvezdy/game/models'):
    js, binc = glb_io.load_glb(src)
    nodes = js['nodes']
    imgs = glb_io.images(js, binc)
    g = glbw.GLB('Island')
    tex = []
    for i, raw in enumerate(imgs):
        mime = js['images'][i].get('mimeType', 'image/jpeg')
        tex.append(g.texture(g.image(raw, f'tex{i}', mime)))
    mats = []
    for m in js.get('materials', []):
        pbr = m.get('pbrMetallicRoughness', {})
        base = None
        if 'baseColorTexture' in pbr:
            src_tex = js['textures'][pbr['baseColorTexture']['index']]['source']
            base = tex[src_tex]
        mats.append(g.material(m.get('name', 'mat'), base_tex=base,
                               base_color=pbr.get('baseColorFactor'),
                               metallic=pbr.get('metallicFactor', 0.0),
                               roughness=pbr.get('roughnessFactor', 0.9),
                               double_sided=m.get('doubleSided', False),
                               alpha_blend=m.get('alphaMode') == 'BLEND'))
    children = []
    stats = []
    terrain = None
    for ni in js['scenes'][0]['nodes']:
        node = nodes[ni]
        if 'mesh' not in node:
            continue
        name = node.get('name', '')
        V, N, UV, C, F, mi = node_attrs(js, binc, node['mesh'])
        if name == 'node_0':
            keep = min(1.0, TERRAIN_TRIS / max(len(F), 1))
        elif name.startswith('Veg'):
            keep = VEG_KEEP
        else:
            keep = ISLET_KEEP
        n0 = len(F)
        V, N, UV, C, F = decimate(V, N, UV, C, F, keep,
                                  1000 if name == 'node_0' else VEG_MIN)
        if name == 'node_0':
            terrain = (V, F)
        if N is None:
            nrm = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
            VN = np.zeros_like(V)
            for k in range(3):
                np.add.at(VN, F[:, k], nrm)
            N = VN / np.maximum(np.linalg.norm(VN, axis=1, keepdims=True), 1e-12)
        attrs = {'POSITION': V.astype(np.float32), 'NORMAL': N.astype(np.float32)}
        uv0 = UV.get('TEXCOORD_1') if 'TEXCOORD_1' in UV else (
            UV.get('TEXCOORD_0') if UV else None)
        if uv0 is not None:
            attrs['TEXCOORD_0'] = uv0.astype(np.float32)
        if C is not None:
            cc = C if C.shape[1] == 4 else np.hstack([C, np.ones((len(C), 1))])
            attrs['COLOR_0'] = cc.astype(np.float32)
        m = g.mesh(name, [{'attributes': attrs, 'indices': F.astype(np.uint32).reshape(-1),
                           'material': mi if mi is not None else 0}])
        tr = node.get('translation')
        rot = node.get('rotation')
        children.append(g.node(name, mesh=m,
                               translation=tr, rotation=rot, scale=node.get('scale')))
        stats.append((name, n0, len(F)))
    root = g.node('Island', children=children)
    g.g['scenes'][0]['nodes'] = [root]
    size = g.write(f'{outdir}/island.glb')
    for s in stats:
        print('  %-12s %8d -> %7d tris' % s)
    print('island.glb', round(size / 1e6, 2), 'MB')

    V, F = terrain
    print('terrain y range', round(V[:, 1].min(), 1), round(V[:, 1].max(), 1))
    # first pass: coarse map of the whole playable plateau
    x0, x1, z0, z1, res = -1500.0, 1500.0, -1500.0, 1500.0, 300
    H = heightmap(V, F, x0, x1, z0, z1, res)
    lo, hi = float(H.min()), float(H.max())
    print('heightmap', H.shape, 'y', round(lo, 1), round(hi, 1))
    hm = ((H - lo) / max(hi - lo, 1e-6) * 65535).astype(np.uint16)
    Image.fromarray(hm).save(f'{outdir}/heightmap.png')
    json.dump({'x0': x0, 'x1': x1, 'z0': z0, 'z1': z1, 'res': res,
               'y_min': lo, 'y_max': hi}, open(f'{outdir}/heightmap.json', 'w'), indent=1)
    # a flat, dry place to spawn the fight
    gx = np.gradient(H, axis=1)
    gz = np.gradient(H, axis=0)
    slope = np.hypot(gx, gz)
    cell = (x1 - x0) / (res - 1)
    best = None
    win = max(2, int(round(12 / cell)))          # ~12 m patch
    for iz in range(win, res - win, 2):
        for ix in range(win, res - win, 2):
            patch = slope[iz - win:iz + win, ix - win:ix + win]
            h = H[iz - win:iz + win, ix - win:ix + win]
            if h.mean() < 120 or patch.mean() > 1.2:
                continue
            score = patch.mean() * 3 + (h.max() - h.min()) * 0.02
            if best is None or score < best[0]:
                best = (score, ix, iz)
    if best is None:
        print('no flat arena found, using the middle of the map')
        best = (0.0, res // 2, res // 2)
    _, ix, iz = best
    wx = x0 + cell * ix
    wz = z0 + cell * iz
    a = 110.0
    res2 = int(round(2 * a)) + 1                  # 1 m cells
    H2 = heightmap(V, F, wx - a, wx + a, wz - a, wz + a, res2)
    lo2, hi2 = float(H2.min()), float(H2.max())
    hm2 = ((H2 - lo2) / max(hi2 - lo2, 1e-6) * 65535).astype(np.uint16)
    Image.fromarray(hm2).save(f'{outdir}/heightmap.png')
    json.dump({'x0': wx - a, 'x1': wx + a, 'z0': wz - a, 'z1': wz + a,
               'res': res2, 'y_min': lo2, 'y_max': hi2, 'cell': 1.0},
              open(f'{outdir}/heightmap.json', 'w'), indent=1)
    arena_y = float(heightmap(V, F, wx - 2, wx + 2, wz - 2, wz + 2, 3)[1, 1])
    json.dump({'x': float(wx), 'y': arena_y, 'z': float(wz),
               'slope': float(slope[iz - win:iz + win, ix - win:ix + win].max()),
               'h_range': float(H[iz - win:iz + win, ix - win:ix + win].max() -
                                H[iz - win:iz + win, ix - win:ix + win].min())},
              open(f'{outdir}/arena.json', 'w'), indent=1)
    print('arena at', round(wx, 1), round(arena_y, 1), round(wz, 1),
          '| 220 m map y', round(lo2, 1), round(hi2, 1), '| 1 m cells,', res2, 'px')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/tmp/models/island.glb')
