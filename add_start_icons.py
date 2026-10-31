"""Mark the starts of the routes with small icons on the approved map.

  * red route (car)            -> red disc with a white car, just before the first red dash;
  * both green routes (on foot) -> green disc with a white running person, just before the first dash.
Icons are the size and style of the open-arch sign (22 px disc, 1.5 px white rim). The approved map is
loaded unchanged; the icons are drawn on transparent layers (4x supersampled) and composited.
"""
import json
import sys

import cv2
import numpy as np
from PIL import Image

SRC, OUT = sys.argv[1], sys.argv[2]
SS = 4

base = Image.open(SRC).convert("RGB")
W, H = base.size
orig = np.asarray(base).copy()

RED = (227, 38, 43)
GREEN = (30, 158, 58)
WHITE = (255, 255, 255)
R, RIM, GAP = 11.0, 1.5, 4.0

# route start points and the direction of travel there (from make_routes.py)
STARTS = {
    "car": {"start": (226.0 - 0.0382 * (1480 - 1200), 1480.0), "dir": (0.0, -1.0), "colour": RED},
    "walk_south": {"start": (244.5, 1385.0), "dir": (4.0, -203.0), "colour": GREEN},
    "walk_north": {"start": (250.0, 985.0), "dir": (0.0, 1.0), "colour": GREEN},
}


def big():
    return np.zeros((H * SS, W * SS), np.uint8)


def to_px(p):
    return np.round(np.asarray(p) * SS * 16).astype(np.int32)


def disc(c, r):
    m = big()
    cv2.circle(m, tuple(to_px(c)), int(round(r * SS * 16)), 255, -1, cv2.LINE_8, shift=4)
    return m


def poly(c, pts, s):
    m = big()
    cv2.fillPoly(m, [to_px(c + np.asarray(pts, float) * s).reshape(-1, 1, 2)], 255, cv2.LINE_8, shift=4)
    return m


def stroke(c, pts, s, w):
    """Polyline with round joins and caps, width w (unit coordinates)."""
    m = big()
    p = to_px(c + np.asarray(pts, float) * s).reshape(-1, 1, 2)
    cv2.polylines(m, [p], False, 255, int(round(w * s * SS)), cv2.LINE_8, shift=4)
    for q in p[:, 0]:
        cv2.circle(m, tuple(q), int(round(w * s * SS * 16 / 2)), 255, -1, cv2.LINE_8, shift=4)
    return m


def car(c, s):
    """Side view of a car facing right, unit box about [-1, 1] x [-0.6, 0.6]; wheels cut out of the body."""
    body = poly(c, [(-0.95, 0.30), (-0.95, -0.05), (-0.80, -0.12), (-0.45, -0.18), (-0.25, -0.50), (0.35, -0.50),
                    (0.60, -0.18), (0.90, -0.10), (0.97, 0.05), (0.97, 0.30)], s)
    windows = poly(c, [(-0.18, -0.38), (0.02, -0.38), (0.02, -0.20), (-0.33, -0.20)], s) | \
        poly(c, [(0.12, -0.38), (0.30, -0.38), (0.45, -0.20), (0.12, -0.20)], s)
    wheel_cut = disc(c + np.array([-0.52, 0.32]) * s, 0.30 * s) | disc(c + np.array([0.55, 0.32]) * s, 0.30 * s)
    wheels = disc(c + np.array([-0.52, 0.32]) * s, 0.21 * s) | disc(c + np.array([0.55, 0.32]) * s, 0.21 * s)
    return ((body & ~windows) & ~wheel_cut) | wheels


def runner(c, s):
    """Running person facing right, unit box about [-1, 1] x [-1, 1]."""
    w = 0.26
    head = disc(c + np.array([0.18, -0.78]) * s, 0.20 * s)
    torso = stroke(c, [(0.08, -0.48), (-0.12, 0.05)], s, w)
    arm_f = stroke(c, [(0.04, -0.38), (0.32, -0.18), (0.55, -0.40)], s, w * 0.8)
    arm_b = stroke(c, [(0.04, -0.38), (-0.25, -0.30), (-0.42, -0.05)], s, w * 0.8)
    leg_f = stroke(c, [(-0.12, 0.05), (0.22, 0.28), (0.15, 0.75)], s, w)
    leg_b = stroke(c, [(-0.12, 0.05), (-0.30, 0.42), (-0.62, 0.55)], s, w)
    return head | torso | arm_f | arm_b | leg_f | leg_b


def down(m):
    return cv2.resize(m, (W, H), interpolation=cv2.INTER_AREA).astype(np.float32) / 255


layers, meta = [], {}
for name, st in STARTS.items():
    p = np.array(st["start"], float)
    d = np.array(st["dir"], float)
    d /= np.linalg.norm(d)
    c = p - d * (R + RIM + GAP)            # on the route line, just before its first dash
    rim, dsk = disc(c, R + RIM), disc(c, R)
    glyph = (car(c, 8.4) if name == "car" else runner(c, 7.2)) & dsk
    layers += [(down(rim), WHITE), (down(dsk), st["colour"]), (down(glyph), WHITE)]
    meta[name] = {"centre": c.round(2).tolist(), "route_start": p.tolist()}

out = orig.astype(np.float32)
for a, col in layers:
    out = out * (1 - a[..., None]) + np.array(col, np.float32) * a[..., None]
out = np.round(out).astype(np.uint8)
mask = np.zeros((H, W), bool)
for a, _ in layers:
    mask |= a > 0
out[~mask] = orig[~mask]
Image.fromarray(out).save(OUT, optimize=True)
json.dump(meta, open(OUT + ".icons.json", "w"))
np.save(OUT + ".icons_mask.npy", mask)
print("saved", OUT)
