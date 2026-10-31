"""Checks for add_start_icons.py: only the three start icons were added to the approved map."""
import json
import sys

import cv2
import numpy as np
from PIL import Image

MAP, APPROVED, OUT = sys.argv[1:4]  # original map, approved PNG, result
o = np.asarray(Image.open(MAP).convert("RGB")).astype(int)
a = np.asarray(Image.open(APPROVED).convert("RGB")).astype(int)
r = np.asarray(Image.open(OUT).convert("RGB")).astype(int)
mask = np.load(OUT + ".icons_mask.npy")
meta = json.load(open(OUT + ".icons.json"))
ok = True


def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


check("size unchanged", r.shape == a.shape, f"{r.shape[1]}x{r.shape[0]}")
diff = np.any(r != a, -1)
check("approved map unchanged outside the three icons", not (diff & ~mask).any(), f"changed {diff.sum()} px")
added = np.any(a != o, -1)
check("icons touch no route arrow, sign or label", not (mask & added).any(), f"{(mask & added).sum()} px")
gray_ink = (o.max(-1) < 175) & (np.abs(o[..., 0] - o[..., 2]) < 20)   # map text, lane arrows, icons
gray_ink = cv2.dilate(gray_ink.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
check("icons cover no map text, lane arrow or icon", not (mask & gray_ink).any(), f"{(mask & gray_ink).sum()} px")
for name, m in meta.items():
    c, p = np.array(m["centre"]), np.array(m["route_start"])
    check(f"{name}: icon right at the route start", 14 < np.hypot(*(c - p)) < 19, f"centre {c.tolist()}, start {p.tolist()}")
print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
