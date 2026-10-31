"""Add the venue caption "MUR_IRAA / маникюр" next to the destination geotag on the approved map.

Blue text (the geotag's colour), two left-aligned lines on a bright yellow rounded plate with a thin
white edge, centred on the geotag head. The approved map is loaded unchanged; the caption is drawn on transparent layers
(4x supersampled) and composited. Every other pixel stays identical.
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

BLUE = (33, 110, 224)          # geotag colour (add_arch_marker.py)
WHITE = (255, 255, 255)
PIN_HEAD = (619.0, 778.4)      # geotag head centre: tip (619, 829) - 2.3 * 22
PIN_RIGHT = 619.0 + 22 + 1.5   # right edge of the geotag head incl. its white rim
LINES = [("MUR_IRAA", "/usr/share/fonts/opentype/inter/Inter-Bold.otf"),
         ("маникюр", "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf")]
FS, GAP = 38, 6                # 2x the first version (19 px)
PLATE = (255, 214, 0)          # bright yellow plate
PAD_X, PAD_Y, CORNER, EDGE = 10, 8, 10, 2


def down(img):
    return cv2.resize(np.asarray(img), (W * S, H * S), interpolation=cv2.INTER_AREA).astype(np.float32) / 255


fonts = [ImageFont.truetype(f, FS * SS) for _, f in LINES]
cap = fonts[0].getbbox("H")[3] - fonts[0].getbbox("H")[1]
line_h = round(cap * 1.55)
x0 = (PIN_RIGHT + GAP + EDGE + PAD_X) * SS
top_cap = PIN_HEAD[1] * SS - (cap + line_h) / 2      # two cap-height lines centred on the geotag head
txt = Image.new("L", (W * SS, H * SS), 0)
dt = ImageDraw.Draw(txt)
for i, ((s, _), font) in enumerate(zip(LINES, fonts)):
    asc, _ = font.getmetrics()
    dt.text((x0, top_cap + i * line_h - (asc - cap)), s, font=font, fill=255)
ink = np.asarray(txt)
ys, xs = np.nonzero(ink)
box = np.array([xs.min() - PAD_X * SS, ys.min() - PAD_Y * SS, xs.max() + PAD_X * SS, ys.max() + PAD_Y * SS])
plate, edge = Image.new("L", txt.size, 0), Image.new("L", txt.size, 0)
ImageDraw.Draw(plate).rounded_rectangle(box.tolist(), radius=CORNER * SS, fill=255)
ImageDraw.Draw(edge).rounded_rectangle((box + np.array([-1, -1, 1, 1]) * EDGE * SS).tolist(),
                                       radius=(CORNER + EDGE) * SS, fill=255)

layers = [(down(edge), WHITE), (down(plate), PLATE), (down(txt), BLUE)]
out = orig.astype(np.float32)
for a, col in layers:
    out = out * (1 - a[..., None]) + np.array(col, np.float32) * a[..., None]
out = np.round(out).astype(np.uint8)
mask = layers[0][0] > 0
out[~mask] = orig[~mask]
Image.fromarray(out).save(OUT, optimize=True)
ys, xs = np.nonzero(layers[0][0] > 0)
json.dump({"text": " / ".join(s for s, _ in LINES), "plate_bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
           "pin_head": PIN_HEAD}, open(OUT + ".venue.json", "w"), ensure_ascii=False)
np.save(OUT + ".venue_mask.npy", mask)
print("saved", OUT)
