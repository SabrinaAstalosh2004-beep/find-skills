"""Remove the map's "Ротонда" place label (teal star icon + name, cut off by the right edge).

The icon (teal disc with a white star), the letters and their white halo are found by colour, and the
area is restored from the surrounding map by inpainting (cv2.inpaint, Navier-Stokes). Every other pixel
stays identical.
"""
import json
import sys

import cv2
import numpy as np
from PIL import Image

SRC, OUT = sys.argv[1], sys.argv[2]
orig = np.asarray(Image.open(SRC).convert("RGB")).copy()
H, W = orig.shape[:2]
X0, Y0, X1, Y1 = 840, 1300, W, 1408          # box of the icon and the name

reg = orig[Y0:Y1, X0:X1].astype(int)
R, G, B = reg[..., 0], reg[..., 1], reg[..., 2]
lum = reg.mean(-1)
teal = (G - R > 30) & (B - R > 15) & (lum < 190)
filled = teal.astype(np.uint8) * 255
cv2.floodFill(filled, np.zeros((filled.shape[0] + 2, filled.shape[1] + 2), np.uint8), (0, 0), 255)
star = cv2.bitwise_not(filled) > 0                 # white star = hole inside the teal disc
core = teal | star
near = cv2.dilate(core.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
bg = cv2.medianBlur(np.ascontiguousarray(reg).astype(np.uint8), 31).mean(-1)
halo = near & (lum - bg > 4)
mask = np.zeros((H, W), bool)
mask[Y0:Y1, X0:X1] = cv2.dilate((core | halo).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0

out = cv2.inpaint(np.ascontiguousarray(orig), mask.astype(np.uint8) * 255, 6, cv2.INPAINT_NS)
out[~mask] = orig[~mask]
Image.fromarray(out).save(OUT, optimize=True)
json.dump({"removed": "Ротонда", "box": [X0, Y0, X1, Y1], "pixels": int(mask.sum())}, open(OUT + ".rotonda.json", "w"),
          ensure_ascii=False)
np.save(OUT + ".rotonda_mask.npy", mask)
print("saved", OUT)
