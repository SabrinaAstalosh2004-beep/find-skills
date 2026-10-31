"""Mark the starts of the routes with icons on the approved map.

  * red route (car)             -> red disc with a white car;
  * both green routes (on foot) -> green disc with a white running person.
Icons are 3x the open-arch sign (66 px disc, 3 px white rim). Each icon sits as close to the start of its
route as possible without covering any route, sign, label, traffic light or other map ink: the position
is searched around the start point, within a sector that keeps it on the right side of its route. The approved map is loaded unchanged; the icons are drawn on
transparent layers (8x supersampled for clean edges) and composited.
"""
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image

MAP, SRC, OUT = sys.argv[1], sys.argv[2], sys.argv[3]  # original map (for clearance), approved PNG, result
SS = 8

base = Image.open(SRC).convert("RGB")
S = int(os.environ.get("SCALE", "1"))  # hi-res build: draw natively at S x the map resolution
W, H = base.size[0] // S, base.size[1] // S
orig = np.asarray(base).copy()
omap = np.asarray(Image.open(MAP).convert("RGB")).astype(int)

RED = (227, 38, 43)
GREEN = (30, 158, 58)
WHITE = (255, 255, 255)
R, RIM, MARGIN = 33.0, 3.0, 2.0

# route start points and the direction of travel there (from make_routes.py)
STARTS = {
    # sector: allowed directions from the start to the icon (degrees, y down: 90 = south, 180 = west)
    "car": {"start": (226.0 - 0.0382 * (1480 - 1200), 1480.0), "sector": (90, 200), "colour": RED},       # on the road
    "walk_south": {"start": (244.5, 1385.0), "sector": (0, 90), "colour": GREEN},       # away from the red line
    "walk_north": {"start": (250.0, 985.0), "sector": (-90, 90), "colour": GREEN},      # away from the label
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


def rounded(pts, r, n=24):
    """Polygon with every corner rounded by radius r (unit coordinates)."""
    pts = np.asarray(pts, float)
    out = []
    for i in range(len(pts)):
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
        u, v = (a - b) / np.linalg.norm(a - b), (c - b) / np.linalg.norm(c - b)
        ang = np.arccos(np.clip(u @ v, -1, 1))
        t = min(r / np.tan(ang / 2), 0.45 * np.linalg.norm(a - b), 0.45 * np.linalg.norm(c - b))
        rr = t * np.tan(ang / 2)
        p1, p2 = b + u * t, b + v * t
        bis = (u + v) / np.linalg.norm(u + v)
        ctr = b + bis * np.hypot(t, rr)
        a1, a2 = np.arctan2(*(p1 - ctr)[::-1]), np.arctan2(*(p2 - ctr)[::-1])
        da = (a2 - a1 + np.pi) % (2 * np.pi) - np.pi
        out += [ctr + rr * np.array([np.cos(a1 + da * k / n), np.sin(a1 + da * k / n)]) for k in range(n + 1)]
    return np.array(out)


def stroke(c, pts, s, w):
    """Polyline with round joins and caps, width w (unit coordinates)."""
    m = big()
    p = to_px(c + np.asarray(pts, float) * s).reshape(-1, 1, 2)
    cv2.polylines(m, [p], False, 255, int(round(w * s * SS)), cv2.LINE_8, shift=4)
    for q in p[:, 0]:
        cv2.circle(m, tuple(q), int(round(w * s * SS * 16 / 2)), 255, -1, cv2.LINE_8, shift=4)
    return m


def car(c, s):
    """Side view of a passenger car facing right, unit box about [-1, 1] x [-0.55, 0.55]."""
    body = poly(c, rounded([(-0.98, -0.12), (-0.62, -0.16), (-0.36, -0.50), (0.24, -0.50), (0.56, -0.16),
                            (0.92, -0.10), (0.98, 0.04), (0.98, 0.30), (-0.98, 0.30)], 0.09), s)
    rear_win = poly(c, rounded([(-0.52, -0.17), (-0.31, -0.41), (-0.09, -0.41), (-0.09, -0.17)], 0.04), s)
    front_win = poly(c, rounded([(-0.01, -0.41), (0.19, -0.41), (0.42, -0.17), (-0.01, -0.17)], 0.04), s)
    lamp = poly(c, rounded([(0.80, -0.04), (0.98, -0.04), (0.98, 0.04), (0.80, 0.04)], 0.03), s)
    door = stroke(c, [(-0.05, -0.14), (-0.05, 0.22)], s, 0.035)
    w1, w2 = np.array([-0.56, 0.30]), np.array([0.58, 0.30])
    arches = disc(c + w1 * s, 0.29 * s) | disc(c + w2 * s, 0.29 * s)
    tyres = disc(c + w1 * s, 0.22 * s) | disc(c + w2 * s, 0.22 * s)
    hubs = disc(c + w1 * s, 0.085 * s) | disc(c + w2 * s, 0.085 * s)
    return (body & ~rear_win & ~front_win & ~lamp & ~door & ~arches) | (tyres & ~hubs)


def runner(c, s):
    """Running person facing right, unit box about [-1, 1] x [-1, 1]."""
    w = 0.25
    head = disc(c + np.array([0.20, -0.76]) * s, 0.19 * s)
    torso = stroke(c, [(0.10, -0.46), (-0.10, 0.04)], s, w)
    arm_f = stroke(c, [(0.06, -0.37), (0.33, -0.17), (0.56, -0.38)], s, w * 0.78)
    arm_b = stroke(c, [(0.06, -0.37), (-0.24, -0.30), (-0.43, -0.06)], s, w * 0.78)
    leg_f = stroke(c, [(-0.10, 0.04), (0.24, 0.27), (0.16, 0.74)], s, w)
    leg_b = stroke(c, [(-0.10, 0.04), (-0.30, 0.42), (-0.64, 0.54)], s, w)
    foot = stroke(c, [(0.16, 0.74), (0.32, 0.76)], s, w * 0.8)
    return head | torso | arm_f | arm_b | leg_f | leg_b | foot


def down(m):
    return cv2.resize(m, (W * S, H * S), interpolation=cv2.INTER_AREA).astype(np.float32) / 255


if S == 1:
    # everything the icons must leave visible: all drawn elements and dark map ink (text, lane arrows, lights)
    keep = np.any(orig.astype(int) != omap, -1) | (omap.max(-1) < 175) & (np.abs(omap[..., 0] - omap[..., 2]) < 25)
    keep |= (omap[..., 0] > 200) & (omap[..., 1] < 120)  # red traffic-light lamps etc.
    keep = cv2.dilate(keep.astype(np.uint8), np.ones((2 * int(MARGIN) + 1,) * 2, np.uint8)) > 0
    yy, xx = np.mgrid[0:H, 0:W]
else:  # hi-res build: same icon centres as the 1x build
    FIXED = json.load(open(os.environ["ICONS_JSON"]))


def free(c):
    inside = (xx - c[0]) ** 2 + (yy - c[1]) ** 2 <= (R + RIM + 1) ** 2
    return not (inside & keep).any()


layers, meta = [], {}
for name, st in STARTS.items():
    p = np.array(st["start"], float)
    best = None if S == 1 else np.array(FIXED[name]["centre"])
    for rad in (np.arange(R + RIM + 2, R + RIM + 90, 1.0) if S == 1 else []):  # nearest free spot to the route start
        for ang in np.radians(np.arange(st["sector"][0], st["sector"][1] + 1, 5)):
            c = p + rad * np.array([np.cos(ang), np.sin(ang)])
            if free(c):
                best = c
                break
        if best is not None:
            break
    assert best is not None, name
    c = best
    rim, dsk = disc(c, R + RIM), disc(c, R)
    glyph = (car(c, 25.2) if name == "car" else runner(c, 21.6)) & dsk
    layers += [(down(rim), WHITE), (down(dsk), st["colour"]), (down(glyph), WHITE)]
    if S == 1:
        keep |= down(rim) > 0                                   # icons must not overlap each other either
    meta[name] = {"centre": c.round(2).tolist(), "route_start": p.tolist(), "radius": R + RIM}

out = orig.astype(np.float32)
for a, col in layers:
    out = out * (1 - a[..., None]) + np.array(col, np.float32) * a[..., None]
out = np.round(out).astype(np.uint8)
mask = np.zeros((H * S, W * S), bool)
for a, _ in layers:
    mask |= a > 0
out[~mask] = orig[~mask]
Image.fromarray(out).save(OUT, optimize=True)
json.dump(meta, open(OUT + ".icons.json", "w"))
np.save(OUT + ".icons_mask.npy", mask)
print("saved", OUT)
