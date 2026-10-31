"""Checks for add_metro.py: only the metro logo and its arrow were added to the approved map."""
import json
import sys

import cv2
import numpy as np
from PIL import Image

MAP, APPROVED, OUT, SHOT = sys.argv[1:5]  # original map, approved PNG, result, approval screenshot
o = np.asarray(Image.open(MAP).convert("RGB")).astype(int)
a = np.asarray(Image.open(APPROVED).convert("RGB")).astype(int)
r = np.asarray(Image.open(OUT).convert("RGB")).astype(int)
s = np.asarray(Image.open(SHOT).convert("RGB")).astype(int)
mask = np.load(OUT + ".metro_mask.npy")
meta = json.load(open(OUT + ".metro.json"))
ok = True


def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


check("size unchanged", r.shape == a.shape, f"{r.shape[1]}x{r.shape[0]}")
diff = np.any(r != a, -1)
check("approved map unchanged outside the metro sign and arrow", not (diff & ~mask).any(), f"changed {diff.sum()} px")
added = np.any(a != o, -1)
check("no route, sign or earlier label covered", not (mask & added).any(), f"{(mask & added).sum()} px")
dark = (o.max(-1) < 140)  # map text and icons (dark ink)
check("no map text or icon covered", not (mask & cv2.dilate(dark.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)).any())

# hand marks are yellow; later approved changes (e.g. resized signs) also differ from an older screenshot
marks = (np.abs(s - a).max(-1) > 70) & (s[..., 0] > 190) & (s[..., 1] > 180) & (s[..., 2] < 110)
marks = cv2.morphologyEx(marks.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0
n, lab, st, cen = cv2.connectedComponentsWithStats(marks.astype(np.uint8))
big = sorted([(st[i], cen[i], i) for i in range(1, n) if st[i][4] > 10], key=lambda b: b[0][1])
check("screenshot = approved map + 2 yellow marks", len(big) == 2)
(cb, cc, _), (ab, ac, ai) = big
x, y, w, h, _ = cb
ring_c = np.array([x + w / 2, y + h / 2])
sc = np.array(meta["sign_centre"])
check("metro logo ring centred on the yellow 'M' circle", np.hypot(*(sc - ring_c)) < 15,
      f"sign {sc.tolist()}, circle box centre {ring_c.round(1).tolist()}")
ys, xs = np.nonzero(lab == ai)
pts = np.c_[xs, ys]
start = np.array(meta["arrow_from"])
tip_drawn = pts[np.argmax(((pts - start) ** 2).sum(1))]
tip = np.array(meta["arrow_to"])
d1 = (tip - start) / np.linalg.norm(tip - start)
d2 = (tip_drawn - start) / np.linalg.norm(tip_drawn - start)
check("arrow follows the drawn arrow", np.hypot(*(tip - tip_drawn)) < 10 and d1 @ d2 > 0.995,
      f"tip {tip.tolist()} vs drawn {tip_drawn.tolist()}, angle diff {np.degrees(np.arccos(min(1, d1 @ d2))):.1f} deg")
lb = meta["logo_bbox"]
check("logo 3x the previous sign (ring outer diameter 135 px vs 45 px)", abs((lb[2] - lb[0]) - 135) <= 2,
      f"logo box {lb}, width {lb[2] - lb[0]} px")
for b in (cb, ab):  # the new arrow is yellow itself: look for hand-drawn yellow outside the drawn elements
    x, y, w, h, _ = b
    yl = r[y:y + h, x:x + w]
    hand = (yl[..., 0] > 200) & (yl[..., 1] > 200) & (yl[..., 2] < 90) & ~mask[y:y + h, x:x + w]
    check("hand-drawn yellow mark gone", not hand.any())
print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
