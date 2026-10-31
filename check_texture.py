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


def boundaries(img):
    """Region outlines: strong edges of the image smoothed beyond the texture grain."""
    g = cv2.GaussianBlur(img.astype(np.float32), (0, 0), 4).mean(-1)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    mag = np.hypot(gx, gy)
    return mag > np.percentile(mag, 92)


bb, tb = boundaries(base), boundaries(tex)
dist_to_tex = cv2.distanceTransform((~tb).astype(np.uint8), cv2.DIST_L2, 5)
d = dist_to_tex[bb]
check("outlines stay in place (map boundaries vs textured boundaries)", np.percentile(d, 90) <= 3.0,
      f"median {np.median(d):.1f} px, 90th percentile {np.percentile(d, 90):.1f} px at 3x")

H = base.shape[0]
over = np.abs(fin[:H] - base).max(-1) > 60          # pixels where my overlays clearly cover the map
eq = np.all(fin[:H][over] == tfin[:H][over], -1).mean()
check("routes, icons, captions identical to the untextured build", eq > 0.97, f"{100 * eq:.1f} % of overlay pixels identical")
below = slice(H, None)
check("information strip below the map identical", np.array_equal(fin[below], tfin[below]))
print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
