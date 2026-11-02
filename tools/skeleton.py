"""Skeleton template + automatic fitting to a humanoid mesh + skin weights.

The source models are single static meshes in an A/T-ish pose with no rig, so we
fit a template skeleton to the geometry:

  1. a height-normalised template is dropped onto the mesh bbox,
  2. every vertex is assigned to the nearest bone segment,
  3. each bone chain is re-fitted to the vertices it owns (y-slice ring centroids,
     then simplified to the 20..80 percentile span of the chain),
  4. repeat a few times.

The result is a plain dict {"bones": [...], "parents": {...}, "head": {..}}" in
mesh space; `skin_weights` turns it into per-vertex influences.
"""
import numpy as np

# name, parent, head position, tail position -- in units of body height,
# x>0 is the character's left, z>0 is forward.
TEMPLATE = [
    ('Root', None, (0.0, 0.50, 0.0), (0.0, 0.55, 0.0)),
    ('Hips', 'Root', (0.0, 0.52, 0.0), (0.0, 0.58, 0.0)),
    ('Spine', 'Hips', (0.0, 0.58, 0.0), (0.0, 0.66, 0.0)),
    ('Chest', 'Spine', (0.0, 0.66, 0.0), (0.0, 0.76, 0.0)),
    ('Neck', 'Chest', (0.0, 0.79, 0.0), (0.0, 0.83, 0.0)),
    ('Head', 'Neck', (0.0, 0.83, 0.0), (0.0, 0.94, 0.0)),
    ('Shoulder_L', 'Chest', (0.02, 0.78, 0.0), (0.10, 0.78, 0.0)),
    ('UpperArm_L', 'Shoulder_L', (0.10, 0.78, 0.0), (0.17, 0.63, 0.0)),
    ('LowerArm_L', 'UpperArm_L', (0.17, 0.63, 0.0), (0.21, 0.50, 0.0)),
    ('Hand_L', 'LowerArm_L', (0.21, 0.50, 0.0), (0.23, 0.44, 0.0)),
    ('Shoulder_R', 'Chest', (-0.02, 0.78, 0.0), (-0.10, 0.78, 0.0)),
    ('UpperArm_R', 'Shoulder_R', (-0.10, 0.78, 0.0), (-0.17, 0.63, 0.0)),
    ('LowerArm_R', 'UpperArm_R', (-0.17, 0.63, 0.0), (-0.21, 0.50, 0.0)),
    ('Hand_R', 'LowerArm_R', (-0.21, 0.50, 0.0), (-0.23, 0.44, 0.0)),
    ('Thigh_L', 'Hips', (0.055, 0.52, 0.0), (0.06, 0.28, 0.0)),
    ('Shin_L', 'Thigh_L', (0.06, 0.28, 0.0), (0.06, 0.06, 0.0)),
    ('Foot_L', 'Shin_L', (0.06, 0.06, 0.0), (0.06, 0.02, 0.08)),
    ('Thigh_R', 'Hips', (-0.055, 0.52, 0.0), (-0.06, 0.28, 0.0)),
    ('Shin_R', 'Thigh_R', (-0.06, 0.28, 0.0), (-0.06, 0.06, 0.0)),
    ('Foot_R', 'Shin_R', (-0.06, 0.06, 0.0), (-0.06, 0.02, 0.08)),
]

BONE_NAMES = [b[0] for b in TEMPLATE]
PARENT = {b[0]: b[1] for b in TEMPLATE}

# chains that get re-fitted (parent -> child), plus bones fitted on their own
CHAINS = [
    ['Hips', 'Spine', 'Chest', 'Neck', 'Head'],
    ['Shoulder_L', 'UpperArm_L', 'LowerArm_L', 'Hand_L'],
    ['Shoulder_R', 'UpperArm_R', 'LowerArm_R', 'Hand_R'],
    ['Thigh_L', 'Shin_L', 'Foot_L'],
    ['Thigh_R', 'Shin_R', 'Foot_R'],
]


def template_skeleton(V, height_scale=None):
    """Place the template on the mesh bbox (y up, feet on y=0)."""
    y0, y1 = V[:, 1].min(), V[:, 1].max()
    h = (y1 - y0) if height_scale is None else height_scale
    cx = (V[:, 0].min() + V[:, 0].max()) / 2
    out = {}
    for name, par, hd, tl in TEMPLATE:
        out[name] = (np.array([hd[0] * h + cx, hd[1] * h + y0, hd[2] * h]),
                     np.array([tl[0] * h + cx, tl[1] * h + y0, tl[2] * h]))
    return out, h, y0


def seg_dist(P, a, b, ret_t=False):
    ab = b - a
    L2 = float(ab @ ab)
    if L2 < 1e-12:
        d = P - a
        t = np.zeros(len(P))
    else:
        t = np.clip((P - a) @ ab / L2, 0.0, 1.0)
        d = P - (a + t[:, None] * ab)
    dist = np.linalg.norm(d, axis=1)
    return (dist, t) if ret_t else dist


def assign(V, bones, names, bias=None, use_geo=True):
    """Nearest-bone hard assignment. `bias` scales distances per bone."""
    D = np.empty((len(V), len(names)))
    for i, n in enumerate(names):
        a, b = bones[n]
        D[:, i] = seg_dist(V, a, b)
        if bias and n in bias:
            D[:, i] *= bias[n]
    if use_geo:
        # keep the torso together: strongly prefer the body chain near x=0
        pass
    return np.argmin(D, axis=1)


def fit_chain(V, lab, chain, bones, names, iters=2):
    """Re-fit a bone chain to the vertices assigned to its bones."""
    idx = {n: i for i, n in enumerate(names)}
    for _ in range(iters):
        for c in chain:
            ids = [idx[n] for n in c if n in idx]
            m = np.isin(lab, ids)
            if m.sum() < 30:
                continue
            P = V[m]
            # ring centroids along the chain direction
            a = bones[c[0]][0]
            b = bones[c[-1]][1]
            d = b - a
            L = np.linalg.norm(d)
            if L < 1e-9:
                continue
            d /= L
            t = (P - a) @ d
            nb = 24
            edges = np.linspace(t.min(), t.max(), nb + 1)
            cent = []
            for i in range(nb):
                s = (t >= edges[i]) & (t < edges[i + 1])
                if s.sum() < 5:
                    continue
                cent.append(P[s].mean(0))
            if len(cent) < 2:
                continue
            cent = np.array(cent)
            # cumulative arc length along the centroids
            seglen = np.linalg.norm(np.diff(cent, axis=0), axis=1)
            cum = np.concatenate([[0], np.cumsum(seglen)])
            total = cum[-1]
            if total < 1e-6:
                continue
            # the chain owns [0, total]; each bone takes an even share
            n = len(c)
            for i, name in enumerate(c):
                t0 = total * i / n
                t1 = total * (i + 1) / n
                p0 = _at(cent, cum, t0)
                p1 = _at(cent, cum, t1)
                bones[name] = (p0, p1)
            # chain the bones exactly
            for i in range(len(c) - 1):
                bones[c[i]] = (bones[c[i]][0], bones[c[i + 1]][0])
            # the parent keeps its own head, the chain head moves with it
            # (handled by the caller)
    return bones


def _at(cent, cum, t):
    if t <= cum[0]:
        return cent[0]
    if t >= cum[-1]:
        return cent[-1]
    i = int(np.searchsorted(cum, t) - 1)
    i = max(0, min(i, len(cent) - 2))
    f = (t - cum[i]) / max(cum[i + 1] - cum[i], 1e-9)
    return cent[i] * (1 - f) + cent[i + 1] * f


def find_head(V, frac=0.13):
    """Locate the head: vertical band under the crown, trimmed to one blob."""
    y1 = V[:, 1].max()
    H = y1 - V[:, 1].min()
    band = V[V[:, 1] > y1 - frac * H]
    c = band.mean(0)
    for _ in range(4):
        rad = np.linalg.norm((band - c)[:, [0, 2]], axis=1)
        keep = rad < max(np.percentile(rad, 80), 0.05 * H)
        if keep.sum() < 30:
            break
        c = band[keep].mean(0)
        band = band[keep]
    return c, (y1 - frac * H), y1, band


def refine_head(V, bones):
    """Point the Head bone at the real skull and rebuild Neck from Chest."""
    c, base_y, top_y, band = find_head(V)
    base = np.array([c[0], base_y, c[2]])
    tip = np.array([c[0], top_y, c[2]])
    bones['Head'] = (base, tip)
    bones['Neck'] = (bones['Chest'][1], base)
    return bones


def fit_spine(V, lab, bones, names):
    """Lay out Hips/Spine/Chest/Neck between the hip joints and the skull."""
    c, base_y, top_y, band = find_head(V)
    hipL, hipR = bones['Thigh_L'][0], bones['Thigh_R'][0]
    hips = (hipL + hipR) / 2
    H = V[:, 1].max() - V[:, 1].min()
    # upper torso centre just under the skull
    sel = np.abs(V[:, 1] - (base_y - 0.04 * H)) < 0.05 * H
    if sel.sum() > 40:
        upper = np.array([np.median(V[sel, 0]), base_y - 0.04 * H, np.median(V[sel, 2])])
    else:
        upper = np.array([c[0], base_y - 0.04 * H, c[2]])
    head_base = np.array([c[0], base_y, c[2]])
    # follow the body's centre line between the hips and the upper torso
    pts = [hips.copy(), (hips + upper) / 2, upper.copy()]
    for _ in range(3):
        for i in (1, 2):
            d = np.linalg.norm(V - pts[i], axis=1)
            s2 = d < 0.10 * H
            if s2.sum() > 50:
                pts[i] = pts[i] * 0.4 + np.median(V[s2], axis=0) * 0.6
                pts[i][1] = (hips[1] + upper[1]) * (i / 3) + 0
    pts[1][1] = hips[1] + (upper[1] - hips[1]) / 3
    pts[2][1] = hips[1] + 2 * (upper[1] - hips[1]) / 3
    bones['Hips'] = (hips, pts[1])
    bones['Spine'] = (pts[1], pts[2])
    bones['Chest'] = (pts[2], pts[2] + (head_base - pts[2]) * 0.75)
    bones['Neck'] = (bones['Chest'][1], head_base)
    bones['Head'] = (head_base, np.array([c[0], top_y, c[2]]))
    bones['Root'] = (hips - np.array([0, 0.05 * H, 0]), hips)
    for side in ('L', 'R'):
        bones['Shoulder_' + side] = (bones['Chest'][1], bones['Shoulder_' + side][1])
    return


def fit(V, iters=3, bias=None, verbose=False):
    bones, h, y0 = template_skeleton(V)
    names = BONE_NAMES
    for it in range(iters):
        lab = assign(V, bones, names, bias)
        for chain in CHAINS:
            if chain is CHAINS[0]:
                continue          # the spine is laid out by hand below
            fit_chain(V, lab, chain, bones, names, iters=1)
        fit_spine(V, lab, bones, names)
        # arms hang off the shoulder bones (already chained by fit_chain);
        # legs keep the hip joint found by their own chain fit
        refine_head(V, bones)
        if verbose:
            counts = np.bincount(lab, minlength=len(names))
            print(' iter', it, dict(zip(names, counts)))
    refine_head(V, bones)
    lab = assign(V, bones, names, bias)
    return dict(bones=bones, parents=PARENT, names=names, labels=lab, height=h, y0=y0)


def skin_weights(V, skel, k=4, sharp=4.0, bias=None):
    """Inverse-distance weights to the k nearest bones, normalised, top-3 kept."""
    names = skel['names']
    bones = skel['bones']
    D = np.empty((len(V), len(names)))
    for i, n in enumerate(names):
        a, b = bones[n]
        D[:, i] = seg_dist(V, a, b)
        if bias and n in bias:
            D[:, i] *= bias[n]
    D = np.maximum(D, 1e-4)
    W = 1.0 / D ** sharp
    order = np.argsort(-W, axis=1)[:, :k]
    Wk = np.zeros_like(W)
    rows = np.arange(len(V))[:, None]
    Wk[rows, order] = W[rows, order]
    keep = np.argsort(-Wk, axis=1)[:, :3]
    W3 = np.zeros_like(W)
    W3[rows, keep] = Wk[rows, keep]
    W3 /= W3.sum(1, keepdims=True)
    # prune tiny influences, renormalise, keep at most 3
    W3[W3 < 0.02] = 0
    W3 /= W3.sum(1, keepdims=True)
    return W3


def stretch_bone(bones, name, head=None, tail=None):
    a, b = bones[name]
    bones[name] = (head if head is not None else a, tail if tail is not None else b)
