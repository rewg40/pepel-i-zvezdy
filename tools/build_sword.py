"""Normalise the shipped broadsword: metres, hilt at the origin, blade along +Y.

writes game/models/sword.glb
"""
import io
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import glb_io
import glbw

LENGTH = 1.15          # metres, tip to pommel


def main(src, out):
    d = glb_io.mesh_data(src)
    V, F, N, UV = d['V'], d['F'], d['N'], d['UV']
    V = V - V.mean(0)
    # the blade runs along +-z in the source; rotate so it runs along +y
    Rz = np.array([[0, 0, 1.0], [1.0, 0, 0], [0, 1.0, 0]])
    # find the longest axis
    ext = V.max(0) - V.min(0)
    axis = int(np.argmax(ext))
    M = np.eye(3)
    if axis == 2:
        M = np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]])
    elif axis == 0:
        M = np.array([[0, -1.0, 0], [1.0, 0, 0], [0, 0, 1.0]])
    V = V @ M.T
    N = N @ M.T
    L = V[:, 1].max() - V[:, 1].min()
    s = LENGTH / L
    V = V * s
    # grip at the origin: about 22% up from the pommel
    y0, y1 = V[:, 1].min(), V[:, 1].max()
    grip = y0 + 0.22 * (y1 - y0)
    V[:, 1] -= grip
    V[:, 1] *= -1          # blade points down (-y) so a hand holding +y up is natural
    V = V[:, [0, 1, 2]]
    # centre x/z on the blade centre line
    V[:, 0] -= np.median(V[:, 0])
    V[:, 2] -= np.median(V[:, 2])

    tex = Image.open(io.BytesIO(glb_io.images(d['js'], d['binc'])[0])).convert('RGB')
    buf = io.BytesIO()
    tex.save(buf, 'JPEG', quality=90)
    g = glbw.GLB('Sword')
    ti = g.texture(g.image(buf.getvalue(), 'sword_albedo', 'image/jpeg'), g.sampler())
    mat = g.material('SwordSteel', base_tex=ti, metallic=0.85, roughness=0.35,
                     double_sided=False)
    mi = g.mesh('Sword', [{'attributes': {'POSITION': V.astype(np.float32),
                                          'NORMAL': N.astype(np.float32),
                                          'TEXCOORD_0': UV.astype(np.float32)},
                           'indices': F.astype(np.uint32).reshape(-1),
                           'material': mat}])
    nd = g.node('Sword', mesh=mi)
    g.g['scenes'][0]['nodes'] = [nd]
    size = g.write(out)
    print('sword', round(size / 1e6, 2), 'MB  length', round(V[:, 1].min(), 2),
          '..', round(V[:, 1].max(), 2),
          ' width', round(float(np.ptp(V[:, 0])), 3))


if __name__ == '__main__':
    main('/tmp/models/sword.glb',
         sys.argv[1] if len(sys.argv) > 1 else 'game/models/sword.glb')
