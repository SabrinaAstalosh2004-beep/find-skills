"""Checks for add_arch_marker.py: only the geotag, the arch sign and its caption were added to the approved map."""
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
check("approved map unchanged outside the new geotag, sign and caption", not (diff & ~mask).any(),
      f"changed {diff.sum()} px, mask {mask.sum()} px")
routes = np.any(a != o, -1)  # every route arrow and the street label of the approved version
check("geotag/sign/caption touch no route arrow or street label", not (mask & routes).any(), f"{(mask & routes).sum()} px")
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
box = (slice(by, by + bh + 1), slice(bx, bx + bw + 1))
check("blue check mark removed (its area = approved map, apart from the geotag)",
      not (np.any(r[box] != a[box], -1) & ~mask[box]).any())
yx, yy, yw, yh, _ = yellow
ya = r[yy:yy + yh, yx:yx + yw]
check("yellow arrow removed (no yellow left where it was)", not ((ya[..., 0] > 200) & (ya[..., 1] > 200) & (ya[..., 2] < 90)).any())
tip = np.array(meta["pin_tip"])
check("geotag replaces the blue check mark (tip at its vertex)", bx <= tip[0] <= bx + bw and by + bh - 3 <= tip[1] <= by + bh + 1,
      f"pin tip {tip.tolist()}, check mark x{bx}-{bx + bw} y{by}-{by + bh}")
check("geotag stands right above the two final route arrows (museum entrance)",
      not routes[int(tip[1]) + 1:int(tip[1]) + 22, int(tip[0]) - 4:int(tip[0]) + 5].any() and routes[850:856, 600:645].any())
sc, sr = np.array(meta["sign_centre"]), meta["sign_r"]
check("arch sign replaces the yellow arrow", yx <= sc[0] - sr and sc[0] + sr <= yx + yw and yy <= sc[1] - sr <= yy + yh,
      f"sign centre {sc.tolist()}, arrow box x{yx}-{yx + yw} y{yy}-{yy + yh}")
check("arch sign is just below the arch passage (y 1175-1182, x 258-337)", abs(sc[0] - 337) < 15 and 0 < sc[1] - sr - 1182 < 40)
cb = meta["caption_bbox"]
check("caption next to the arch sign", 0 <= cb[0] - (sc[0] + sr) < 10 and cb[1] <= sc[1] <= cb[3],
      f"caption box {cb}, sign centre {sc.tolist()}")
print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
