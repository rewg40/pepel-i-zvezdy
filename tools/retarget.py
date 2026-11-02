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
            L[:3, :3] = mat_from_q(q)          # node scale is ignored on purpose:
            L[:3, 3] = t                       # Mixamo FBXs carry a 100x armature
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
            P = P + R @ p
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
    for clip in out.values():
        fix_assimp_tracks(js, clip['tracks'])
    return out, js, b


def _parent_index(js):
    pidx = {}
    for i, n in enumerate(js['nodes']):
        for c in n.get('children', []):
            pidx[c] = i
    return pidx


def assimp_pre_chain(js, pidx, name, names):
    """Product of the `<bone>_$AssimpFbx$_PreRotation/_Rotation` helper nodes.

    Assimp exports an FBX joint as `<parent> -> <bone>_$Translation ->
    <bone>_$PreRotation -> <bone>_$Rotation -> <bone>`, and then writes the FBX
    animation channel (which already contains the joint orient) straight onto
    <bone>.  Played back naively the pre-rotation is applied twice, which flips
    limbs by 180 degrees; the channel has to be re-based on the helper chain.
    """
    if name not in names:
        return None
    j = pidx.get(names.index(name))
    q = np.array([1.0, 0.0, 0.0, 0.0])
    found = False
    while j is not None and names[j].startswith(name + '_$AssimpFbx$'):
        _t, qj, _s = node_local(js, j)
        q = q_mul(q, qj)                    # parent -> child order
        found = True
        j = pidx.get(j)
    return q if found else None


def fix_assimp_tracks(js, tracks):
    """Undo the double-applied joint orient of assimp-converted FBX files."""
    names = [n.get('name', 'node%d' % i) for i, n in enumerate(js['nodes'])]
    pidx = _parent_index(js)
    for name in list(tracks):
        pre = assimp_pre_chain(js, pidx, name, names)
        if pre is None:
            continue
        tracks[name].pop('translation', None)   # offsets live on the helpers
        if 'rotation' in tracks[name]:
            times, vals = tracks[name]['rotation']
            inv = np.array([pre[0], -pre[1], -pre[2], -pre[3]])
            tracks[name]['rotation'] = (times, np.stack([q_mul(inv, q) for q in vals]))


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
            s = s.lstrip('0123456789')      # mixamorig9:Hips, bip01_01_L_Thigh
            break
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
def _vangle(a, b):
    """Angle in degrees between two directions."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    c = float(np.dot(a, b)) / max(np.linalg.norm(a) * np.linalg.norm(b), 1e-12)
    return math.degrees(math.acos(min(1.0, max(-1.0, c))))


def _angle(A, B):
    c = (np.trace(np.asarray(A).T @ np.asarray(B)) - 1.0) / 2.0
    return math.degrees(math.acos(min(1.0, max(-1.0, c))))


def rot_between(a, b):
    """Minimal rotation matrix that turns unit vector a into unit vector b."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    a = a / max(np.linalg.norm(a), 1e-12)
    b = b / max(np.linalg.norm(b), 1e-12)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if c < -0.999999:                       # opposite: any perpendicular axis
        axis = np.cross(a, [1.0, 0.0, 0.0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0.0, 1.0, 0.0])
        return mat_from_q(q_axis(axis, math.pi))
    return mat_from_q(q_norm(np.array([1.0 + c, v[0], v[1], v[2]])))


def _dir_of(rig, name, child):
    v = rig.rest_world[child][:3, 3] - rig.rest_world[name][:3, 3]
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else None


def retarget_clip(clip, src, dst, mapping, fps=30.0, scale=None, strip_xz=False,
                  extra_offset=None, ref_time=0.0, ref='auto', mode='rot'):
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

    # A Mixamo FBX converted by Assimp carries the armature object itself as an
    # animated node ("CharacterArmature"), with the FBX unit-scale (100x) baked
    # into it.  Everything above our topmost mapped bone is object motion, not
    # character motion, so we express the whole source pose relative to that bone.
    mapped_src = [s for s in src_rest]
    base = None
    if src_hips in src.idx:
        chain = src._chain(src_hips)
        if len(chain) > 1:
            for j in chain:
                nm = src.js['nodes'][j].get('name')
                if nm in mapped_src and j != chain[-1]:
                    base = nm
                    break

    def rel(R, P, Rb, Pb, is_base=False):
        if base is None:
            return R, P
        if is_base:
            return R, P - Pb
        return Rb.T @ R, Rb.T @ (P - Pb)

    if scale is None:
        h_dst = dst.height()
        Rb0 = src.rest_world[base][:3, :3] if base else np.eye(3)
        Pb0 = src.rest_world[base][:3, 3] if base else np.zeros(3)
        h_src = max(max(rel(src.rest_world[s][:3, :3], src.rest_world[s][:3, 3],
                            Rb0, Pb0, s == base)[1][1] for s in src_rest), 1e-6)
        scale = h_dst / h_src
    fix = np.eye(3)
    if src_root and src_root in src_rest:
        fix = dst_rest[root_bone][:3, :3] @ src_rest[src_root][:3, :3].T

    hips_rest_src = rel(np.eye(3), src.rest_world[src_hips][:3, 3], Rb0, Pb0,
                        src_hips == base)[1] if src_hips else np.zeros(3)
    hips_rest_dst = dst.rest_world[hips_bone][:3, 3]
    parent_world_dst = {}
    for b in dst.names:
        p = dst.parent[b]
        parent_world_dst[b] = dst.rest_world[p] if p else np.eye(4)

    # ---- reference pose.
    # Retargeting transfers "how the bone moved away from its reference pose".
    # The natural reference is the bind pose, but Mixamo binds its skeletons in a
    # T-pose while our characters rest with their arms down, so the arms would be
    # pushed ~70 degrees down in every clip.  When the bind pose is clearly
    # unlike our rest pose we take the clip's own first frame as the reference
    # instead: that frame is the animation's neutral stand, and our rest pose is
    # lined up with it.
    Rb0 = src.rest_world[base][:3, :3] if base else np.eye(3)
    Pb0 = src.rest_world[base][:3, 3] if base else np.zeros(3)

    # world -> world frame between the source's top node and our armature
    frame_src = base
    if frame_src is None and src_hips in src.idx:
        chain = src._chain(src_hips)
        if chain:
            frame_src = src.js['nodes'][chain[0]].get('name')
    frame_fix = None
    if frame_src in src.rest_world:
        frame_fix = dst_rest[root_bone][:3, :3] @ src.rest_world[frame_src][:3, :3].T

    def src_ref(b, s, t):
        Rw, Pw = src.world_at(s, float(t), tracks)
        return rel(Rw, Pw, Rb0, Pb0, s == base)[0]

    samples = [float(x) for x in np.linspace(0.0, dur, min(24, max(4, n)))[:-1]]

    def mean_dir(b, s, t_list):
        acc = np.zeros(3)
        c = next((k for k in dst.names if dst.parent[k] == b and mapping.get(k)), None)
        c_src = next((k for k in src.names if src.parent[k] == s), None)
        if c is None or c_src is None:
            return None
        for tt in t_list:
            Rw, Pw = src.world_at(s, tt, tracks)
            _, Pc = src.world_at(c_src, tt, tracks)
            v = Pc - Pw
            if np.linalg.norm(v) > 1e-9:
                acc += v / np.linalg.norm(v)
        return acc if np.linalg.norm(acc) > 1e-9 else None

    def _ref_score(kind):
        """How far the source neutral is from our rest pose, in degrees."""
        fix0 = frame_fix if frame_fix is not None else dst_rest[root_bone][:3, :3] @ Rb0.T
        score = total = 0.0
        for b in ('UpperArm_L', 'UpperArm_R', 'LowerArm_L', 'LowerArm_R',
                  'Thigh_L', 'Thigh_R', 'Shin_L', 'Shin_R'):
            s = mapping.get(b)
            if not s or b not in dst.parent or src.parent.get(s) is None:
                continue
            d_d = _dir_of(dst, b, next(k for k in dst.names if dst.parent[k] == b))
            if d_d is None:
                continue
            if kind == 'bind':
                d_s = _dir_of(src, s, next(k for k in src.names if src.parent[k] == s))
            else:
                d_s = mean_dir(b, s, samples)
            if d_s is None:
                continue
            score += _vangle(fix0 @ d_s, d_d)
            total += 1
        return score / total if total else 1e9

    use_first = ref in ('first', 'mean')
    if ref == 'auto':
        # pick the reference that puts our rest pose closest to the clip's
        # neutral: for T-pose binders (Mixamo) that is the clip itself
        first_score = _ref_score('mean')
        bind_score = _ref_score('bind')
        ref = 'mean' if first_score < bind_score else 'bind'
        use_first = ref == 'mean'
    ref_kind = 'mean' if ref == 'mean' else ('first' if use_first else 'bind')
    ref_rot = {}
    n_ref = 0
    for b, s in mapping.items():
        if s is None or s not in src_rest:
            continue
        if ref == 'mean':
            # chordal mean of the clip's own poses == its neutral stand
            M = np.zeros((3, 3))
            for tt in samples:
                M += src_ref(b, s, tt)
            U, _sv, Vt = np.linalg.svd(M)
            ref_rot[s] = U @ Vt
        elif use_first:
            ref_rot[s] = src_ref(b, s, ref_time)
        else:
            ref_rot[s] = rel(src_rest[s][:3, :3], src_rest[s][:3, 3],
                             Rb0, Pb0, s == base)[0]
        n_ref += 1

    out = {'times': times.tolist(), 'rot': {b: [] for b in dst.names},
           'hips': [], 'duration': dur, 'scale': float(scale), 'ref_bones': n_ref,
           'ref': ref_kind}

    # ---- direction ("aim") transfer for the limbs.
    # Our characters rest with their arms down, Mixamo binds them in a T-pose, so
    # copying world orientations overshoots the shoulders by ~70 degrees.  For a
    # bone that has a mapped child we instead transfer how the *direction* of the
    # bone changes between the clip's reference frame and time t, and apply that
    # swing to our own rest direction.  Directions are immune to the different
    # bind poses; leaves (hands, feet) and the hips keep the orientation transfer.
    def src_dir(s1, s2, tt):
        _, p1 = src.world_at(s1, float(tt), tracks)
        _, p2 = src.world_at(s2, float(tt), tracks)
        if base is not None:
            _, pb = src.world_at(base, float(tt), tracks)
            p1, p2 = p1 - pb, p2 - pb
        v = p2 - p1
        nrm = float(np.linalg.norm(v))
        return v / nrm if nrm > 1e-9 else None

    aim = {}
    aim_child = {}
    if mode == 'aim' and frame_fix is not None:
        for b in dst.names:
            s1 = mapping.get(b)
            if not s1 or b in ('Root', 'Hips'):
                continue
            c = next((k for k in dst.names if dst.parent[k] == b and mapping.get(k)), None)
            if c is None:
                continue
            d_d = dst.rest_world[c][:3, 3] - dst.rest_world[b][:3, 3]
            if np.linalg.norm(d_d) < 1e-6:
                continue
            # the same reference the rotations use: bind pose, first frame or
            # the clip's average direction (stride-neutral)
            if ref == 'mean':
                acc = np.zeros(3)
                for tt in samples:
                    v = src_dir(s1, mapping[c], tt)
                    if v is not None:
                        acc += v
                d_s = acc / np.linalg.norm(acc) if np.linalg.norm(acc) > 1e-9 else None
            elif use_first:
                d_s = src_dir(s1, mapping[c], ref_time)
            else:
                d_s = _dir_of(src, s1, mapping[c])
            if d_s is None:
                continue
            aim[b] = (d_d / np.linalg.norm(d_d), d_s)
            aim_child[b] = c

    for t in times:
        world = {}
        # ---- source world rotations (only for mapped bones, but walk the full chain)
        cache = {}
        for b in dst.names:
            s = mapping.get(b)
            if s is None:
                continue
            Rw, Pw = src.world_at(s, float(t), tracks)
            if base is not None:
                Rb, Pb = src.world_at(base, float(t), tracks)
                Rw, Pw = rel(Rw, Pw, Rb, Pb, s == base)
            delta = fix @ (Pw - hips_rest_src) * scale
            if b in aim:
                d_d, d_s_ref = aim[b]
                d_s_now = src_dir(s, mapping[aim_child[b]], t)
                if d_s_now is not None:
                    target = frame_fix @ d_s_now
                    ref_w = frame_fix @ d_s_ref
                    if _vangle(d_d, ref_w) < 25.0:
                        # our rest points the same way as the clip's neutral:
                        # follow the clip exactly (knees and elbows then bend
                        # as far as the animation needs)
                        d_new = target
                    else:
                        # rest poses really differ, keep our own bias and only
                        # transfer how the direction *changed*
                        swing = rot_between(d_s_ref, d_s_now)
                        swing = frame_fix @ swing @ frame_fix.T
                        d_new = swing @ d_d
                    Rw = rot_between(d_d, d_new) @ dst_rest[b][:3, :3]
            else:
                off = dst_rest[b][:3, :3] @ ref_rot[s].T
                Rw = off @ Rw
            world[b] = (Rw, delta)
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


def fbx_to_glb(src):
    """Convert an FBX with tools/fbx2glb.js (assimp/wasm, no Blender needed)."""
    import shutil
    import subprocess
    import tempfile
    node = shutil.which('node')
    if node is None:
        raise RuntimeError('node is required to convert FBX '
                           '(or export GLB from Blender/Mixamo)')
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fbx2glb.js')
    out = os.path.join(tempfile.mkdtemp(prefix='fbx2glb_'),
                       os.path.splitext(os.path.basename(src))[0] + '.glb')
    r = subprocess.run([node, script, src, out], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1:][0]
                           if (r.stderr or r.stdout) else 'fbx2glb failed')
    return out


def gather_sources(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            for pat in ('*.glb', '*.GLB', '*.fbx', '*.FBX'):
                files += sorted(glob.glob(os.path.join(p, pat)))
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
    ap.add_argument('--prefix', default='', help='prefix added to every clip name')
    ap.add_argument('--rename', action='append', default=[], metavar='FROM=TO',
                    help='rename a clip (or a source file stem), e.g. --rename walking=Walk')
    ap.add_argument('--ref', choices=('auto', 'bind', 'first', 'mean'), default='auto',
                    help='reference pose: bind = file rest pose, first = clip first '
                         'frame, mean = average pose of the clip (good for cycles and '
                         'for T-pose binders like Mixamo), auto = pick per clip')
    ap.add_argument('--fps', type=float, default=30.0, help='resample rate (default 30)')
    ap.add_argument('--strip-xz', action='store_true',
                    help='kill horizontal hip motion (in-place locomotion clips)')
    ap.add_argument('--mode', choices=('aim', 'rot'), default='aim',
                    help="aim = transfer bone directions (hands/feet/hips keep rotation), "
                         "rot = transfer full world rotations")
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

    renames = {}
    for m in a.rename:
        if '=' not in m:
            print(f'bad --rename {m!r}, expected FROM=TO')
            return 2
        k, v = m.split('=', 1)
        renames[k.strip()] = v.strip()

    only = None
    if a.clips:
        only = {c.strip() for c in a.clips.split(',') if c.strip()}

    jobs = []
    for f in files:
        if f.lower().endswith('.fbx'):
            try:
                f = fbx_to_glb(f)
            except Exception as e:                            # noqa: BLE001
                print(f'! {f}: {e}')
                continue
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
        stem_used = os.path.splitext(os.path.basename(f))[0]
        k = name
        n = seen.get(k, 0)
        seen[k] = n + 1
        if n:
            k = f'{name}_{n + 1}'
        mapping = {b: s for b, s in mp.items() if s}
        res = retarget_clip(clip, src, dst, mapping, fps=a.fps, strip_xz=a.strip_xz,
                            mode=a.mode, ref=a.ref)
        off = measure_ground_offset(res, dst)
        if a.ground and abs(off) > 0.005:
            d = np.array([0.0, -off, 0.0])
            d = np.linalg.inv(dst.rest_world['Root'][:3, :3]) @ d
            res['hips'] = [h + d for h in res['hips']]
            off = 0.0
        out_clips.append((a.prefix + renames.get(k, renames.get(stem_used, k)), res))
        print(f'  {k:16s} <- {os.path.basename(f)}  ({res["duration"]:.2f}s, '
              f'{len(res["times"])} frames, scale {res["scale"]:.3f}, '
              f'ref {res["ref"]}, hips min {off:+.2f} m)')

    names = write_clip_glb(dst, out_clips, a.out, probe=not a.no_probe)
    print(f'\nwrote {a.out}: {len(names)} animation(s) -> {", ".join(names)}')
    print(f'rig node "{dst.root_name}", track paths Skeleton3D:<bone>')
    return 0


if __name__ == '__main__':
    sys.exit(main())
