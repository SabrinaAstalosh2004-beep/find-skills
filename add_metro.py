"""Add a metro logo and an arrow showing the direction to the metro to the approved map.

Approval screenshot marks, replaced here:
  * yellow "M" in a circle -> metro logo as supplied by the user (Moscow Metro, 2014: red pin-shaped
    ring with a serif "М"), traced from the supplied image into vector form, ring centred on the mark;
  * yellow arrow           -> straight yellow arrow along the drawn one, tip where the drawn tip is.
The approved map is loaded unchanged; the new elements are drawn on transparent layers
(4x supersampled) and composited. Every other pixel stays identical.
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

YELLOW = (255, 204, 0)
YELLOW_EDGE = (190, 140, 0)
LOGO_RED = (199, 55, 54)
WHITE = (255, 255, 255)

MOVE_UP = 42.0                       # whole metro group raised by 15 % of its height (logo top 1347 .. arrow tip 1628)
SIGN_C = np.array([686.0, 1415.0 - MOVE_UP])  # centre of the yellow circle = centre of the logo ring
# Logo geometry traced from the supplied image (pixels of that image, ring centre at the origin).
L_R, L_W = 343.6, 62.0               # ring centre-line radius and stroke width
L_END = 134.8                        # left end of the ring (round cap), degrees, y down
L_TAIL = 375.0                       # straight tail from the 45-degree point, tangent, butt end
L_M = np.array([[447, 2094], [448, 2128], [585, 2128], [586, 2095], [567, 2094], [566, 2090], [587, 2034],
                [646, 2129], [705, 2034], [726, 2090], [725, 2094], [705, 2094], [706, 2128], [845, 2127],
                [845, 2094], [817, 2092], [725, 1859], [647, 1994], [567, 1859], [473, 2094]], float) - [644.5, 2016.6]
SIGN_OUTER_D = 3 * 45.0              # 3x the previous sign (disc 40 px + rim)
K = SIGN_OUTER_D / 2 / (L_R + L_W / 2)
ARROW_FROM = np.array([695.0, 1508.0 - MOVE_UP])  # start and tip of the yellow arrow
ARROW_TO = np.array([860.0, 1627.0 - MOVE_UP])
LINE_W, HEAD_LEN, HEAD_W = 15.0, 54.0, 48.0  # 3x the first version (5, 18, 16)
EDGE = 1.5  # thin darker contour: keeps the yellow arrow readable on the light map


def poly_mask(poly):
    big = np.zeros((H * SS, W * SS), np.uint8)
    cv2.fillPoly(big, [np.round(np.asarray(poly) * SS * 16).astype(np.int32).reshape(-1, 1, 2)], 255, cv2.LINE_8, shift=4)
    return big


def circle(c, r):
    big = np.zeros((H * SS, W * SS), np.uint8)
    cv2.circle(big, tuple(np.round(np.asarray(c) * SS * 16).astype(int)), int(round(r * SS * 16)), 255, -1, cv2.LINE_8, shift=4)
    return big


def down(big):
    return cv2.resize(np.asarray(big), (W, H), interpolation=cv2.INTER_AREA).astype(np.float32) / 255


def arrow(grow):
    """Shaft + head as one polygon; grow widens it all round (for the white edge)."""
    d = (ARROW_TO - ARROW_FROM) / np.linalg.norm(ARROW_TO - ARROW_FROM)
    n = np.array([-d[1], d[0]])
    tip = ARROW_TO + d * grow * 1.8
    tail = ARROW_FROM - d * grow
    neck = ARROW_TO - d * HEAD_LEN
    w, h = LINE_W / 2 + grow, HEAD_W / 2 + grow
    return [tail + n * w, neck + n * w, neck + n * h, tip, neck - n * h, neck - n * w, tail - n * w]


# metro logo
def thick_polyline(pts, width, round_start):
    """Stroke of the given width along pts: one polygon (offset sides), butt end, optional round start."""
    pts = np.asarray(pts)
    d = np.gradient(pts, axis=0)
    d /= np.linalg.norm(d, axis=1)[:, None]
    n = np.c_[-d[:, 1], d[:, 0]] * width / 2
    poly = np.r_[pts + n, (pts - n)[::-1]]
    big = poly_mask(poly)
    if round_start:
        big |= circle(pts[0], width / 2)
    return big


t = np.radians(np.linspace(L_END, 360 + 45, 600))          # ring: left end -> over the top -> 45 deg
arc = np.c_[np.cos(t), np.sin(t)] * L_R
tail_dir = np.array([-1.0, 1.0]) / np.sqrt(2)
tail = arc[-1] + np.outer(np.linspace(0, L_TAIL, 200)[1:], tail_dir)
centre_line = SIGN_C + K * np.r_[arc, tail]
logo = thick_polyline(centre_line, K * L_W, True) | poly_mask(SIGN_C + K * L_M)
EDGE_L = 1.5
logo_edge = cv2.dilate(logo, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(2 * EDGE_L * SS) + 1,) * 2))

# direction arrow
a_edge, a_body = poly_mask(arrow(EDGE)), poly_mask(arrow(0.0))

layers = [(down(a_edge), YELLOW_EDGE), (down(a_body), YELLOW), (down(logo_edge), WHITE), (down(logo), LOGO_RED)]
out = orig.astype(np.float32)
for a, col in layers:
    out = out * (1 - a[..., None]) + np.array(col, np.float32) * a[..., None]
out = np.round(out).astype(np.uint8)
mask = np.zeros((H, W), bool)
for a, _ in layers:
    mask |= a > 0
out[~mask] = orig[~mask]
Image.fromarray(out).save(OUT, optimize=True)
ys, xs = np.nonzero(down(logo) > 0)
json.dump({"move_up": MOVE_UP, "sign_centre": SIGN_C.tolist(), "logo_outer_d": SIGN_OUTER_D, "logo_bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())], "arrow_from": ARROW_FROM.tolist(),
           "arrow_to": ARROW_TO.tolist()}, open(OUT + ".metro.json", "w"))
np.save(OUT + ".metro_mask.npy", mask)
print("saved", OUT)
