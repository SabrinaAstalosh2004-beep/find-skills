"""Add a metro sign and an arrow showing the direction to the metro to the approved map.

Approval screenshot marks, replaced here:
  * yellow "M" in a circle -> metro sign (blue disc, white "М", white rim), centred on the mark;
  * yellow arrow           -> straight blue arrow along the drawn one, tip where the drawn tip is.
The approved map is loaded unchanged; the new elements are drawn on transparent layers
(4x supersampled) and composited. Every other pixel stays identical.
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

BLUE = (0, 114, 188)
WHITE = (255, 255, 255)

SIGN_C = np.array([686.0, 1415.0])  # centre of the yellow circle
SIGN_R = 20.0
RIM = 2.5
ARROW_FROM = np.array([695.0, 1508.0])  # start and tip of the yellow arrow
ARROW_TO = np.array([860.0, 1627.0])
LINE_W, HEAD_LEN, HEAD_W = 5.0, 18.0, 16.0
EDGE = 1.5  # thin white edge around the arrow, as around the other signs


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


# metro sign
disc = circle(SIGN_C, SIGN_R)
rim = circle(SIGN_C, SIGN_R + RIM)
font = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Bold.otf", 26 * SS)
glyph = Image.new("L", (W * SS, H * SS), 0)
bb = font.getbbox("М")
ImageDraw.Draw(glyph).text((SIGN_C[0] * SS - (bb[0] + bb[2]) / 2, SIGN_C[1] * SS - (bb[1] + bb[3]) / 2), "М",
                           font=font, fill=255)
glyph = np.asarray(glyph) & disc

# direction arrow
a_edge, a_body = poly_mask(arrow(EDGE)), poly_mask(arrow(0.0))

layers = [(down(a_edge), WHITE), (down(a_body), BLUE),
          (down(rim), WHITE), (down(disc), BLUE), (down(glyph), WHITE)]
out = orig.astype(np.float32)
for a, col in layers:
    out = out * (1 - a[..., None]) + np.array(col, np.float32) * a[..., None]
out = np.round(out).astype(np.uint8)
mask = np.zeros((H, W), bool)
for a, _ in layers:
    mask |= a > 0
out[~mask] = orig[~mask]
Image.fromarray(out).save(OUT, optimize=True)
json.dump({"sign_centre": SIGN_C.tolist(), "sign_r": SIGN_R, "arrow_from": ARROW_FROM.tolist(),
           "arrow_to": ARROW_TO.tolist()}, open(OUT + ".metro.json", "w"))
np.save(OUT + ".metro_mask.npy", mask)
print("saved", OUT)
