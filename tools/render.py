"""Offline preview renderer: z-buffered point splatting with UV texture lookup.

Cheap but good enough to judge geometry seams, cut caps, textures and poses.
"""
import numpy as np
from PIL import Image

VIEWS = {
    'front': (np.array([0, 0, 1.0]), np.array([0, 1.0, 0])),
    'back': (np.array([0, 0, -1.0]), np.array([0, 1.0, 0])),
    'side': (np.array([1.0, 0, 0]), np.array([0, 1.0, 0])),
    'side2': (np.array([-1.0, 0, 0]), np.array([0, 1.0, 0])),
    'persp': (np.array([0.75, 0.25, 0.95]), np.array([0, 1.0, 0])),
    'top': (np.array([0, 1.0, 0.001]), np.array([0, 0, 1.0])),
}


def render_points(P, N, UV, tex, view='front', height=512, bg=(24, 26, 30),
                  pad=0.04, splat=2, tint=None, box=None, col=None):
    P = np.asarray(P, np.float64)
    fwd, up = VIEWS[view] if isinstance(view, str) else view
    fwd = fwd / np.linalg.norm(fwd)
    right = np.cross(up, fwd)
    right /= np.linalg.norm(right)
    up2 = np.cross(fwd, right)
    X, Y, Z = P @ right, P @ up2, P @ fwd
    if box is None:
        x0, x1, y0, y1 = X.min(), X.max(), Y.min(), Y.max()
    else:
        x0, x1, y0, y1 = box[0], box[1], box[2], box[3]
    ext_x = (x1 - x0) * (1 + pad)
    ext_y = (y1 - y0) * (1 + pad)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    H = max(int(height / splat), 16)
    W = max(int(H * ext_x / max(ext_y, 1e-9)), 16)
    px = ((X - cx) / ext_x * 0.5 + 0.5) * (W - 1)
    py = (0.5 - (Y - cy) / ext_y * 0.5) * (H - 1)
    inside = (px >= 0) & (px < W) & (py >= 0) & (py < H)
    ix = np.clip(px.astype(np.int64), 0, W - 1)
    iy = np.clip(py.astype(np.int64), 0, H - 1)
    flat = (iy * W + ix)[inside]
    zz = Z[inside]
    if col is not None:
        col = np.asarray(col, np.float64)
    elif tex is not None:
        tw, th = tex.size
        img_a = np.asarray(tex).astype(np.float64)
        u = np.clip((UV[:, 0] % 1.0) * (tw - 1), 0, tw - 1).astype(np.int64)
        v = np.clip((1.0 - UV[:, 1] % 1.0) * (th - 1), 0, th - 1).astype(np.int64)
        col = img_a[v, u]
    else:
        col = np.full((len(P), 3), 190.0)
    if tint is not None:
        col = col * np.asarray(tint)
    if N is not None:
        shade = 0.55 + 0.45 * np.abs(np.asarray(N, np.float64) @ fwd)
    else:
        shade = np.ones(len(P))
    col = np.clip(col[inside] * shade[inside][:, None], 0, 255)
    best = np.full(H * W, -1e18)
    np.maximum.at(best, flat, zz)
    sel = zz >= best[flat] - 1e-9
    buf = np.zeros((H * W, 3))
    buf[flat[sel]] = col[sel]
    mask = best > -1e17
    img = np.zeros((H * W, 3))
    img[:] = bg
    img[mask] = buf[mask]
    out = Image.fromarray(np.clip(img.reshape(H, W, 3), 0, 255).astype(np.uint8))
    if splat > 1:
        out = out.resize((W * splat, H * splat), Image.NEAREST)
    return out


def montage(imgs, pad=4, bg=(18, 20, 24)):
    h = max(i.height for i in imgs)
    w = sum(i.width for i in imgs) + pad * (len(imgs) + 1)
    out = Image.new('RGB', (w, h + 2 * pad), bg)
    x = pad
    for im in imgs:
        out.paste(im, (x, (h - im.height) // 2 + pad))
        x += im.width + pad
    return out


def save(img, path):
    img.save(path)
    return path
