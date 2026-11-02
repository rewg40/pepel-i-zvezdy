"""Load a character GLB, evaluate an animation frame with linear blend skinning
and render it.  Also validates the part/cap structure and prints a report."""
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, __file__.rsplit('-', 1)[0])
import glb_io
import render as R

Q = None


def node_matrix(n):
    if 'matrix' in n:
        return np.array(n['matrix'], float).reshape(4, 4).T
    t = np.array(n.get('translation', [0, 0, 0]), float)
    q = np.array(n.get('rotation', [0, 0, 0, 1]), float)  # x,y,z,w
    s = np.array(n.get('scale', [1, 1, 1]), float)
    x, y, z, w = q
    M = np.eye(4)
    M[:3, :3] = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]) * s
    M[:3, 3] = t
    return M


class Char:
    def __init__(self, path):
        js, b = glb_io.load_glb(path)
        self.js, self.b = js, b
        self.parent = {}
        for i, n in enumerate(js['nodes']):
            for c in n.get('children', []):
                self.parent[c] = i
        self.anims = {a['name']: a for a in js.get('animations', [])}
        self.skins = js['skins']

    def rest_globals(self):
        G = {}
        for i in range(len(self.js['nodes'])):
            G[i] = self.node_globals(i, {})
        return G

    def node_globals(self, i, local_override):
        chain = []
        j = i
        while True:
            chain.append(j)
            if j in self.parent:
                j = self.parent[j]
            else:
                break
        M = np.eye(4)
        for j in reversed(chain):
            M = M @ local_override.get(j, node_matrix(self.js['nodes'][j]))
        return M

    def anim_local(self, anim, t):
        """Local TRS override at time t (rotation + translation tracks)."""
        out = {}
        js = self.js
        for ch in anim['channels']:
            s = anim['samplers'][ch['sampler']]
            tin = glb_io.accessor(js, self.b, s['input'])
            if t <= tin[0]:
                k, f = 0, 0.0
            elif t >= tin[-1]:
                k, f = len(tin) - 2, 1.0
            else:
                k = int(np.searchsorted(tin, t) - 1)
                k = max(0, min(k, len(tin) - 2))
                f = (t - tin[k]) / max(tin[k + 1] - tin[k], 1e-9)
            val = glb_io.accessor(js, self.b, s['output']).astype(np.float64)
            v = val[k] * (1 - f) + val[k + 1] * f
            nd = ch['target']['node']
            if ch['target']['path'] == 'rotation':
                v = v / np.linalg.norm(v)
                out.setdefault(nd, {})['rotation'] = [v[0], v[1], v[2], v[3]]
            else:
                out.setdefault(nd, {})['translation'] = list(v)
        return out

    def posed(self, anim_name=None, t=0.0, hide=()):
        loc = {} if anim_name is None else self.anim_local(self.anims[anim_name], t)
        node_local = {}
        for i, n in enumerate(self.js['nodes']):
            if i in loc:
                m = node_matrix({**n, **loc[i]})
                node_local[i] = m
            else:
                node_local[i] = node_matrix(n)
        G = {}
        for i in range(len(self.js['nodes'])):
            M = np.eye(4)
            chain = []
            j = i
            while True:
                chain.append(j)
                if j in self.parent:
                    j = self.parent[j]
                else:
                    break
            for j in reversed(chain):
                M = M @ node_local[j]
            G[i] = M
        return G

    def mesh_prims(self, skip_pieces=True):
        """Yield (node name, prim dict, joints, ibm) for all skinned meshes."""
        js, b = self.js, self.b
        for i, n in enumerate(js['nodes']):
            if 'mesh' not in n:
                continue
            if skip_pieces and '_Piece_' in (n.get('name') or ''):
                continue
            skin = js['skins'][n['skin']] if 'skin' in n else None
            if skin:
                ibm = glb_io.accessor(js, b, skin['inverseBindMatrices']).astype(np.float64)
                ibm = ibm.reshape(-1, 4, 4).transpose(0, 2, 1)
                joints = skin['joints']
            else:
                ibm, joints = None, None
            for prim in js['meshes'][n['mesh']]['primitives']:
                yield n.get('name', ''), prim, joints, ibm

    def skinned_points(self, G, hide=(), skip_pieces=True):
        js, b = self.js, self.b
        P, Nn, C, part = [], [], [], []
        for name, prim, joints, ibm in self.mesh_prims(skip_pieces):
            if any(h in name for h in hide):
                continue
            at = prim['attributes']
            V = glb_io.accessor(js, b, at['POSITION']).astype(np.float64)
            NRM = glb_io.accessor(js, b, at['NORMAL']).astype(np.float64)
            UV = glb_io.accessor(js, b, at['TEXCOORD_0']).astype(np.float64)
            J = glb_io.accessor(js, b, at['JOINTS_0']).astype(np.int64)
            Wt = glb_io.accessor(js, b, at['WEIGHTS_0']).astype(np.float64)
            if joints is not None:
                Gj = np.stack([G[joints[k]] for k in range(len(joints))])
                M = np.einsum('nk,nkij->nij', Wt, Gj[J] @ ibm[J])
                Vh = np.hstack([V, np.ones((len(V), 1))])
                V = np.einsum('nij,nj->ni', M, Vh)[:, :3]
                Nn_ = np.einsum('nij,nj->ni', M[:, :3, :3], NRM)
                NRM = Nn_ / np.maximum(np.linalg.norm(Nn_, axis=1, keepdims=True), 1e-9)
            P.append(V)
            Nn.append(NRM)
            C.append(UV)
            part.append(np.full(len(V), name))
        return np.vstack(P), np.vstack(Nn), np.vstack(C), np.concatenate(part)


def main(path, anim=None, t=0.0, out='preview.png', views=('front', 'side', 'back'),
         hide=()):
    ch = Char(path)
    js = ch.js
    print('nodes', len(js['nodes']), 'meshes', len(js['meshes']),
          'anims', list(ch.anims))
    tex = glb_io.material_texture(js, ch.b, 'baseColorTexture', 0)
    G = ch.posed(anim, t)
    P, N, UV, part = ch.skinned_points(G, hide)
    imgs = []
    if tex is not None:
        for v in views:
            imgs.append(R.render_points(P, N, UV, tex, v, 620))
        imgs.append(R.render_points(P, N, UV, tex, 'persp', 620))
    R.save(R.montage(imgs), out)
    print('wrote', out, 'verts', len(P))
    return ch


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None,
         float(sys.argv[3]) if len(sys.argv) > 3 else 0.0,
         sys.argv[4] if len(sys.argv) > 4 else '/tmp/preview.png')
