"""Add the destination geotag and the open-arch sign to the approved route map.

Approval screenshot marks, replaced here:
  * blue check mark  -> geotag (pin) of the destination, tip where the check mark's vertex was;
  * yellow arrow     -> round sign with an arch symbol and the caption "Открытая арка для входа".
The approved map (output of make_routes.py) is loaded unchanged; the new elements are drawn on
transparent layers (4x supersampled) and composited. Every other pixel stays identical.
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
SIGN = (80, 92, 110)
TEXT = (36, 37, 40)
WHITE = (255, 255, 255)
OUTLINE = 1.5  # white edge separating icons from the map


def fill(poly):
    big = np.zeros((H * SS, W * SS), np.uint8)
    cv2.fillPoly(big, [np.round(np.asarray(poly) * SS * 16).astype(np.int32).reshape(-1, 1, 2)], 255, cv2.LINE_8, shift=4)
    return big


def circle(c, r):
    big = np.zeros((H * SS, W * SS), np.uint8)
    cv2.circle(big, tuple(np.round(np.asarray(c) * SS * 16).astype(int)), int(round(r * SS * 16)), 255, -1, cv2.LINE_8, shift=4)
    return big


def down(big):
    return cv2.resize(big, (W, H), interpolation=cv2.INTER_AREA).astype(np.float32) / 255


# ---------- destination geotag (replaces the blue check mark) ----------
PIN_TIP = np.array([619.0, 829.0])   # lowest point (vertex) of the blue check mark
PIN_R = 22.0                          # 2x the first version (11)
PIN_C = PIN_TIP - np.array([0.0, 2.3 * PIN_R])


def pin_poly(r, tip):
    a = np.arccos(r / np.linalg.norm(tip - PIN_C))
    phi = np.pi / 2  # centre -> tip points down
    arc = np.linspace(phi + a, phi + 2 * np.pi - a, 200)
    return np.array([PIN_C + r * np.array([np.cos(t), np.sin(t)]) for t in arc] + [tip])


pin_body = fill(pin_poly(PIN_R, PIN_TIP))
pin_edge = fill(pin_poly(PIN_R + OUTLINE, PIN_TIP + np.array([0, OUTLINE * 1.6])))
pin_dot = circle(PIN_C, PIN_R * 0.38)

# ---------- open-arch sign (replaces the yellow arrow) ----------
SIGN_C = np.array([350.0, 1226.0])   # at the yellow arrow, clear of "120" and the route dashes
SIGN_R = 22.0                        # 2x the first version (11)
GS = SIGN_R / 11.0                   # glyph scale
sign_disc = circle(SIGN_C, SIGN_R)
sign_edge = circle(SIGN_C, SIGN_R + OUTLINE)


def arch(cx, base_y, half_w, h):
    """Arch silhouette: vertical sides up to a semicircular top (closed polygon)."""
    top_c = base_y - h + half_w
    pts = [(cx - half_w, base_y), (cx - half_w, top_c)]
    pts += [(cx + half_w * np.cos(t), top_c - half_w * np.sin(t)) for t in np.linspace(np.pi, 0, 60)]
    pts += [(cx + half_w, base_y)]
    return pts


gx, gb = SIGN_C[0], SIGN_C[1] + 6.0 * GS  # glyph: white arch frame with an open passage
glyph = fill(arch(gx, gb, 6.5 * GS, 12.5 * GS)) & ~fill(arch(gx, gb + 0.01, 3.2 * GS, 8.0 * GS))

# caption
FONT = "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf"
FS, LINE_GAP, HALO = 19, 4, 2
LINES = ["Открытая арка", "для входа"]
font = ImageFont.truetype(FONT, FS * SS)
asc, desc = font.getmetrics()
cap = font.getbbox("О")[3] - font.getbbox("О")[1]
X0 = SIGN_C[0] + SIGN_R + 6
line_h = cap + (FS * SS) // 3 + LINE_GAP * SS
top_cap = SIGN_C[1] * SS - (cap + line_h) / 2   # two cap-height lines centred on the sign
txt = Image.new("L", (W * SS, H * SS), 0)
halo = Image.new("L", (W * SS, H * SS), 0)
dt, dh = ImageDraw.Draw(txt), ImageDraw.Draw(halo)
for i, s in enumerate(LINES):
    pos = (X0 * SS, top_cap + i * line_h - (asc - cap))
    dt.text(pos, s, font=font, fill=255)
    dh.text(pos, s, font=font, fill=255, stroke_width=HALO * SS, stroke_fill=255)

# ---------- composite ----------
layers = [
    (down(np.asarray(halo)), WHITE), (down(np.asarray(txt)), TEXT),
    (down(sign_edge), WHITE), (down(sign_disc), SIGN), (down(glyph & sign_disc), WHITE),
    (down(pin_edge), WHITE), (down(pin_body & ~pin_dot), PIN),
]
out = orig.astype(np.float32)
for a, col in layers:
    out = out * (1 - a[..., None]) + np.array(col, np.float32) * a[..., None]
out = np.round(out).astype(np.uint8)
mask = np.zeros((H, W), bool)
for a, _ in layers:
    mask |= a > 0
out[~mask] = orig[~mask]
Image.fromarray(out).save(OUT, optimize=True)

ys, xs = np.nonzero(layers[0][0] > 0)
json.dump({"pin_tip": PIN_TIP.tolist(), "pin_centre": PIN_C.tolist(), "pin_r": PIN_R,
           "sign_centre": SIGN_C.tolist(), "sign_r": SIGN_R, "caption": " ".join(LINES),
           "caption_bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]},
          open(OUT + ".marker.json", "w"), ensure_ascii=False)
np.save(OUT + ".marker_mask.npy", mask)
print("saved", OUT)
