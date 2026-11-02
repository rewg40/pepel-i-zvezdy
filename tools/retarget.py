"""Retarget animation clips from a foreign rig onto a character built by
`tools/build_char.py`.

The idea: we do not need Godot's BoneMap / SkeletonProfile at all.  Clips are
re-baked offline onto *our* rest pose, so the resulting file contains ordinary
glTF animations that target our own bone names and play correctly in engine.

Math
----
For every target bone `b` mapped to a source bone `s`:

    q_off(b)      = q_dst_rest_world(b) * q_src_rest_world(s)^-1
    q_dst_world   = q_off(b) * q_src_world(s, t)
    q_dst_local   = q_dst_world(dst_parent)^-1 * q_dst_world

At rest the offset is the identity, so rest poses line up; during the clip the
source's *world* bone orientation is transferred, which is exactly what
retargeting needs.  Hip translation is delta-based and scaled by the ratio of
the two skeletons' heights (a bone-length ratio), so a 1.6 m clip drives a 1.86 m
zombie without foot sliding upwards.
"""
import argparse
import glob
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import glb_io
import glbw

# --------------------------------------------------------------------------- #
# quaternion helpers, (w, x, y, z)
# --------------------------------------------------------------------------- #
def q_mul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array([
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2])


def q_inv(q):
    return np.array([q[0], -q[1], -q[2], -q[3]])


def q_norm(q):
    n = np.linalg.norm(q)
    return q / n if n > 1e-12 else np.array([1.0, 0.0, 0.0, 0.0])


def q_slerp(a, b, t):
    d = float(np.dot(a, b))
    if d < 0.0:
        b = -b
        d = -d
    if d > 0.9995:
        return q_norm(a + (b - a) * t)
    th = math.acos(max(-1.0, min(1.0, d)))
    return q_norm(math.sin((1 - t) * th) / math.sin(th) * a +
                  math.sin(t * th) / math.sin(th) * b)


def mat_from_q(q):
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def q_from_mat(m):
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = [0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s,
             (m[1, 0] - m[0, 1]) / s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [(m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s,
             (m[0, 2] + m[2, 0]) / s]
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s,
             (m[1, 2] + m[2, 1]) / s]
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s,
             (m[1, 2] + m[2, 1]) / s, 0.25 * s]
    return q_norm(np.array(q))


def q_axis(axis, angle):
    axis = np.asarray(axis, float)
    axis = axis / np.linalg.norm(axis)
    return np.array([math.cos(angle / 2), *(math.sin(angle / 2) * axis)])


# --------------------------------------------------------------------------- #
# glTF scene helpers
# --------------------------------------------------------------------------- #
def node_local(js, i):
    """Local TRS of node i -> (translation, quaternion wxyz, scale)."""
    n = js['nodes'][i]
    if 'matrix' in n:
        M = np.array(n['matrix'], float).reshape(4, 4).T
        t = M[:3, 3]
        q = q_from_mat(M[:3, :3] / np.array([np.linalg.norm(M[:3, k])
                                             for k in range(3)]))
        s = np.array([np.linalg.norm(M[:3, k]) for k in range(3)])
        return t, q, s
    t = np.array(n.get('translation', [0, 0, 0]), float)
    r = n.get('rotation', [0, 0, 0, 1])       # glTF is (x, y, z, w)
    q = np.array([r[3], r[0], r[1], r[2]], float)
    s = np.array(n.get('scale', [1, 1, 1]), float)
    return t, q_norm(q), s


class RigData:
    """Rest skeleton read from a GLB: bone list, parents, local + world transforms.

    Used for both sides of the retarget: the destination is our character (bones
    taken from its skin), the source is whatever the clip file contains (all
    nodes, so unmapped helper bones are still walked correctly)."""

    def __init__(self, path, bone_names=None):
        js, b = glb_io.load_glb(path)
        self.js, self.bin = js, b
        names = [n.get('name', 'node%d' % i) for i, n in enumerate(js['nodes'])]
        idx = {}
        for i, nm in enumerate(names):
            idx.setdefault(nm, i)
        parent_idx = {}
        for i, n in enumerate(js['nodes']):
            for c in n.get('children', []):
                parent_idx[c] = i
        self.idx = idx
        if bone_names is None:
            if js.get('skins'):
                bone_names = [names[j] for j in js['skins'][0]['joints']]
            else:
                bone_names = list(dict.fromkeys(names))
        self.root_name = names[js['scenes'][0]['nodes'][0]] if js.get('scenes') else 'Rig'
        self.name = self.root_name
        self.names = []
        self.parent = {}
        self.local = {}
        self.rest_t = {}
        self.rest_q = {}
        self.rest_world = {}
        bset = set(bone_names)
        for nm in bone_names:
            if nm not in idx:
                raise KeyError(f'no node named {nm} in {path}')
            self.names.append(nm)
            p = parent_idx.get(idx[nm])
            while p is not None and names[p] not in bset:
                p = parent_idx.get(p)
            self.parent[nm] = names[p] if p is not None else None
            t, q, sc = node_local(js, idx[nm])
            self.local[nm] = (t, q, sc)
            self.rest_t[nm], self.rest_q[nm] = t, q
            self.rest_world[nm] = self._world(idx[nm], parent_idx)
        self.index = {n: k for k, n in enumerate(self.names)}

    def _world(self, i, parent_idx):
        M = np.eye(4)
        chain = []
        j = i
        while True:
            chain.append(j)
            if j not in parent_idx:
                break
            j = parent_idx[j]
        for j in reversed(chain):
            t, q, sc = node_local(self.js, j)
            L = np.eye(4)
            L[:3, :3] = mat_from_q(q) * sc
            L[:3, 3] = t
            M = M @ L
        return M

    def _chain(self, nm):
        chain = []
        j = self.idx[nm]
        pidx = {}
        for i, n in enumerate(self.js['nodes']):
            for c in n.get('children', []):
                pidx[c] = i
        while True:
            chain.append(j)
            if j not in pidx:
                break
            j = pidx[j]
        return list(reversed(chain))

    def height(self):
        return float(max(self.rest_world[n][1, 3] for n in self.names))

    def world_at(self, nm, t, tracks):
        """World rotation + position of a node at time t (rest fallback)."""
        R = np.eye(3)
        P = np.zeros(3)
        for j in self._chain(nm):
            name = self.js['nodes'][j].get('name', 'node%d' % j)
            t0, q0, s0 = self.local.get(name) or node_local(self.js, j)
            q = q0
            tr = tracks.get(name, {})
            if 'rotation' in tr:
                times, vals = tr['rotation']
                if len(times) == 1:
                    q = vals[0]
                else:
                    k = max(0, min(int(np.searchsorted(times, t) - 1), len(times) - 2))
                    f = (t - times[k]) / max(times[k + 1] - times[k], 1e-9)
                    q = q_slerp(vals[k], vals[k + 1], min(max(f, 0.0), 1.0))
            p = np.array(t0, float)
            if 'translation' in tr:
                times, vals = tr['translation']
                if len(times) == 1:
                    p = vals[0]
                else:
                    k = max(0, min(int(np.searchsorted(times, t) - 1), len(times) - 2))
                    f = (t - times[k]) / max(times[k + 1] - times[k], 1e-9)
                    f = min(max(f, 0.0), 1.0)
                    p = vals[k] * (1 - f) + vals[k + 1] * f
            P = P + R @ (p * s0)
            R = R @ mat_from_q(q)
        return R, P


Skeleton = RigData


def read_clip(path, fps=30.0):
    """Read every animation of a GLB into {bone: {path: (times, values)}}."""
    js, b = glb_io.load_glb(path)
    names = [n.get('name', 'node%d' % i) for i, n in enumerate(js['nodes'])]
    out = {}
    for an in js.get('animations', []):
        tracks = {}
        dur = 0.0
        for ch in an['channels']:
            s = an['samplers'][ch['sampler']]
            times = glb_io.accessor(js, b, s['input']).astype(np.float64)
            vals = glb_io.accessor(js, b, s['output']).astype(np.float64)
            dur = max(dur, float(times[-1]))
            node = names[ch['target']['node']]
            p = ch['target']['path']
            if p == 'rotation':
                vals = np.stack([q_norm(np.array([v[3], v[0], v[1], v[2]])) for v in vals])
            tracks.setdefault(node, {})[p] = (times, vals)
        name = an.get('name') or 'Clip%d' % len(out)
        out[name] = {'tracks': tracks, 'duration': dur}
    return out, js, b


# --------------------------------------------------------------------------- #
# bone name mapping
# --------------------------------------------------------------------------- #
CANON = ['Root', 'Hips', 'Spine', 'Chest', 'Neck', 'Head',
         'Shoulder_L', 'UpperArm_L', 'LowerArm_L', 'Hand_L',
         'Shoulder_R', 'UpperArm_R', 'LowerArm_R', 'Hand_R',
         'Thigh_L', 'Shin_L', 'Foot_L',
         'Thigh_R', 'Shin_R', 'Foot_R']

# candidate source names per canonical bone, in priority order
ALIASES = {
    'Root': ['root', 'reference', 'armature', 'scene', 'motion', 'rootmotion'],
    'Hips': ['hips', 'pelvis', 'hip', 'bip01pelvis', 'bip001pelvis'],
    'Spine': ['spine', 'spine01', 'spine1', 'abdomen', 'torso1', 'spine0'],
    'Chest': ['chest', 'spine2', 'spine02', 'upperchest', 'torso', 'bip01spine2'],
    'Neck': ['neck', 'neck1', 'neck01'],
    'Head': ['head', 'skull'],
    'Shoulder_L': ['leftshoulder', 'shoulderl', 'lshoulder', 'leftclavicle',
                   'claviclel', 'lcollar', 'leftcollar'],
    'UpperArm_L': ['leftarm', 'leftupperarm', 'upperarml', 'leftuparm', 'larm',
                   'arml', 'leftshoulderarm'],
    'LowerArm_L': ['leftforearm', 'leftlowerarm', 'lowerarml', 'leftloarm',
                   'lforearm', 'forearml'],
    'Hand_L': ['lefthand', 'handl', 'lhand', 'lefthand1'],
    'Shoulder_R': ['rightshoulder', 'shoulderr', 'rshoulder', 'rightclavicle',
                   'clavicler', 'rcollar', 'rightcollar'],
    'UpperArm_R': ['rightarm', 'rightupperarm', 'upperarmr', 'rightuparm', 'rarm',
                   'armr', 'rightshoulderarm'],
    'LowerArm_R': ['rightforearm', 'rightlowerarm', 'lowerarmr', 'rightloarm',
                   'rforearm', 'forearmr'],
    'Hand_R': ['righthand', 'handr', 'rhand', 'righthand1'],
    'Thigh_L': ['leftupleg', 'leftthigh', 'leftupperleg', 'thighl', 'lupleg',
                'leftleg1', 'upperlegl'],
    'Shin_L': ['leftleg', 'leftshin', 'leftcalf', 'leftlowerleg', 'shinl',
               'lcalf', 'lowerlegl'],
    'Foot_L': ['leftfoot', 'footl', 'lfoot'],
    'Thigh_R': ['rightupleg', 'rightthigh', 'rightupperleg', 'thighr', 'rupleg',
                'rightleg1', 'upperlegr'],
    'Shin_R': ['rightleg', 'rightshin', 'rightcalf', 'rightlowerleg', 'shinr',
               'rcalf', 'lowerlegr'],
    'Foot_R': ['rightfoot', 'footr', 'rfoot'],
}


def normalize(name):
    s = name.lower()
    for junk in ('.', '_', ':', '-', ' ', '|'):
        s = s.replace(junk, '')
    for prefix in ('mixamorig', 'bip01', 'bip001', 'armature', 'def'):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return s


def build_mapping(src_names, target_names, overrides=None):
    """target bone -> source bone (or None)."""
    norm = {}
    for n in src_names:
        norm.setdefault(normalize(n), n)
    out = {}
    used = set()
    for canon in target_names:
        if overrides and canon in overrides:
            src = overrides[canon]
            out[canon] = src if src in src_names else None
            continue
        found = None
        for cand in ALIASES.get(canon, []):
            if cand in norm and norm[cand] not in used:
                found = norm[cand]
                break
        out[canon] = found
        if found:
            used.add(found)
    return out


# --------------------------------------------------------------------------- #
# retargeting
# --------------------------------------------------------------------------- #
def retarget_clip(clip, src, dst, mapping, fps=30.0, scale=None, strip_xz=False,
                  extra_offset=None):
    """-> {'times': [...], 'rot': {bone: [q...]}, 'hips': [Vector3...], 'duration'}"""
    dur = clip['duration']
    if dur <= 0:
        dur = 1.0 / fps
    n = max(2, int(round(dur * fps)) + 1)
    times = np.linspace(0.0, dur, n)
    tracks = clip['tracks']

    # world rest rotations
    src_rest = {}
    dst_rest = {}
    for b in dst.names:
        dst_rest[b] = dst.rest_world[b]
    for b, s in mapping.items():
        if s is not None:
            src_rest[s] = src.rest_world[s]

    hips_bone = 'Hips' if 'Hips' in dst.names else dst.names[0]
    src_hips = mapping.get(hips_bone)
    root_bone = dst.names[0]
    src_root = mapping.get(root_bone) or src_hips

    if scale is None:
        h_dst = dst.height()
        h_src = max(max(src.rest_world[s][1, 3] for s in src_rest), 1e-6)
        scale = h_dst / h_src
    fix = np.eye(3)
    if src_root and src_root in src_rest:
        fix = dst_rest[root_bone][:3, :3] @ src_rest[src_root][:3, :3].T

    hips_rest_src = src.rest_world[src_hips][:3, 3] if src_hips else np.zeros(3)
    hips_rest_dst = dst.rest_world[hips_bone][:3, 3]
    parent_world_dst = {}
    for b in dst.names:
        p = dst.parent[b]
        parent_world_dst[b] = dst.rest_world[p] if p else np.eye(4)

    out = {'times': times.tolist(), 'rot': {b: [] for b in dst.names},
           'hips': [], 'duration': dur, 'scale': float(scale)}

    for t in times:
        world = {}
        # ---- source world rotations (only for mapped bones, but walk the full chain)
        cache = {}
        for b in dst.names:
            s = mapping.get(b)
            if s is None:
                continue
            Rw, Pw = src.world_at(s, float(t), tracks)
            delta = fix @ (Pw - hips_rest_src) * scale
            off = dst_rest[b][:3, :3] @ (src_rest[s][:3, :3]).T
            world[b] = (off @ Rw, delta)
        # ---- convert to local
        hips_local = None
        for b in dst.names:
            parent = dst.parent[b]
            if b in world:
                Rw, _ = world[b]
            else:
                Rw = dst_rest[b][:3, :3]          # unmapped -> stays at rest
            if parent is None:
                local = Rw
            elif parent in world:
                local = world[parent][0].T @ Rw
            else:
                local = dst_rest[parent][:3, :3].T @ Rw
            out['rot'][b].append(q_from_mat(local))
            if b == hips_bone:
                if b in world:
                    d = world[b][1].copy()
                    if strip_xz:
                        d[0] = d[2] = 0.0
                    if extra_offset is not None:
                        d = d + np.asarray(extra_offset, float)
                    hw = hips_rest_dst + d
                else:
                    hw = hips_rest_dst
                prot = parent_world_dst[b][:3, :3]
                ppos = parent_world_dst[b][:3, 3]
                hips_local = prot.T @ (hw - ppos)
                out['hips'].append(hips_local)
    return out


def measure_ground_offset(res, dst):
    """How far the hips sink below their rest height (metres, negative = lower).

    The hips track we write is parent-local, so the offset is rotated into world
    space first (our root is rotated by the Blender Z-up conversion).
    """
    bone = 'Hips' if 'Hips' in dst.names else dst.names[0]
    parent = dst.parent[bone]
    R = dst.rest_world[parent][:3, :3] if parent else np.eye(3)
    rest = np.asarray(dst.rest_t[bone], float)
    ys = [(R @ (np.asarray(h, float) - rest))[1] for h in res['hips']]
    return float(min(ys)) if ys else 0.0


def write_clip_glb(dst, clips, out_path, probe=True):
    """Write our skeleton (rest pose) + the retargeted animations as a GLB."""
    g = glbw.GLB(dst.name + '_clips')
    # ---- bone nodes in the destination rest pose
    node_of = {}
    for nm in dst.names:
        t = dst.rest_t[nm]
        q = dst.rest_q[nm]
        node_of[nm] = g.node(nm, translation=t, rotation=[q[1], q[2], q[3], q[0]])
    for nm in dst.names:
        kids = [node_of[c] for c in dst.names if dst.parent[c] == nm]
        if kids:
            g.g['nodes'][node_of[nm]]['children'] = kids
    roots = [node_of[n] for n in dst.names if dst.parent[n] is None]

    ibm = []
    for nm in dst.names:
        ibm.append(np.linalg.inv(dst.rest_world[nm]).T.reshape(-1))
    ibm_acc = g.accessor(np.array(ibm, np.float32))
    joints = [node_of[n] for n in dst.names]
    skin_idx = len(g.g['skins'])
    g.g['skins'].append({'name': dst.name + '_anim_skin', 'joints': joints,
                         'inverseBindMatrices': ibm_acc, 'skeleton': roots[0]})

    probe_node = None
    if probe:
        # Godot only builds a Skeleton3D when the file has a skin, so hang a
        # 4-vertex quad off the skeleton; the game never shows it.
        y = dst.rest_world['Hips'][1, 3]
        V = np.array([[0, y - 0.2, 0], [0.02, y - 0.2, 0], [0.02, y - 0.2, 0.02],
                      [0, y - 0.2, 0.02]], np.float32)
        F = np.array([0, 1, 2, 0, 2, 3], np.uint32)
        jj = np.zeros((4, 4), np.uint8)
        ww = np.zeros((4, 4), np.float32)
        ww[:, 0] = 1.0
        mat = g.material('AnimProbe', base_color=[0, 0, 0, 1])
        mi = g.mesh(dst.name + '_AnimProbe', [{
            'attributes': {'POSITION': V, 'NORMAL': np.tile([0, 1.0, 0], (4, 1)).astype(np.float32),
                           'JOINTS_0': jj, 'WEIGHTS_0': ww},
            'indices': F, 'material': mat}])
        probe_node = g.node(dst.name + '_AnimProbe', mesh=mi, skin=skin_idx)

    # ---- animations
    names_out = []
    for name, res in clips:
        times = np.array(res['times'], np.float32)
        t_acc = g.accessor(times)
        samplers, channels = [], []
        for nm in dst.names:
            q = np.array(res['rot'][nm])
            for i in range(1, len(q)):
                if float(np.dot(q[i], q[i - 1])) < 0:
                    q[i] = -q[i]
            q = q[:, [1, 2, 3, 0]]                       # wxyz -> glTF xyzw
            qacc = g.accessor(q.astype(np.float32))
            samplers.append({'input': t_acc, 'output': qacc, 'interpolation': 'LINEAR'})
            channels.append({'sampler': len(samplers) - 1,
                             'target': {'node': node_of[nm], 'path': 'rotation'}})
            if nm == ('Hips' if 'Hips' in dst.names else dst.names[0]):
                hips = np.array(res['hips'], np.float32)
                pacc = g.accessor(hips)
                samplers.append({'input': t_acc, 'output': pacc, 'interpolation': 'LINEAR'})
                channels.append({'sampler': len(samplers) - 1,
                                 'target': {'node': node_of[nm], 'path': 'translation'}})
        g.g['animations'].append({'name': name, 'samplers': samplers, 'channels': channels})
        names_out.append(name)

    # keep the armature node name identical to the character's, so Godot builds
    # the same Skeleton3D node name and the track paths match
    arm = g.node(dst.root_name, children=roots + ([probe_node] if probe_node else []))
    g.g['scenes'][0]['nodes'] = [arm]
    g.write(out_path)
    return names_out



# --------------------------------------------------------------------------- #
# command line
# --------------------------------------------------------------------------- #
CLIP_BAD_CHARS = ' .:/-|()'


def clip_name(raw, stem):
    """Godot-friendly animation name; generic exporter names fall back to the file."""
    name = (raw or '').strip()
    if not name or name.lower() in ('mixamo.com', 'mixamo', 'take 001', 'armature|mixamo.com|layer0',
                                    'animation', 'default', 'unnamed'):
        name = stem
    out = ''
    for ch in name:
        out += '_' if ch in CLIP_BAD_CHARS else ch
    while '__' in out:
        out = out.replace('__', '_')
    return out.strip('_') or 'Clip'


def gather_sources(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, '*.glb')) +
                            glob.glob(os.path.join(p, '*.GLB')))
        else:
            files.append(p)
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Retarget animation clips (Mixamo / Quaternius / any humanoid GLB) '
                    'onto the skeleton of one of our characters.')
    ap.add_argument('source', nargs='+', help='clip GLB file(s) or folder(s)')
    ap.add_argument('target', help='our character GLB (game/models/medic.glb, zombie.glb)')
    ap.add_argument('out', help='output GLB with the retargeted AnimationLibrary')
    ap.add_argument('--clips', default=None, help='comma separated clip names to keep')
    ap.add_argument('--fps', type=float, default=30.0, help='resample rate (default 30)')
    ap.add_argument('--strip-xz', action='store_true',
                    help='kill horizontal hip motion (in-place locomotion clips)')
    ap.add_argument('--ground', action='store_true',
                    help='raise/lower the clip so the lowest hip frame sits at rest height')
    ap.add_argument('--no-probe', action='store_true',
                    help='do not add the hidden quad that forces a Godot Skeleton3D')
    ap.add_argument('--map', action='append', default=[], metavar='TARGET=SOURCE',
                    help='override one bone mapping, e.g. --map Spine=mixamorig:Spine')
    ap.add_argument('--list', action='store_true', help='only print the mapping')
    a = ap.parse_args(argv)

    dst = RigData(a.target)
    files = gather_sources(a.source)
    if not files:
        print('no source GLB found')
        return 2

    overrides = {}
    for m in a.map:
        if '=' not in m:
            print(f'bad --map {m!r}, expected TARGET=SOURCE')
            return 2
        k, v = m.split('=', 1)
        overrides[k.strip()] = v.strip()

    only = None
    if a.clips:
        only = {c.strip() for c in a.clips.split(',') if c.strip()}

    jobs = []
    for f in files:
        try:
            clips, _, _ = read_clip(f, a.fps)
        except Exception as e:                                # noqa: BLE001
            print(f'! {f}: cannot read ({e})')
            continue
        src = RigData(f)
        mp = build_mapping(src.names, dst.names, overrides)
        found = sum(1 for v in mp.values() if v)
        if a.list or not jobs:
            print(f'\n{f}: {len(src.names)} bones, {len(clips)} clip(s)')
            print(f'  mapped {found}/{len(dst.names)} bones')
            for k in dst.names:
                print(f'    {k:12s} <- {mp.get(k)}')
        if found < max(6, len(dst.names) // 2):
            print(f'! {f}: skeleton does not look humanoid, skipped '
                  f'(use --map for unknown bone names)')
            continue
        stem = os.path.splitext(os.path.basename(f))[0]
        for cname, clip in sorted(clips.items()):
            name = clip_name(cname, stem)
            if only and name not in only and cname not in only:
                continue
            jobs.append((f, name, clip, mp, src))
    if a.list:
        return 0
    if not jobs:
        print('nothing to retarget')
        return 2

    # stop duplicate names (several files may hold a generic "Armature|mixamo.com")
    seen = {}
    out_clips = []
    for f, name, clip, mp, src in jobs:
        k = name
        n = seen.get(k, 0)
        seen[k] = n + 1
        if n:
            k = f'{name}_{n + 1}'
        mapping = {b: s for b, s in mp.items() if s}
        res = retarget_clip(clip, src, dst, mapping, fps=a.fps, strip_xz=a.strip_xz)
        off = measure_ground_offset(res, dst)
        if a.ground and abs(off) > 0.005:
            d = np.array([0.0, -off, 0.0])
            d = np.linalg.inv(dst.rest_world['Root'][:3, :3]) @ d
            res['hips'] = [h + d for h in res['hips']]
            off = 0.0
        out_clips.append((k, res))
        print(f'  {k:16s} <- {os.path.basename(f)}  ({res["duration"]:.2f}s, '
              f'{len(res["times"])} frames, scale {res["scale"]:.3f}, '
              f'hips min {off:+.2f} m)')

    names = write_clip_glb(dst, out_clips, a.out, probe=not a.no_probe)
    print(f'\nwrote {a.out}: {len(names)} animation(s) -> {", ".join(names)}')
    print(f'rig node "{dst.root_name}", track paths Skeleton3D:<bone>')
    return 0


if __name__ == '__main__':
    sys.exit(main())
