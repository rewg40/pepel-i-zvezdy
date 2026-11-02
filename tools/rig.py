"""Skeleton -> glTF skin (bones, inverse bind matrices) + animation authoring."""
import numpy as np

import skeleton as S


def quat_from_mat(R):
    """3x3 rotation -> (w, x, y, z)."""
    m = R
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    q = np.array([w, x, y, z])
    return q / np.linalg.norm(q)


def quat_mul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array([
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2])


def quat_to_mat(q):
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def rot_euler(rx=0.0, ry=0.0, rz=0.0):
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rx @ Ry @ Rz


def bone_frames(bones, names):
    """Rest orientation per bone: y along the bone, z as close to +Z as possible."""
    frames = {}
    for n in names:
        a, b = bones[n]
        y = b - a
        L = np.linalg.norm(y)
        y = y / L if L > 1e-9 else np.array([0.0, 1.0, 0.0])
        z = np.array([0.0, 0.0, 1.0]) - y * y[2]
        if np.linalg.norm(z) < 1e-3:
            z = np.array([0.0, 1.0, 0.0]) - y * y[1]
        z /= np.linalg.norm(z)
        x = np.cross(y, z)
        frames[n] = np.stack([x, y, z], axis=1)
    return frames


class Rig:
    def __init__(self, skel, scale=1.0, name='Rig'):
        self.names = list(skel['names'])
        self.parents = dict(skel['parents'])
        self.bones = {n: (np.asarray(a, float) * scale, np.asarray(b, float) * scale)
                      for n, (a, b) in skel['bones'].items()}
        self.frames = bone_frames(self.bones, self.names)
        self.rest = self._rest_matrices()
        self.index = {n: i for i, n in enumerate(self.names)}

    def _rest_matrices(self):
        out = {}
        for n in self.names:
            M = np.eye(4)
            M[:3, :3] = self.frames[n]
            M[:3, 3] = self.bones[n][0]
            out[n] = M
        return out

    def local_rest(self, n):
        p = self.parents[n]
        if p is None:
            return self.rest[n]
        return np.linalg.inv(self.rest[p]) @ self.rest[n]

    def local_trs(self):
        """Rest local translation + rotation quaternion (w,x,y,z) per bone."""
        out = {}
        for n in self.names:
            L = self.local_rest(n)
            out[n] = (L[:3, 3].copy(), quat_from_mat(L[:3, :3]))
        return out

    def ibm(self):
        return {n: np.linalg.inv(self.rest[n]) for n in self.names}

    def part_of_bone(self):
        part = {}
        for n in self.names:
            if n.startswith('Head') or n == 'Neck':
                part[n] = 'Head'
            elif n.startswith(('Shoulder_L', 'UpperArm_L', 'LowerArm_L', 'Hand_L')):
                part[n] = 'ArmL'
            elif n.startswith(('Shoulder_R', 'UpperArm_R', 'LowerArm_R', 'Hand_R')):
                part[n] = 'ArmR'
            elif n.startswith(('Thigh_L', 'Shin_L', 'Foot_L')):
                part[n] = 'LegL'
            elif n.startswith(('Thigh_R', 'Shin_R', 'Foot_R')):
                part[n] = 'LegR'
            else:
                part[n] = 'Body'
        return part


def apply_pose(rig, pose):
    """pose: {bone: (rx,ry,rz)} or {bone: (rx,ry,rz,tx,ty,tz)} -> local TRS dict."""
    rest = rig.local_trs()
    out = {}
    for n in rig.names:
        t, q = rest[n]
        p = pose.get(n)
        if p is not None:
            rx, ry, rz = p[0], p[1], p[2]
            q = quat_mul(q, quat_from_mat(rot_euler(rx, ry, rz)))
            if len(p) > 3:
                t = t + np.array(p[3:6], float)
        out[n] = (t, q)
    return out


# ----------------------------------------------------------------------------
# pose generators.  All angles in radians, +x rotation swings a bone forward.
# ----------------------------------------------------------------------------
D = np.pi / 180.0


def _swing(t, amp=0.6, phase=0.0):
    return amp * np.sin(2 * np.pi * t + phase)


def idle(t, seed=0.0):
    b = np.sin(2 * np.pi * t)
    b2 = np.sin(4 * np.pi * t)
    return {
        'Hips': (0.01 * b, 0.02 * b, 0.0, 0.0, 0.006 * b2, 0.0),
        'Spine': (0.02 * b, 0.0, 0.01 * b),
        'Chest': (-0.02 * b, 0.01 * b, 0.0),
        'Neck': (0.02 * b, 0.05 * b, 0.0),
        'Head': (0.0, 0.06 * b, 0.01 * b),
        'UpperArm_L': (0.03 * b, 0.0, -0.05),
        'UpperArm_R': (0.03 * b, 0.0, 0.05),
        'LowerArm_L': (0.10 + 0.02 * b, 0.0, 0.0),
        'LowerArm_R': (0.10 + 0.02 * b, 0.0, 0.0),
    }


def walk(t, amp=1.0, arms=True):
    s = np.sin(2 * np.pi * t)
    c = np.cos(2 * np.pi * t)
    p = {
        'Hips': (0.04 * amp, 0.10 * s * amp, 0.0, 0.0, -0.012 * abs(c) * amp, 0.0),
        'Spine': (0.03 * amp, -0.05 * s * amp, 0.0),
        'Chest': (0.02 * amp, -0.06 * s * amp, 0.0),
        'Neck': (-0.04 * amp, 0.0, 0.0),
        'Thigh_L': (0.55 * s * amp, 0.0, 0.0),
        'Shin_L': (-max(0.0, 0.8 * np.sin(2 * np.pi * (t + 0.25))) * amp, 0.0, 0.0),
        'Foot_L': (-0.25 * s * amp, 0.0, 0.0),
        'Thigh_R': (-0.55 * s * amp, 0.0, 0.0),
        'Shin_R': (-max(0.0, 0.8 * np.sin(2 * np.pi * (t + 0.75))) * amp, 0.0, 0.0),
        'Foot_R': (0.25 * s * amp, 0.0, 0.0),
    }
    if arms:
        p['UpperArm_L'] = (-0.45 * s * amp, 0.0, -0.08)
        p['UpperArm_R'] = (0.45 * s * amp, 0.0, 0.08)
        p['LowerArm_L'] = (0.35 + 0.15 * abs(s) * amp, 0.0, 0.0)
        p['LowerArm_R'] = (0.35 + 0.15 * abs(s) * amp, 0.0, 0.0)
    else:
        p['UpperArm_L'] = (-0.20 * s * amp, 0.0, -0.12)
        p['UpperArm_R'] = (0.20 * s * amp, 0.0, 0.12)
        p['LowerArm_L'] = (0.20, 0.0, 0.0)
        p['LowerArm_R'] = (0.20, 0.0, 0.0)
    return p


def run(t):
    p = walk(t, amp=1.5)
    p['Spine'] = (0.18, p['Spine'][1], 0.0)
    p['Chest'] = (0.12, p['Chest'][1], 0.0)
    p['Neck'] = (-0.22, 0.0, 0.0)
    p['LowerArm_L'] = (1.15, 0.0, 0.0)
    p['LowerArm_R'] = (1.15, 0.0, 0.0)
    p['Hips'] = (p['Hips'][0], p['Hips'][1], 0.0, 0.0, -0.03 * abs(np.cos(2 * np.pi * t)), 0.0)
    return p


def attack(t):
    """Overhead two-handed slash, 1.0 = full cycle (windup, hit, recover)."""
    if t < 0.35:
        k = t / 0.35
        k = k * k * (3 - 2 * k)
        raise_ = k
        strike = 0.0
    elif t < 0.55:
        k = (t - 0.35) / 0.20
        raise_ = 1 - k
        strike = k
    else:
        k = (t - 0.55) / 0.45
        raise_ = 0.0
        strike = 1 - k * k * (3 - 2 * k)
    return {
        'Hips': (0.10 * raise_ - 0.12 * strike, -0.35 * raise_ + 0.45 * strike, 0.0),
        'Spine': (0.25 * raise_ - 0.30 * strike, -0.25 * raise_ + 0.30 * strike, 0.0),
        'Chest': (0.20 * raise_ - 0.25 * strike, -0.20 * raise_ + 0.25 * strike, 0.0),
        'Neck': (-0.15 * raise_ + 0.10 * strike, 0.0, 0.0),
        'UpperArm_L': (-2.5 * raise_ + 0.9 * strike, -0.25, -0.30),
        'UpperArm_R': (-2.5 * raise_ + 0.9 * strike, 0.25, 0.30),
        'LowerArm_L': (0.55 * rise(raise_, strike), 0.0, 0.0),
        'LowerArm_R': (0.55 * rise(raise_, strike), 0.0, 0.0),
        'Thigh_L': (0.25 * strike, 0.0, 0.0),
        'Thigh_R': (-0.10 * strike, 0.0, 0.0),
        'Shin_L': (-0.15 * strike, 0.0, 0.0),
    }


def rise(a, b):
    return max(a, 0.15 - 0.15 * b)


def hit(t):
    k = max(0.0, 1.0 - t / 0.45)
    return {
        'Hips': (-0.10 * k, 0.0, 0.05 * k, 0.0, 0.0, -0.03 * k),
        'Spine': (-0.22 * k, 0.10 * k, 0.0),
        'Chest': (-0.18 * k, 0.15 * k, 0.0),
        'Neck': (0.20 * k, 0.0, 0.0),
        'Head': (0.25 * k, 0.10 * k, 0.0),
        'UpperArm_L': (0.35 * k, 0.0, -0.35 * k),
        'UpperArm_R': (0.35 * k, 0.0, 0.35 * k),
        'LowerArm_L': (0.5 * k, 0.0, 0.0),
        'LowerArm_R': (0.5 * k, 0.0, 0.0),
        'Thigh_L': (-0.15 * k, 0.0, 0.0),
        'Shin_L': (0.25 * k, 0.0, 0.0),
    }


def death(t):
    """Collapse to the ground on the back."""
    k = min(1.0, t / 0.75)
    k = k * k * (3 - 2 * k)
    return {
        'Root': (-1.52 * k, 0.0, 0.0, 0.0, -0.29 * k, -0.16 * k),
        'Hips': (0.35 * k, 0.0, 0.0),
        'Spine': (0.20 * k, 0.0, 0.0),
        'Chest': (0.15 * k, 0.0, 0.0),
        'Neck': (0.35 * k, 0.25 * k, 0.0),
        'Head': (0.30 * k, 0.20 * k, 0.0),
        'UpperArm_L': (0.4 * k, 0.0, -0.9 * k),
        'UpperArm_R': (0.4 * k, 0.0, 0.9 * k),
        'LowerArm_L': (0.6 * k, 0.0, 0.0),
        'LowerArm_R': (0.6 * k, 0.0, 0.0),
        'Thigh_L': (0.9 * k, 0.0, -0.25 * k),
        'Thigh_R': (0.9 * k, 0.0, 0.25 * k),
        'Shin_L': (-0.9 * k, 0.0, 0.0),
        'Shin_R': (-0.9 * k, 0.0, 0.0),
    }


def crawl(t):
    """Dragging crawl for a legless zombie: torso prone, arms pulling, head up."""
    s = np.sin(2 * np.pi * t)
    return {
        'Root': (1.30, 0.0, 0.0, 0.0, 0.0, -0.06),
        'Hips': (-0.10, 0.04 * s, 0.0),
        'Spine': (-0.18, -0.03 * s, 0.0),
        'Chest': (-0.20, -0.03 * s, 0.0),
        'Neck': (0.72, 0.0, 0.0),
        'Head': (0.50, 0.06 * s, 0.0),
        'Shoulder_L': (0.0, 0.0, -0.12 * s),
        'Shoulder_R': (0.0, 0.0, 0.12 * s),
        'UpperArm_L': (0.95 + 0.35 * s, 0.0, -0.55),
        'UpperArm_R': (0.95 - 0.35 * s, 0.0, 0.55),
        'LowerArm_L': (-0.75 - 0.35 * s, 0.0, 0.0),
        'LowerArm_R': (-0.75 + 0.35 * s, 0.0, 0.0),
        'Hand_L': (0.25, 0.0, 0.0),
        'Hand_R': (0.25, 0.0, 0.0),
        'Thigh_L': (0.15, 0.0, -0.12),
        'Thigh_R': (0.15, 0.0, 0.12),
        'Shin_L': (-0.20, 0.0, 0.0),
        'Shin_R': (-0.20, 0.0, 0.0),
    }


def zombie_idle(t):
    b = np.sin(2 * np.pi * t)
    return {
        'Hips': (0.03 * b, 0.03 * b, 0.02 * b, 0.0, -0.005 * b, 0.0),
        'Spine': (0.04 * b, 0.0, 0.0),
        'Chest': (-0.03 * b, 0.03 * b, 0.0),
        'Neck': (0.10 * b, 0.08 * b, 0.0),
        'Head': (0.05 * b, 0.10 * b, 0.05 * b),
        'UpperArm_L': (-0.55, 0.0, -0.18),
        'UpperArm_R': (-0.35, 0.0, 0.18),
        'LowerArm_L': (0.55, 0.0, 0.0),
        'LowerArm_R': (0.35, 0.0, 0.0),
    }


def zombie_walk(t, arms=True):
    s = np.sin(2 * np.pi * t)
    c = np.cos(2 * np.pi * t)
    p = {
        'Hips': (0.05, 0.12 * s, 0.06 * s, 0.0, -0.012 * abs(c), 0.0),
        'Spine': (0.05, -0.08 * s, -0.03 * s),
        'Chest': (0.05, -0.10 * s, 0.0),
        'Neck': (0.2, 0.0, 0.0),
        'Head': (0.15, 0.12 * s, 0.08 * s),
        'Thigh_L': (0.42 * s, 0.0, -0.08),
        'Shin_L': (-max(0.0, 0.55 * np.sin(2 * np.pi * (t + 0.25))), 0.0, 0.0),
        'Foot_L': (-0.15 * s, 0.0, 0.0),
        'Thigh_R': (-0.42 * s, 0.0, 0.08),
        'Shin_R': (-max(0.0, 0.55 * np.sin(2 * np.pi * (t + 0.75))), 0.0, 0.0),
        'Foot_R': (0.15 * s, 0.0, 0.0),
    }
    if arms:
        p['UpperArm_L'] = (-0.75 + 0.15 * s, 0.0, -0.25)
        p['UpperArm_R'] = (-0.75 - 0.15 * s, 0.0, 0.25)
        p['LowerArm_L'] = (0.85, 0.0, 0.0)
        p['LowerArm_R'] = (0.85, 0.0, 0.0)
    else:
        p['Shoulder_L'] = (0.0, 0.0, -0.10 * s)
        p['Shoulder_R'] = (0.0, 0.0, 0.10 * s)
    return p


def zombie_attack(t):
    if t < 0.4:
        k = t / 0.4
        k = k * k * (3 - 2 * k)
        up, down = k, 0.0
    elif t < 0.6:
        k = (t - 0.4) / 0.2
        up, down = 1 - k, k
    else:
        k = (t - 0.6) / 0.4
        up, down = 0.0, 1 - k * k * (3 - 2 * k)
    return {
        'Hips': (0.10 * up - 0.20 * down, 0.0, 0.0),
        'Spine': (0.20 * up - 0.35 * down, 0.0, 0.0),
        'Chest': (0.15 * up - 0.30 * down, 0.0, 0.0),
        'Neck': (-0.10 * up + 0.15 * down, 0.0, 0.0),
        'Head': (-0.10 * up + 0.20 * down, 0.0, 0.0),
        'UpperArm_L': (-1.5 * up + 0.35 * down, 0.0, -0.3),
        'UpperArm_R': (-1.5 * up + 0.35 * down, 0.0, 0.3),
        'LowerArm_L': (0.3 + 0.6 * up, 0.0, 0.0),
        'LowerArm_R': (0.3 + 0.6 * up, 0.0, 0.0),
    }


POSES = {
    'Idle': (idle, 2.0, True),
    'Walk': (walk, 1.0, True),
    'Run': (run, 0.7, True),
    'Attack': (attack, 1.0, False),
    'Hit': (hit, 0.45, False),
    'Death': (death, 1.2, False),
    'Crawl': (crawl, 1.2, True),
    'ZombieIdle': (zombie_idle, 2.5, True),
    'ZombieWalk': (zombie_walk, 1.2, True),
    'ZombieWalkNoArms': (lambda t: zombie_walk(t, arms=False), 1.2, True),
    'ZombieAttack': (zombie_attack, 1.0, False),
}


def sample_anim(rig, fn, length, fps=30, loop=True):
    n = int(round(length * fps))
    times = np.arange(n + 1) / fps
    frames = []
    for t in times:
        ph = (t / length) % 1.0 if loop else min(t / length, 1.0)
        frames.append(apply_pose(rig, fn(ph)))
    return times, frames


def make_tracks(rig, times, frames):
    """-> {bone: {'rotation': quats[N,4], 'translation': vec[N,3]}}"""
    out = {}
    for n in rig.names:
        q = np.array([f[n][1] for f in frames])
        t = np.array([f[n][0] for f in frames])
        out[n] = {'rotation': q, 'translation': t}
    return out
