"""Render a filmstrip of an animation and cut-away views."""
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import check_glb
import glb_io
import render as R


def strip(path, anim, n=6, view='persp', height=420, hide=(), out='strip.png', scale=1.0):
    ch = check_glb.Char(path)
    tex = glb_io.material_texture(ch.js, ch.b, 'baseColorTexture', 0)
    js = ch.js
    dur = 0
    a = ch.anims[anim]
    for s in a['samplers']:
        t = glb_io.accessor(js, ch.b, s['input'])
        dur = max(dur, float(t[-1]))
    imgs = []
    for i in range(n):
        t = dur * i / max(n - 1, 1)
        G = ch.posed(anim, t, hide)
        P, N, UV, _ = ch.skinned_points(G, hide)
        imgs.append(R.render_points(P * scale, N, UV, tex, view, height))
    R.save(R.montage(imgs), out)
    print('wrote', out, 'duration', round(dur, 2))


if __name__ == '__main__':
    strip(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 6,
          sys.argv[4] if len(sys.argv) > 4 else 'persp', 420,
          tuple(sys.argv[5].split(',')) if len(sys.argv) > 5 and sys.argv[5] else (),
          sys.argv[6] if len(sys.argv) > 6 else '/tmp/strip.png')
