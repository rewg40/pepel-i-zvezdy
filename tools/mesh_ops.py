"""Mesh preprocessing: welding, UV-chart detection, chart-safe decimation."""
import numpy as np
from scipy.spatial import cKDTree
import fast_simplification


def weld(V, F, r=1.2e-4):
    """Merge vertices closer than r. Returns (Vw, Fw, src) where src[i] is the
    index of the source vertex that represents welded vertex i."""
    if r <= 0:
        return V, F, np.arange(len(V))
    tree = cKDTree(V)
    pairs = tree.query_pairs(r, output_type='ndarray')
    parent = np.arange(len(V))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb
    root = np.array([find(i) for i in range(len(V))])
    uniq, inv = np.unique(root, return_inverse=True)
    remap = np.full(len(V), -1, np.int64)
    remap[uniq] = np.arange(len(uniq))
    Fw = remap[F]
    # faces that completely collapsed are dropped
    ok = (Fw[:, 0] != Fw[:, 1]) & (Fw[:, 1] != Fw[:, 2]) & (Fw[:, 0] != Fw[:, 2])
    return V[uniq], Fw[ok], uniq


def face_normals(V, F):
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    ln[ln < 1e-12] = 1.0
    return n / ln


def charts(UV, F, eps=2e-4):
    """Connected components of faces in UV space. Returns per-face chart id."""
    q = np.round(UV / eps).astype(np.int64)
    seen = {}
    parent = np.arange(len(F))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for fi in range(len(F)):
        f = F[fi]
        for k in range(3):
            a, b = f[k], f[(k + 1) % 3]
            ka, kb = (q[a][0], q[a][1]), (q[b][0], q[b][1])
            key = (a, b, ka, kb) if (ka, kb) <= (kb, ka) else (b, a, kb, ka)
            other = seen.get(key)
            if other is None:
                seen[key] = fi
            else:
                union(fi, other)
    roots = np.array([find(i) for i in range(len(F))])
    _, inv = np.unique(roots, return_inverse=True)
    return inv


def decimate_charts(V, F, UV, chart, target_tris=150000, min_keep=6, max_ratio=0.93):
    """Decimate every UV chart separately so UVs stay valid inside the chart."""
    nf = len(F)
    counts = np.bincount(chart)
    keep = np.maximum((counts * (target_tris / nf)).astype(np.int64), min_keep)
    keep = np.minimum(keep, counts)
    out_V, out_F, out_UV, off = [], [], [], 0
    for c in range(len(counts)):
        fs = np.nonzero(chart == c)[0]
        vs, inv = np.unique(F[fs], return_inverse=True)
        fl = inv.reshape(-1, 3).astype(np.int32)
        Vc = V[vs]
        k = int(keep[c])
        if len(fs) > 40 and len(fs) > k * 1.15:
            # keep the reduction moderate: never destroy more than max_ratio of the chart
            red = 1.0 - k / len(fs)
            Vd, Fd = fast_simplification.simplify(Vc.astype(np.float32), fl,
                                                  target_reduction=float(min(red, max_ratio)))
            Fd = Fd[np.all(Fd[:, :3] < len(Vd), axis=1)]
            Fd = Fd[(Fd[:, 0] != Fd[:, 1]) & (Fd[:, 1] != Fd[:, 2]) & (Fd[:, 0] != Fd[:, 2])]
            Vd = Vd.astype(np.float64)
            # the simplifier can emit stray vertices on tiny charts: reject those
            size = np.maximum(Vc.max(0) - Vc.min(0), 1e-6)
            inside = np.all((Vd >= Vc.min(0) - 0.02 * size) &
                            (Vd <= Vc.max(0) + 0.02 * size), axis=1)
            if len(Fd) < min_keep or not np.all(inside[np.unique(Fd)]):
                Vd, Fd = Vc, fl
            _, j = cKDTree(Vc).query(Vd)
            UVc = UV[vs][j]
        else:
            Vd, Fd = Vc, fl
            UVc = UV[vs]
        out_V.append(Vd)
        out_F.append(Fd.astype(np.int64) + off)
        out_UV.append(UVc)
        off += len(Vd)
    return (np.concatenate(out_V), np.concatenate(out_F), np.concatenate(out_UV))
