"""Add a geotag and the caption "Открытая арка для входа" to the approved route map.

The approved map (output of make_routes.py) is loaded unchanged; the pin and the caption are
drawn on transparent layers (4x supersampled) and composited. Every other pixel stays identical.
The pin replaces the yellow hand-drawn arrow of the approval screenshot: its tip sits where the
arrow tip was (just below the arch passage, under the green dash) and it leans the same way, so it
points into the arch without covering any route dash or the house number "120".
"""
import json
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SRC, OUT = sys.argv[1], sys.argv[2]
SS = 4

base = Image.open(SRC).convert("RGB")
W, H = base.size
orig = np.asarray(base).copy()

PIN = (33, 110, 224)
TEXT = (36, 37, 40)
WHITE = (255, 255, 255)

# ---------- pin ----------
TIP = np.array([325.0, 1202.0])                 # yellow arrow tip, moved 9 px right to clear "120"
AXIS = np.array([-0.5, -0.866])                 # centre -> tip, as the yellow arrow (about 30 deg from vertical)
R = 10.0                                        # head radius
DIST = 2.3 * R                                  # centre-to-tip distance
OUTLINE = 1.5                                   # white edge separating the pin from the map
C = TIP - AXIS * DIST


def pin_poly(r, tip_ext=0.0):
    """Teardrop outline: circle of radius r around C plus the two tangents to the tip."""
    tip = TIP + AXIS * tip_ext
    dist = np.linalg.norm(tip - C)
    a = np.arccos(r / dist)                     # angle between the axis and the tangent points
    phi = np.arctan2(AXIS[1], AXIS[0])
    arc = np.linspace(phi + a, phi + 2 * np.pi - a, 200)
    pts = [C + r * np.array([np.cos(t), np.sin(t)]) for t in arc]
    return np.array(pts + [tip])


def fill(poly):
    big = np.zeros((H * SS, W * SS), np.uint8)
    cv2.fillPoly(big, [np.round(poly * SS * 16).astype(np.int32).reshape(-1, 1, 2)], 255, cv2.LINE_8, shift=4)
    return big


def circle(c, r):
    big = np.zeros((H * SS, W * SS), np.uint8)
    cv2.circle(big, tuple(np.round(c * SS * 16).astype(int)), int(round(r * SS * 16)), 255, -1, cv2.LINE_8, shift=4)
    return big


down = lambda big: cv2.resize(big, (W, H), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
pin_body = fill(pin_poly(R))
pin_edge = fill(pin_poly(R + OUTLINE, OUTLINE * 1.6))
dot = circle(C, R * 0.38)
a_edge = down(pin_edge)
a_body = down(pin_body & ~dot)

# ---------- caption ----------
FONT = "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf"
FS, LINE_GAP, HALO = 19, 4, 2
LINES = ["Открытая арка", "для входа"]
font = ImageFont.truetype(FONT, FS * SS)
asc, desc = font.getmetrics()
X0 = C[0] + R + 9                               # left edge of the caption, right of the pin head
cap = font.getbbox("О")[3] - font.getbbox("О")[1]
txt = Image.new("L", (W * SS, H * SS), 0)
halo = Image.new("L", (W * SS, H * SS), 0)
dt, dh = ImageDraw.Draw(txt), ImageDraw.Draw(halo)
line_h = cap + (FS * SS) // 3 + LINE_GAP * SS
top_cap = C[1] * SS - (2 * cap + line_h - cap) / 2   # centre the two cap-height lines on the pin head
for i, s in enumerate(LINES):
    y_cap = top_cap + i * line_h
    pos = (X0 * SS, y_cap - (asc - cap))
    dt.text(pos, s, font=font, fill=255)
    dh.text(pos, s, font=font, fill=255, stroke_width=HALO * SS, stroke_fill=255)
a_txt = down(np.asarray(txt))
a_halo = down(np.asarray(halo))

# ---------- composite ----------
out = orig.astype(np.float32)
for a, col in ((a_halo, WHITE), (a_txt, TEXT), (a_edge, WHITE), (a_body, PIN)):
    out = out * (1 - a[..., None]) + np.array(col, np.float32) * a[..., None]
out = np.round(out).astype(np.uint8)
mask = (a_halo > 0) | (a_edge > 0)
out[~mask] = orig[~mask]
Image.fromarray(out).save(OUT, optimize=True)

ys, xs = np.nonzero(a_halo > 0)
json.dump({"pin_tip": TIP.tolist(), "pin_centre": C.round(1).tolist(), "pin_axis": AXIS.tolist(),
           "caption": " ".join(LINES), "caption_bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]},
          open(OUT + ".marker.json", "w"), ensure_ascii=False)
np.save(OUT + ".marker_mask.npy", mask)
print("saved", OUT)
