"""Give the flat fills of the map screenshot realistic procedural textures, without moving any outline.

Usage: texture_map.py <clean 1x map> <out> [scale]

The 1x map is classified by colour (water, lawn, tree canopy, asphalt, pavement, three kinds of roofs).
Each class gets a soft weight (1 inside the fill, fading to ~0.5 across its anti-aliased outline), so
outlines stay exactly where they are while the texture strength changes smoothly; lane markings, icons
and map labels (plus a 1 px zone around dark text) are not retextured. The map is upscaled S x (Lanczos)
and each class gets a seeded procedural texture at full resolution:
  water   - deeper river blue with wind ripples along the Fontanka;
  lawn    - fine grass grain with mowing variation; canopy - clumped foliage with self-shadowing;
  asphalt - aggregate grain; pavement - fine paving grain; roofs - roofing grain and darker roof edges.
"""
import sys

import cv2
import numpy as np
from PIL import Image

SRC, OUT = sys.argv[1], sys.argv[2]
S = int(sys.argv[3]) if len(sys.argv) > 3 else 3
rng = np.random.default_rng(20261031)

m1 = np.asarray(Image.open(SRC).convert("RGB")).astype(np.float32)
h1, w1 = m1.shape[:2]
H, W = h1 * S, w1 * S

# class prototypes (RGB of the flat fills), realistic target colour, blend towards it, tolerance
CLASSES = {
    "water":    {"proto": [(162, 210, 246)], "real": (78, 136, 178), "mix": 0.55, "tol": 12},
    "lawn":     {"proto": [(222, 238, 202), (222, 242, 202)], "real": (150, 190, 106), "mix": 0.45, "tol": 9},
    "canopy":   {"proto": [(210, 234, 182), (202, 218, 186)], "real": (96, 146, 70), "mix": 0.50, "tol": 9},
    "asphalt":  {"proto": [(190, 198, 210), (194, 198, 210), (186, 194, 210), (182, 190, 202)],
                 "real": (138, 143, 152), "mix": 0.45, "tol": 7},
    "pavement": {"proto": [(250, 250, 246), (250, 250, 250), (246, 246, 246), (250, 246, 246), (246, 242, 238)],
                 "real": (226, 223, 216), "mix": 0.45, "tol": 5},
    "roof":     {"proto": [(230, 222, 218), (230, 222, 222), (226, 222, 218), (234, 226, 222), (230, 226, 222)],
                 "real": (196, 170, 150), "mix": 0.45, "tol": 6},
    "roof_lav": {"proto": [(226, 222, 234), (222, 222, 234)], "real": (176, 174, 192), "mix": 0.45, "tol": 6},
    "roof_grey": {"proto": [(226, 226, 226), (230, 230, 230)], "real": (182, 182, 184), "mix": 0.45, "tol": 4},
}
names = list(CLASSES)

# ---------- classify the 1x map ----------
best = np.full((h1, w1), 1e9, np.float32)
cls = np.full((h1, w1), -1, np.int16)
for i, n in enumerate(names):
    for p in CLASSES[n]["proto"]:
        d = np.abs(m1 - np.array(p, np.float32)).max(-1)
        hit = (d <= CLASSES[n]["tol"]) & (d < best)
        best[hit], cls[hit] = d[hit], i
ink = (m1.mean(-1) < 185) & (cls < 0)                                 # map text, icons, markings
keep_out = cv2.dilate(ink.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0


def weight(i):
    """Soft class weight at full resolution: 1 inside the fill, ~0.5 on its anti-aliased outline, 0 outside.
    The outline stays where it is; only the strength of the texture fades across it."""
    m = ((cls == i) & ~keep_out).astype(np.float32)
    up = cv2.resize(m, (W, H), interpolation=cv2.INTER_LINEAR)
    return cv2.GaussianBlur(up, (0, 0), 0.5 * S)


base = np.asarray(Image.fromarray(m1.astype(np.uint8)).resize((W, H), Image.LANCZOS)).astype(np.float32)


# ---------- procedural noise ----------
def fractal(octaves, base_cell, gain=0.55, aniso=(1.0, 1.0)):
    out = np.zeros((H, W), np.float32)
    amp, cell, tot = 1.0, base_cell, 0.0
    for _ in range(octaves):
        gh = max(2, int(H / (cell * aniso[1])))
        gw = max(2, int(W / (cell * aniso[0])))
        g = rng.standard_normal((gh, gw)).astype(np.float32)
        out += amp * cv2.resize(g, (W, H), interpolation=cv2.INTER_CUBIC)
        tot += amp
        amp *= gain
        cell /= 2
    out /= tot
    return out / (out.std() + 1e-6)


def rotated(field, deg):
    M = cv2.getRotationMatrix2D((W / 2, H / 2), deg, 1.0)
    return cv2.warpAffine(field, M, (W, H), borderMode=cv2.BORDER_REFLECT)


grain = fractal(2, 2.0)                                     # very fine grain (2-1 px)
mottle = fractal(4, 60.0)                                   # large soft variation
ripples = rotated(fractal(3, 10.0, aniso=(6.0, 1.0)), 25)   # elongated along the river (embankment ~25 deg)
canopy_n = fractal(4, 14.0, gain=0.6)

out = base.copy()


touched = np.zeros((H, W), np.float32)


def apply(name, lum_mod, extra=None):
    c = CLASSES[name]
    wgt = weight(names.index(name))
    m = wgt > 0.002
    if not m.any():
        return
    real = np.array(c["real"], np.float32)
    col = base[m] * (1 - c["mix"]) + real * c["mix"]
    col *= (1 + lum_mod[m])[:, None]
    if extra is not None:
        col += extra[m]
    a = wgt[m][:, None]
    out[m] += a * (col - base[m])
    touched[m] += wgt[m]


# water: ripples + soft depth variation + sparse glints
glint = np.clip(ripples - 2.2, 0, None)[..., None] * np.array([40, 45, 45], np.float32)
apply("water", 0.06 * ripples + 0.05 * mottle, glint)
# lawn: grass grain + mowing variation
apply("lawn", 0.07 * grain + 0.05 * mottle + 0.03 * fractal(2, 6.0))
# tree canopy: clumps with light from the top-left
clumps = cv2.GaussianBlur(canopy_n, (0, 0), 1.2)
shade = cv2.filter2D(clumps, -1, np.array([[1, 1, 0], [1, 0, -1], [0, -1, -1]], np.float32) / 4)
apply("canopy", 0.16 * clumps + 0.18 * shade + 0.06 * grain)
# asphalt and pavement
apply("asphalt", 0.06 * grain + 0.03 * mottle)
apply("pavement", 0.025 * grain + 0.015 * mottle)
# roofs: roofing grain and darker edges (distance to the roof outline)
for n in ("roof", "roof_lav", "roof_grey"):
    m = (weight(names.index(n)) > 0.5).astype(np.uint8)
    big = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (12 * S + 1,) * 2))
    big = cv2.dilate(big, np.ones((5, 5), np.uint8)) & m          # whole buildings only, not bridges or paths
    dist = cv2.distanceTransform(cv2.dilate(m, np.ones((3, 3), np.uint8)), cv2.DIST_L2, 5)
    edge = -0.10 * np.exp(-dist / (2.5 * S)) * cv2.GaussianBlur(big.astype(np.float32), (0, 0), S)
    apply(n, 0.035 * grain + 0.03 * mottle + edge)

res = np.clip(np.round(out), 0, 255).astype(np.uint8)
untouched = touched < 0.002
res[untouched] = np.clip(np.round(base[untouched]), 0, 255).astype(np.uint8)
Image.fromarray(res).save(OUT, optimize=True)
np.save(OUT + ".untouched.npy", untouched)
print("saved", OUT, res.shape, "retextured", round(100 * (~untouched).mean(), 1), "%")
