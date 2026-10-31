"""Checks for add_arch_marker.py: only the pin and caption were added to the approved map."""
import json
import sys

import cv2
import numpy as np
from PIL import Image

MAP, APPROVED, OUT, SHOT = sys.argv[1:5]  # original map, approved routes PNG, result, approval screenshot
o = np.asarray(Image.open(MAP).convert("RGB")).astype(int)
a = np.asarray(Image.open(APPROVED).convert("RGB")).astype(int)
r = np.asarray(Image.open(OUT).convert("RGB")).astype(int)
s = np.asarray(Image.open(SHOT).convert("RGB")).astype(int)
mask = np.load(OUT + ".marker_mask.npy")
meta = json.load(open(OUT + ".marker.json"))
ok = True


def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


check("size unchanged", r.shape == a.shape, f"{r.shape[1]}x{r.shape[0]}")
diff = np.any(r != a, -1)
check("approved map unchanged outside the pin and caption", not (diff & ~mask).any(),
      f"changed {diff.sum()} px, mask {mask.sum()} px")
routes = np.any(a != o, -1)  # every route arrow and the street label of the approved version
check("pin/caption touch no route arrow or street label", not (mask & routes).any(), f"{(mask & routes).sum()} px")
sub = o[1200:1260, 255:345]
ink = np.zeros(o.shape[:2], bool)
ink[1200:1260, 255:345] = (sub.mean(-1) < 170) & (np.abs(sub[..., 0] - sub[..., 2]) < 20)
ink = cv2.dilate(ink.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
check('house number "120" left visible', not (mask & ink).any())

# the screenshot's hand-drawn marks are gone; everything else matches the approved version
marks = np.abs(s - a).max(-1) > 70
n, lab, st, _ = cv2.connectedComponentsWithStats(marks.astype(np.uint8))
big = [st[i] for i in range(1, n) if st[i][4] > 15]
check("screenshot = approved map + 2 hand marks", len(big) == 2,
      "; ".join(f"x{x}-{x + w} y{y}-{y + h}" for x, y, w, h, _ in big))
blue, yellow = sorted(big, key=lambda b: b[1])
bx, by, bw, bh, _ = blue
check("blue check mark removed", np.abs(r[by:by + bh, bx:bx + bw] - a[by:by + bh, bx:bx + bw]).max() == 0)
yx, yy, yw, yh, _ = yellow
ya = r[yy:yy + yh, yx:yx + yw]
check("yellow arrow removed (no yellow left where it was)", not ((ya[..., 0] > 200) & (ya[..., 1] > 200) & (ya[..., 2] < 90)).any())
tip, ax = np.array(meta["pin_tip"]), np.array(meta["pin_axis"])
check("pin placed where the yellow arrow was", yx - 15 <= tip[0] <= yx + yw and yy - 5 <= tip[1] <= yy + 20,
      f"pin tip {tip.tolist()}, arrow box x{yx}-{yx + yw} y{yy}-{yy + yh}")
t = (tip[1] - 1178.5) / -ax[1]
hit = tip + ax * t
check("pin points into the open arch (passage y 1175-1182, x 258-337)", 258 <= hit[0] <= 337 and 0 < t < 40,
      f"axis meets passage at x={hit[0]:.1f} after {t:.0f} px")
cb = meta["caption_bbox"]
check("caption next to the pin", cb[0] - meta["pin_centre"][0] < 25 and cb[1] <= meta["pin_centre"][1] <= cb[3],
      f"caption box {cb}, pin centre {meta['pin_centre']}")
print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
