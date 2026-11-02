"""Build a game-ready GLB character from a prepared mesh.

The mesh is split into body / head / arms / legs.  Every part is a separate
skinned mesh that shares one skeleton, so the game can hide a part and re-parent
it as a rigid body when the limb is cut off.  Stump caps are exported as small
extra meshes that stay hidden until the limb is removed.

usage: python tools/build_char.py medic  (writes game/models/medic.glb)
"""
import io
import json
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import glbw
import rig as RIG
import skeleton as S

PARTS = ['Body', 'Head', 'ArmL', 'ArmR', 'LegL', 'LegR']
CUT_BONE = {          # part -> bone the stump lives on
    'Head': 'Neck', 'ArmL': 'Shoulder_L', 'ArmR': 'Shoulder_R',
    'LegL': 'Hips', 'LegR': 'Hips'}
# joints where a part's boundary is capped: (bone of the joint, radius factor, bone to skin to)
SOCKETS = {
    'Body': [('Shoulder_L', 0.060, 'Chest'), ('Shoulder_R', 0.060, 'Chest'),
             ('Thigh_L', 0.070, 'Hips'), ('Thigh_R', 0.070, 'Hips')],
    'Head': [('Neck', 0.055, 'Head')],
    'ArmL': [('Shoulder_L', 0.060, 'UpperArm_L')],
    'ArmR': [('Shoulder_R', 0.060, 'UpperArm_R')],
    'LegL': [('Thigh_L', 0.070, 'Thigh_L')],
    'LegR': [('Thigh_R', 0.070, 'Thigh_R')],
}
# outward direction of each socket's cut plane, in rig space
SOCKET_DIR = {
    'Shoulder_L': np.array([1.0, 0.0, 0.0]),
    'Shoulder_R': np.array([-1.0, 0.0, 0.0]),
    'Thigh_L': np.array([0.0, -1.0, 0.0]),
    'Thigh_R': np.array([0.0, -1.0, 0.0]),
    'Neck': np.array([0.0, 1.0, 0.0]),
}
ATTACH_BONE = {       # part -> bone the rigid piece is parented to
    'Head': 'Head', 'ArmL': 'UpperArm_L', 'ArmR': 'UpperArm_R',
    'LegL': 'Thigh_L', 'LegR': 'Thigh_R'}


# --------------------------------------------------------------------------- #
def boundary_loops(faces):
    """Boundary edges of a face set -> list of vertex loops."""
    from collections import defaultdict
    cnt = defaultdict(int)
    for f in faces:
        for k in range(3):
            a, b = int(f[k]), int(f[(k + 1) % 3])
            cnt[(min(a, b), max(a, b))] += 1
    edges = [e for e, c in cnt.items() if c == 1]
    if not edges:
        return []
    adj = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    loops, seen = [], set()
    for a, b in edges:
        if (a, b) in seen:
            continue
        loop = [a]
        seen.add((min(a, b), max(a, b)))
        cur, prev = b, a
        while True:
            loop.append(cur)
            nxt = [x for x in adj[cur] if x != prev]
            if not nxt:
                break
            n = nxt[0]
            e = (min(cur, n), max(cur, n))
            if e in seen:
                break
            seen.add(e)
            prev, cur = cur, n
        if len(loop) > 3:
            loops.append(loop)
    return loops


def cap_loops(V, loops, sockets, rig, H):
    """Fan-cap every boundary loop that sits near one of the given sockets.

    Returns (verts, faces, weights_bone_index) or (None, None, None)."""
    cv, cf, cbone = [], [], []
    off = 0
    for joint_bone, rf, skin_bone in sockets:
        joint = rig.bones[joint_bone][0]
        radius = rf * H
        used = False
        for loop in loops:
            P = V[loop]
            c = P.mean(0)
            if np.linalg.norm(c - joint) > radius:
                continue
            if used:
                # one cap per socket is enough; extra loops are inner shells
                continue
            cv.append(c)
            k = len(loop)
            for i in range(k):
                cf.append([off, off + 1 + i, off + 1 + (i + 1) % k])
            cv.extend(P)
            cbone.extend([rig.index[skin_bone]] * (k + 1))
            off += k + 1
            used = True
    if not cv:
        return None, None, None
    return np.array(cv), np.array(cf, np.int64), np.array(cbone)


def cap_all(V, F, loops, bias_point=None):
    """Fan-cap every boundary loop; normals point away from the part centre.

    Returns (verts, faces, normals) or (None, None, None)."""
    if not loops:
        return None, None, None
    centre = V[np.unique(F)].mean(0) if bias_point is None else bias_point
    cv, cf, cn = [], [], []
    off = 0
    for loop in loops:
        P = V[loop]
        c = P.mean(0)
        n = c - centre
        ln = np.linalg.norm(n)
        n = n / ln if ln > 1e-6 else np.array([0.0, 1.0, 0.0])
        cv.append(c)
        k = len(loop)
        for i in range(k):
            cf.append([off, off + 1 + i, off + 1 + (i + 1) % k])
        cv.extend(P)
        cn.extend([n] * (k + 1))
        off += k + 1
    return np.array(cv), np.array(cf, np.int64), np.array(cn)


def make_disc(rig, joint_bone, radius, inset=0.0, k=18):
    """Flat disc across a joint, facing outwards along the limb axis."""
    joint = rig.bones[joint_bone][0].copy()
    n = SOCKET_DIR[joint_bone]
    joint = joint + n * inset
    u = np.cross(n, [0.0, 1.0, 0.0])
    if np.linalg.norm(u) < 1e-6:
        u = np.cross(n, [1.0, 0.0, 0.0])
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    pts = [joint + radius * (np.cos(2 * np.pi * i / k) * u +
                            np.sin(2 * np.pi * i / k) * v) for i in range(k)]
    V = np.vstack([joint, np.array(pts)])
    F = np.array([[0, 1 + i, 1 + (i + 1) % k] for i in range(k)], np.int64)
    N = np.tile(n, (len(V), 1))
    return V, F, N, joint


def part_faces(W, F, bone_names, names):
    """Per-face part id from the summed skin weights of its three corners."""
    idx = {n: i for i, n in enumerate(bone_names)}
    bid = np.zeros(len(bone_names), np.int64)
    for p, bs in PART_BONES.items():
        for b in bs:
            bid[idx[b]] = names.index(p)
    fw = W[F[:, 0]] + W[F[:, 1]] + W[F[:, 2]]
    best = np.argmax(fw, axis=1)
    return bid[best]


PART_BONES = {
    'Body': ['Root', 'Hips', 'Spine', 'Chest'],
    'Head': ['Neck', 'Head'],
    'ArmL': ['Shoulder_L', 'UpperArm_L', 'LowerArm_L', 'Hand_L'],
    'ArmR': ['Shoulder_R', 'UpperArm_R', 'LowerArm_R', 'Hand_R'],
    'LegL': ['Thigh_L', 'Shin_L', 'Foot_L'],
    'LegR': ['Thigh_R', 'Shin_R', 'Foot_R'],
}


def normals(V, F):
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    vn = np.zeros_like(V)
    for k in range(3):
        np.add.at(vn, F[:, k], n)
    ln = np.linalg.norm(vn, axis=1, keepdims=True)
    ln[ln < 1e-12] = 1.0
    return vn / ln


def bone_world(rig, trs):
    """Local TRS per bone -> world matrices (nested dict order follows rig.names)."""
    G = {}

    def get(n):
        if n in G:
            return G[n]
        t, q = trs[n]
        M = np.eye(4)
        M[:3, :3] = RIG.quat_to_mat(np.array([q[3], q[0], q[1], q[2]]))
        M[:3, 3] = t
        p = rig.parents[n]
        G[n] = (get(p) @ M) if p else M
        return G[n]

    for n in rig.names:
        get(n)
    return G


def min_height(rig, ibm, Vs, Ws, trs):
    G = bone_world(rig, trs)
    mats = np.stack([G[n] @ ibm[n] for n in rig.names])
    M = np.einsum('nk,nkij->nij', Ws, mats[rig.hard_idx])
    Vh = np.hstack([Vs, np.ones((len(Vs), 1))])
    return float(np.einsum('nij,nj->ni', M, Vh)[:, 1].min())


def build(mesh_npz, tex_path, out_glb, name='Character', fps=30, scale=1.0,
          vertex_scale=None, texture_size=2048, anim_set='default'):
    z = np.load(mesh_npz)
    V = z['V'].astype(np.float64)
    F = z['F']
    UV = z['UV'].astype(np.float64)
    H = V[:, 1].max() - V[:, 1].min()
    if vertex_scale:
        V = V * vertex_scale
        H *= vertex_scale
    N = normals(V, F)

    skel = S.fit(V, iters=4)
    rig = RIG.Rig(skel, scale=1.0)
    W = S.skin_weights(V, skel)
    part_ids = part_faces(W, F, skel['names'], PARTS)

    tex = Image.open(tex_path).convert('RGB')
    if texture_size and max(tex.size) > texture_size:
        tex = tex.resize((texture_size, texture_size), Image.LANCZOS)
    buf = io.BytesIO()
    tex.save(buf, 'JPEG', quality=88)

    g = glbw.GLB(name)
    tex_id = g.image(buf.getvalue(), name + '_albedo', 'image/jpeg')
    tex_idx = g.texture(tex_id, g.sampler())
    mat = g.material(name + '_skin', base_tex=tex_idx, metallic=0.0, roughness=0.85,
                     double_sided=False)
    blood_tex = blood_image()
    bb = io.BytesIO()
    blood_tex.save(bb, 'JPEG', quality=85)
    b_id = g.image(bb.getvalue(), 'blood', 'image/jpeg')
    b_idx = g.texture(b_id, g.sampler())
    mat_blood = g.material('Blood', base_tex=b_idx, metallic=0.0, roughness=0.4,
                           double_sided=False)

    # ---------------- skeleton nodes
    bone_node = {}
    for n in rig.names:
        t, q = rig.local_trs()[n]
        bone_node[n] = g.node(n, translation=t, rotation=[q[1], q[2], q[3], q[0]])
    children = {n: [] for n in rig.names}
    roots = []
    for n in rig.names:
        p = rig.parents[n]
        if p is None:
            roots.append(n)
        else:
            children[p].append(n)
    for n in rig.names:
        if children[n]:
            g.g['nodes'][bone_node[n]]['children'] = [bone_node[c] for c in children[n]]
    joints = [bone_node[n] for n in rig.names]
    ibm = np.stack([rig.ibm()[n].T.reshape(-1) for n in rig.names])  # column-major
    ibm_acc = g.accessor(ibm.astype(np.float32))
    skin_idx = len(g.g['skins'])
    g.g['skins'].append({'name': name + '_skin', 'joints': joints,
                         'inverseBindMatrices': ibm_acc, 'skeleton': bone_node['Root']})

    jidx = np.argsort(-W, axis=1)[:, :4]
    jw = np.take_along_axis(W, jidx, axis=1)
    jw = jw / np.maximum(jw.sum(1, keepdims=True), 1e-9)

    def skinned_part(part, faces):
        vs = np.unique(faces)
        remap = np.full(len(V), -1, np.int64)
        remap[vs] = np.arange(len(vs))
        return vs, remap[faces], V[vs], N[vs], UV[vs], jidx[vs], jw[vs]

    meshes = {}
    for pi, part in enumerate(PARTS):
        sel = np.nonzero(part_ids == pi)[0]
        if len(sel) == 0:
            continue
        vs, fl, pv, pn, puv, pj, pw = skinned_part(part, F[sel])
        nv = len(pv)
        prims = []
        capv, capf, capn = cap_all(V, F[sel], boundary_loops(F[sel]),
                                   rig.bones[ATTACH_BONE.get(part, 'Chest')][0])
        if capv is not None:
            # caps take the weights of the nearest skinned vertex
            from scipy.spatial import cKDTree
            _, near = cKDTree(pv).query(capv)
            cj = pj[near]
            cw = pw[near]
            prims.append({'attributes': {
                'POSITION': capv.astype(np.float32),
                'NORMAL': capn.astype(np.float32),
                'TEXCOORD_0': np.full((len(capv), 2), 0.5, np.float32),
                'JOINTS_0': cj[:, :4].astype(np.uint8),
                'WEIGHTS_0': cw[:, :4].astype(np.float32)},
                'indices': capf.astype(np.uint32).reshape(-1),
                'material': mat_blood})
        wts = pw[:, :4].astype(np.float32)
        wts /= np.maximum(wts.sum(1, keepdims=True), 1e-9)
        prims.append({'attributes': {
            'POSITION': pv.astype(np.float32),
            'NORMAL': pn.astype(np.float32),
            'TEXCOORD_0': puv.astype(np.float32),
            'JOINTS_0': pj[:, :4].astype(np.uint8),
            'WEIGHTS_0': wts},
            'indices': fl.astype(np.uint32).reshape(-1),
            'material': mat})
        meshes[part] = (g.mesh(name + '_' + part, prims), nv)

    # ---- rigid cut pieces (used by the game for the severed limb that falls)
    piece_nodes = {}
    for part in meshes:
        if part == 'Body':
            continue
        sel = np.nonzero(part_ids == PARTS.index(part))[0]
        vs, fl, pv, pn, puv, pj, pw = skinned_part(part, F[sel])
        joint_bone = ATTACH_BONE[part]
        origin = rig.bones[joint_bone][0]
        Rm = rig.frames[joint_bone]
        loc = (pv - origin) @ Rm          # world -> bone-local of the proximal joint
        prims = [{'attributes': {'POSITION': loc.astype(np.float32),
                                 'NORMAL': (pn @ Rm).astype(np.float32),
                                 'TEXCOORD_0': puv.astype(np.float32)},
                  'indices': fl.astype(np.uint32).reshape(-1),
                  'material': mat}]
        # the cut face must not be hollow
        cv, cf, cn = cap_all(V, F[sel], boundary_loops(F[sel]), origin)
        if cv is not None:
            prims.append({'attributes': {
                'POSITION': ((cv - origin) @ Rm).astype(np.float32),
                'NORMAL': (cn @ Rm).astype(np.float32),
                'TEXCOORD_0': np.full((len(cv), 2), 0.5, np.float32)},
                'indices': cf.astype(np.uint32).reshape(-1),
                'material': mat_blood})
        piece_nodes[part] = g.node(name + '_Piece_' + part,
                                   mesh=g.mesh(name + '_Piece_' + part, prims),
                                   extras={'piece': part})

    part_node = {}
    for pi, (part, (mi, _)) in enumerate(meshes.items()):
        part_node[part] = g.node(name + '_' + part, mesh=mi, skin=skin_idx,
                                 extras={'part': part, 'cut_bone': CUT_BONE.get(part)})

    pieces_root = g.node(name + '_Pieces', children=list(piece_nodes.values()))
    rig_node = g.node(name + '_Rig', children=[bone_node[n] for n in roots] +
                      list(part_node.values()) + [pieces_root])
    g.g['scenes'][0]['nodes'] = [rig_node]

    # ---------------- animations
    anim_defs = ANIMS.get(anim_set, ANIMS['default'])
    sub = np.arange(0, len(V), max(1, len(V) // 12000))
    rig.hard_idx = jidx[sub]
    ibm_d = rig.ibm()
    anims = []
    for aname, fn, length, loop in anim_defs:
        times, frames = RIG.sample_anim(rig, fn, length, fps=fps, loop=loop)
        if aname in GROUND_FIX:
            lows = [min_height(rig, ibm_d, V[sub], jw[sub], f) for f in frames]
            drop = min(lows) - 0.03 * H     # запас на интерполяцию между кадрами
            for f in frames:
                t0, q0 = f['Root']
                f['Root'] = (t0 - np.array([0.0, drop, 0.0]), q0)
        tracks = RIG.make_tracks(rig, times, frames)
        samplers, channels = [], []
        t_acc = g.accessor(times.astype(np.float32))
        for bn in rig.names:
            q = tracks[bn]['rotation']
            # hemisphere alignment for linear interpolation
            for i in range(1, len(q)):
                if float(q[i] @ q[i - 1]) < 0:
                    q[i] = -q[i]
            q = q[:, [1, 2, 3, 0]]      # (w,x,y,z) -> glTF (x,y,z,w)
            qacc = g.accessor(q.astype(np.float32))
            samplers.append({'input': t_acc, 'output': qacc,
                             'interpolation': 'LINEAR'})
            channels.append({'sampler': len(samplers) - 1,
                             'target': {'node': bone_node[bn], 'path': 'rotation'}})
            tr = tracks[bn]['translation']
            tracc = g.accessor(tr.astype(np.float32))
            samplers.append({'input': t_acc, 'output': tracc,
                             'interpolation': 'LINEAR'})
            channels.append({'sampler': len(samplers) - 1,
                             'target': {'node': bone_node[bn], 'path': 'translation'}})
        g.g['animations'].append({'name': aname, 'samplers': samplers,
                                  'channels': channels})
        anims.append(aname)

    info = {'name': name, 'height': float(H), 'parts': {},
            'animations': anims,
            'bones': {n: [list(map(float, rig.bones[n][0])), list(map(float, rig.bones[n][1]))]
                      for n in rig.names},
            'attach': {}}
    for part, (mi, nv) in meshes.items():
        info['parts'][part] = {'mesh': name + '_' + part, 'verts': int(nv),
                               'bone': ATTACH_BONE.get(part, 'Chest')}
    for bn in rig.names:
        info['attach'][bn] = [list(map(float, rig.rest[bn][:3, 3]))]
    g.g['extras'] = {'parts': {p: ATTACH_BONE.get(p, 'Chest') for p in meshes},
                     'cuts': CUT_BONE}
    size = g.write(out_glb)
    info['size'] = size
    return info


def blood_image(size=256, seed=11):
    from PIL import ImageDraw, ImageFilter
    rng = np.random.default_rng(seed)
    im = Image.new('RGB', (size, size), (92, 10, 12))
    d = ImageDraw.Draw(im)
    for _ in range(360):
        x, y = rng.integers(0, size, 2)
        r = int(rng.integers(2, 26))
        c = int(rng.integers(40, 115))
        d.ellipse([x - r, y - r, x + r, y + r],
                  fill=(c + int(rng.integers(0, 40)), int(rng.integers(4, 26)),
                        int(rng.integers(4, 22))))
    return im.filter(ImageFilter.GaussianBlur(1.0))


# --------------------------------------------------------------------------- #
GROUND_FIX = {'Crawl', 'Death'}

import anim_sets  # noqa: E402

ANIMS = anim_sets.SETS

if __name__ == '__main__':
    which = sys.argv[1] if len(sys.argv) > 1 else 'medic'
    out = sys.argv[2] if len(sys.argv) > 2 else f'game/models/{which}.glb'
    cfg = anim_sets.CONFIG[which]
    info = build(f'/tmp/work/{which}_mesh.npz', f'/tmp/work/{which}_mesh_tex.png',
                 out, name=cfg['name'], scale=cfg.get('scale', 1.0),
                 texture_size=cfg.get('texture', 2048), anim_set=which)
    json.dump(info, open(out.replace('.glb', '.json'), 'w'), indent=1)
    print(json.dumps({k: v for k, v in info.items() if k != 'bones'}, indent=1)[:2000])
    print('size', round(info['size'] / 1e6, 2), 'MB')
