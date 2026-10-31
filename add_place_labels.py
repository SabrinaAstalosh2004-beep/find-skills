"""Add the place names "Гарновский сквер" and "Спортивная площадка" to the approved map.

Approval screenshot marks, replaced here:
  * yellow circle on the courtyard lawn -> "Гарновский сквер" (park-name style of "Польский сад"),
  * yellow check mark on the sports field -> "Спортивная площадка", smaller than every other label.
The approved map is loaded unchanged; the labels are drawn on transparent layers (4x supersampled)
and composited. Every other pixel stays identical.
"""
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SRC, OUT = sys.argv[1], sys.argv[2]
SS = 4

base = Image.open(SRC).convert("RGB")
S = int(os.environ.get("SCALE", "1"))  # hi-res build: draw natively at S x the map resolution
W, H = base.size[0] // S, base.size[1] // S
orig = np.asarray(base).copy()
WHITE = (255, 255, 255)

LABELS = [
    # text lines, centre (= centre of the yellow mark), font, size, colour, halo
    {"name": "garnovsky", "lines": ["Гарновский сквер"], "centre": (490.0, 1028.0),
     "font": "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf", "size": 18, "colour": (88, 128, 52), "halo": 2.0},
    {"name": "sports", "lines": ["Спортивная", "площадка"], "centre": (570.0, 1239.0),  # mark x 549 + 15 % of the field width (140 px)
     "font": "/usr/share/fonts/opentype/inter/Inter-Medium.otf", "size": 12, "colour": (66, 84, 60), "halo": 1.5},
]


def down(img):
    return cv2.resize(np.asarray(img), (W * S, H * S), interpolation=cv2.INTER_AREA).astype(np.float32) / 255


layers, meta = [], {}
for lb in LABELS:
    font = ImageFont.truetype(lb["font"], lb["size"] * SS)
    asc, _ = font.getmetrics()
    cap = font.getbbox("Н")[3] - font.getbbox("Н")[1]
    line_h = round(cap * 1.55)
    n = len(lb["lines"])
    block = cap + (n - 1) * line_h                       # first cap top .. last baseline
    cx, cy = lb["centre"][0] * SS, lb["centre"][1] * SS
    txt = Image.new("L", (W * SS, H * SS), 0)
    halo = Image.new("L", (W * SS, H * SS), 0)
    dt, dh = ImageDraw.Draw(txt), ImageDraw.Draw(halo)
    for i, s in enumerate(lb["lines"]):
        w = font.getlength(s)
        pos = (cx - w / 2, cy - block / 2 + i * line_h - (asc - cap))  # centred lines, centred block
        dt.text(pos, s, font=font, fill=255)
        dh.text(pos, s, font=font, fill=255, stroke_width=round(lb["halo"] * SS), stroke_fill=255)
    a_t, a_h = down(txt), down(halo)
    layers += [(a_h, WHITE), (a_t, lb["colour"])]
    ys, xs = np.nonzero(a_t > 0.3)
    meta[lb["name"]] = {"text": " ".join(lb["lines"]), "centre": lb["centre"], "font_px": lb["size"],
                        "cap_px": cap / SS, "ink_bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]}

out = orig.astype(np.float32)
for a, col in layers:
    out = out * (1 - a[..., None]) + np.array(col, np.float32) * a[..., None]
out = np.round(out).astype(np.uint8)
mask = np.zeros((H * S, W * S), bool)
for a, _ in layers:
    mask |= a > 0
out[~mask] = orig[~mask]
Image.fromarray(out).save(OUT, optimize=True)
json.dump(meta, open(OUT + ".labels.json", "w"), ensure_ascii=False)
np.save(OUT + ".labels_mask.npy", mask)
print("saved", OUT)
