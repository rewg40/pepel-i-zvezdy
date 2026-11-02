"""Mesh preparation: weld -> UV charts -> chart-safe decimation -> split corners.

Produces a rendering-ready mesh (one UV per corner) that still carries the
original 4096^2 atlas, so no texture re-bake is needed.
"""
import sys
import time

import numpy as np

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import glb_io
import mesh_ops as M


def prepare(path, target_tris=150000, weld_r=1.2e-4, verbose=True):
    t0 = time.time()
    d = glb_io.mesh_data(path)
    V, F, UV = d['V'], d['F'], d['UV']
    if verbose:
        print(f'  loaded {len(V)} v / {len(F)} f  ({time.time() - t0:.1f}s)')
    Vw, Fw, src = M.weld(V, F, weld_r)
    UVw = UV[src]
    ch = M.charts(UVw, Fw)
    if verbose:
        print(f'  welded {len(Vw)} v, {len(Fw)} f, {ch.max() + 1} charts  '
              f'({time.time() - t0:.1f}s)')
    Vd, Fd, UVd = M.decimate_charts(Vw, Fw, UVw, ch, target_tris=target_tris)
    if verbose:
        print(f'  decimated {len(Vd)} v / {len(Fd)} f  ({time.time() - t0:.1f}s)')
    # drop vertices not referenced by any face
    used = np.zeros(len(Vd), bool)
    used[Fd.ravel()] = True
    remap = np.full(len(Vd), -1, np.int64)
    remap[used] = np.arange(used.sum())
    Vd, UVd = Vd[used], UVd[used]
    Fd = remap[Fd]
    if verbose:
        print(f'  final {len(Vd)} v / {len(Fd)} f  ({time.time() - t0:.1f}s)')
    return dict(V=Vd, F=Fd, UV=UVd, tex=glb_io.material_texture(d['js'], d['binc']),
                src_js=d['js'])


if __name__ == '__main__':
    import pickle
    name = sys.argv[1]
    out = sys.argv[2]
    target = int(sys.argv[3]) if len(sys.argv) > 3 else 150000
    r = prepare(f'/tmp/models/{name}.glb', target)
    np.savez(out, V=r['V'].astype(np.float32), F=r['F'].astype(np.int64),
             UV=r['UV'].astype(np.float32))
    r['tex'].save(out.replace('.npz', '_tex.png'))
    print('saved', out)
