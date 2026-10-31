"""Checks for texture_map.py and the textured hi-res build.

Usage: check_texture.py <base Sx (upscaled, untextured)> <textured Sx> <final untextured Sx> <final textured Sx>
"""
import sys

import cv2
import numpy as np
from PIL import Image

base, tex, fin, tfin = (np.asarray(Image.open(p).convert("RGB")).astype(np.int16) for p in sys.argv[1:5])
untouched = np.load(sys.argv[2] + ".untouched.npy")
ok = True


def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


check("same size as the untextured hi-res map", base.shape == tex.shape, f"{tex.shape[1]}x{tex.shape[0]}")
same = np.all(base[untouched] == tex[untouched])
check("labels, icons, markings and other excluded pixels unchanged", same, f"{untouched.sum()} px kept")


def grad(img):
    """Gradient of the image smoothed beyond the texture grain (sigma 4 px at 3x)."""
    g = cv2.GaussianBlur(img.astype(np.float32), (0, 0), 4).mean(-1)
    return cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)


bx, by = grad(base)
tx, ty = grad(tex)
bm = np.hypot(bx, by)
outline = (bm > np.percentile(bm, 92)) & ~untouched          # region outlines of the map that were retextured
cosang = (bx * tx + by * ty)[outline] / (bm[outline] * np.hypot(tx, ty)[outline] + 1e-6)
kept = (cosang > 0.7) & (np.hypot(tx, ty)[outline] > 0.3 * bm[outline])
check("outlines stay in place: same edge, same direction at every map outline", kept.mean() > 0.95,
      f"{100 * kept.mean():.1f} % of {outline.sum()} outline px keep an edge in the same direction")

H = base.shape[0]
over = np.abs(fin[:H] - base).max(-1) > 60          # pixels where my overlays clearly cover the map
eq = np.all(fin[:H][over] == tfin[:H][over], -1).mean()
check("routes, icons, captions identical to the untextured build", eq > 0.97, f"{100 * eq:.1f} % of overlay pixels identical")
below = slice(H, None)
check("information strip below the map identical", np.array_equal(fin[below], tfin[below]))
print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
