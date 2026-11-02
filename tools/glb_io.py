"""Minimal GLB reader: JSON chunk + binary chunk + accessor extractor."""
import json
import struct

import numpy as np

COMP = {5120: ('b', 1), 5121: ('B', 1), 5122: ('h', 2), 5123: ('H', 2),
        5125: ('I', 4), 5126: ('f', 4)}
NCOMP = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


def load_glb(path):
    b = open(path, 'rb').read()
    assert b[:4] == b'glTF', path
    ln, kind = struct.unpack('<II', b[12:20])
    js = json.loads(b[20:20 + ln])
    off = 20 + ln
    off += (4 - off % 4) % 4
    blen = struct.unpack('<I', b[off:off + 4])[0]
    return js, b[off + 8:off + 8 + blen]


def accessor(js, binc, idx):
    a = js['accessors'][idx]
    n = NCOMP[a['type']]
    fmt, size = COMP[a['componentType']]
    bv = js['bufferViews'][a['bufferView']]
    base = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    stride = bv.get('byteStride') or n * size
    if stride == n * size:
        arr = np.frombuffer(binc, dtype=np.dtype('<' + fmt), count=a['count'] * n,
                            offset=base)
        arr = arr.reshape(a['count'], n)
    else:
        arr = np.empty((a['count'], n), dtype=np.dtype('<' + fmt))
        for i in range(a['count']):
            off = base + i * stride
            arr[i] = np.frombuffer(binc, dtype=np.dtype('<' + fmt), count=n, offset=off)
    if a['type'] == 'SCALAR':
        arr = arr[:, 0]
    if a.get('normalized'):
        arr = arr.astype(np.float32) / np.iinfo(arr.dtype).max
    return arr


def images(js, binc):
    out = []
    for im in js.get('images', []):
        bv = js['bufferViews'][im['bufferView']]
        o = bv.get('byteOffset', 0)
        out.append(binc[o:o + bv['byteLength']])
    return out


def _node_matrix(n):
    if 'matrix' in n:
        m = np.array(n['matrix'], float).reshape(4, 4).T
        return m
    t = np.array(n.get('translation', [0, 0, 0]), float)
    q = np.array(n.get('rotation', [0, 0, 0, 1]), float)
    s = np.array(n.get('scale', [1, 1, 1]), float)
    x, y, z, w = q
    R = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    M = np.eye(4)
    M[:3, :3] = R * s
    M[:3, 3] = t
    return M


def mesh_data(path, world=True, max_prims=1):
    """Return a dict with V (float32 Nx3), N, UV (Nx2), F (Mx3) for mesh 0.

    With world=True the node transforms of the scene graph are applied.
    """
    js, binc = load_glb(path)
    node_by_mesh = {}
    parents = {}
    for i, n in enumerate(js['nodes']):
        for c in n.get('children', []):
            parents[c] = i
        if 'mesh' in n:
            node_by_mesh.setdefault(n['mesh'], i)

    def world_matrix(ni):
        M = np.eye(4)
        while True:
            M = _node_matrix(js['nodes'][ni]) @ M
            if ni not in parents:
                break
            ni = parents[ni]
        return M

    mi = 0
    prim = js['meshes'][mi]['primitives'][0]
    att = prim['attributes']
    V = accessor(js, binc, att['POSITION']).astype(np.float64)
    N = accessor(js, binc, att['NORMAL']).astype(np.float64) if 'NORMAL' in att else None
    uvkey = 'TEXCOORD_0' if 'TEXCOORD_0' in att else None
    UV = accessor(js, binc, att[uvkey]).astype(np.float64) if uvkey else None
    F = accessor(js, binc, prim['indices']).reshape(-1, 3).astype(np.int64)
    if world:
        ni = node_by_mesh.get(mi)
        if ni is not None:
            M = world_matrix(ni)
            V = V @ M[:3, :3].T + M[:3, 3]
            if N is not None:
                N = N @ np.linalg.inv(M[:3, :3])
                N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    return dict(V=V, N=N, UV=UV, F=F, js=js, binc=binc, prim=prim,
                images=images(js, binc))


def material_texture(js, binc, slot='baseColorTexture', mi=0):
    """Decode the texture bound to a material slot as an RGB PIL image."""
    from PIL import Image
    import io as _io
    m = js['materials'][mi]
    pbr = m.get('pbrMetallicRoughness', {})
    if slot not in pbr:
        return None
    t = js['textures'][pbr[slot]['index']]
    raw = images(js, binc)[t['source']]
    return Image.open(_io.BytesIO(raw)).convert('RGB')
