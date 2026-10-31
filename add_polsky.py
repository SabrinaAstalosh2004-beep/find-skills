"""Replace the cut-off map label "Польский с(ад)" with the full "Польский сад" at half the size.

The old letters (including the faint "ад" under the zoom button) are found as pixels darker than their
local background, restored column by column from the map pixels just above and below them, and the
full name is drawn in the same colour at half the original size plus 20 %, moved right and up by
20 % of its width from where the old label started.
Every other pixel stays identical.
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
MODE = os.environ.get("POLSKY_MODE", "both")  # both | remove (old label only) | text (new label only)
# the old label is measured on the 1x map that still has it
ana = orig if S == 1 and MODE != "text" else np.asarray(Image.open(os.environ["MAP1"]).convert("RGB"))

X0, Y0, X1, Y1 = 690, 1168, 938, 1216          # box of the old label (stops before the zoom button "−")
TEXT = "Польский сад"
WHITE = (255, 255, 255)

# ---------- remove the old label ----------
reg = ana[Y0:Y1, X0:X1].astype(np.float32)
lum = reg.mean(-1)
bg = cv2.medianBlur(np.ascontiguousarray(reg).astype(np.uint8), 21).astype(np.float32).mean(-1)
greenish = reg[..., 1] - (reg[..., 0] + reg[..., 2]) / 2 > 4
dark = (bg - lum > 5) | ((lum < 175) & greenish)            # letters, incl. the faint grey "ад" under the button
dark = cv2.morphologyEx(dark.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)) > 0
near = cv2.dilate(dark.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
halo = near & (lum - bg > 6)                                # white halo around the letters
ink = cv2.dilate((dark | halo).astype(np.uint8), np.ones((7, 3), np.uint8)) > 0   # 3 px extra above/below
old = np.zeros((H, W), bool)
old[Y0:Y1, X0:X1] = ink
core = ana[Y0:Y1, X0:X1][(lum < 150) & greenish]
COLOUR = tuple(int(v) for v in np.median(core, 0))        # colour of the original park label
# The park, pond, paths and building edges here run top-to-bottom while the label is a horizontal band,
# so every column is restored by interpolating between the pixels just above and below the letters.
cleaned = orig.astype(np.float32).copy()
for x in (range(X0, X1) if MODE != "text" else []):
    col = old[:, x]
    y = Y0
    while y < Y1:
        if not col[y]:
            y += 1
            continue
        y2 = y
        while y2 < Y1 and col[y2]:
            y2 += 1
        top, bot = cleaned[y - 1, x], cleaned[y2, x]
        t = (np.arange(y, y2) - (y - 1)) / (y2 - (y - 1))
        cleaned[y:y2, x] = top[None] * (1 - t[:, None]) + bot[None] * t[:, None]
        y = y2
# soften column-to-column steps inside the restored band only
if MODE != "text":
    soft = cv2.GaussianBlur(cleaned, (5, 1), 0)
    cleaned[old] = soft[old]
cleaned = np.round(cleaned).astype(np.uint8)

# old label metrics: left edge and vertical centre of the dark letters
ys, xs = np.nonzero((lum < 150) & greenish)
left, cy = X0 + xs.min(), Y0 + (ys.min() + ys.max()) / 2
old_cap = ys.max() - ys.min()

# ---------- new label, half size ----------
font = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-SemiBold.otf", 18 * SS)   # half size (15) + 20 %
SHIFT = 0.20 * font.getlength(TEXT) / SS     # moved right and up by 20 % of the label width
old_left = left
left, cy = left + SHIFT, cy - SHIFT
cap = font.getbbox("П")[3] - font.getbbox("П")[1]
asc, _ = font.getmetrics()
pos = (left * SS - font.getbbox("П")[0], cy * SS - cap / 2 - (asc - cap))
txt, halo = Image.new("L", (W * SS, H * SS), 0), Image.new("L", (W * SS, H * SS), 0)
ImageDraw.Draw(txt).text(pos, TEXT, font=font, fill=255)
ImageDraw.Draw(halo).text(pos, TEXT, font=font, fill=255, stroke_width=round(1.5 * SS), stroke_fill=255)
a_t = cv2.resize(np.asarray(txt), (W * S, H * S), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
a_h = cv2.resize(np.asarray(halo), (W * S, H * S), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
if MODE == "remove":
    a_t, a_h = np.zeros_like(a_t), np.zeros_like(a_h)

out = cleaned.astype(np.float32)
for a, col in ((a_h, WHITE), (a_t, COLOUR)):
    out = out * (1 - a[..., None]) + np.array(col, np.float32) * a[..., None]
out = np.round(out).astype(np.uint8)
mask = (old if MODE != "text" else np.zeros_like(a_h, bool)) | (a_h > 0)
out[~mask] = orig[~mask]
Image.fromarray(out).save(OUT, optimize=True)
ys, xs = np.nonzero(a_t > 0.3) if MODE != "remove" else (np.array([0]), np.array([0]))
json.dump({"text": TEXT, "colour": COLOUR, "shift_px": round(SHIFT, 1), "old_cap_px": int(old_cap), "new_cap_px": cap / SS,
           "new_bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())], "old_left": int(old_left)},
          open(OUT + ".polsky.json", "w"), ensure_ascii=False)
np.save(OUT + ".polsky_old.npy", old)
np.save(OUT + ".polsky_mask.npy", mask)
print("saved", OUT)
