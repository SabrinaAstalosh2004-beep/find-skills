"""Checks for add_place_labels.py: only the two place names were added to the approved map."""
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
mask = np.load(OUT + ".labels_mask.npy")
meta = json.load(open(OUT + ".labels.json"))
ok = True


def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


check("size unchanged", r.shape == a.shape, f"{r.shape[1]}x{r.shape[0]}")
diff = np.any(r != a, -1)
check("approved map unchanged outside the two new labels", not (diff & ~mask).any(), f"changed {diff.sum()} px")
added = np.any(a != o, -1)  # routes, street label, geotag, arch sign and caption of the approved version
check("new labels touch no route, geotag, arch sign or earlier label", not (mask & added).any(), f"{(mask & added).sum()} px")
ring = np.zeros_like(mask)
ring[998:1023, 519:544] = o[998:1023, 519:544].mean(-1) > 243  # white circle on the lawn
check("white circle on the lawn left visible", not (mask & ring).any())

# hand marks are yellow; later approved changes (e.g. resized signs) also differ from an older screenshot
marks = (np.abs(s - a).max(-1) > 70) & (s[..., 0] > 190) & (s[..., 1] > 180) & (s[..., 2] < 110)
marks = cv2.morphologyEx(marks.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0
n, lab, st, cen = cv2.connectedComponentsWithStats(marks.astype(np.uint8))
big = sorted([(st[i], cen[i]) for i in range(1, n) if st[i][4] > 10], key=lambda b: b[0][1])
check("screenshot = approved map + 2 yellow marks", len(big) == 2,
      "; ".join(f"centre {c.round(0).tolist()}" for _, c in big))
for (box, c), key in zip(big, ("garnovsky", "sports")):
    x, y, w, h, _ = box
    m = meta[key]
    b = m["ink_bbox"]
    centre = np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2])
    want = c + ([0.15 * 140, 0] if key == "sports" else [0, 0])  # sports label: moved right by 15 % of the field
    check(f"'{m['text']}' at its yellow mark" + (" + 15 % of the field to the right" if key == "sports" else ""),
          np.hypot(*(centre - want)) < 4, f"label centre {centre.round(1).tolist()}, target {want.round(1).tolist()}")
    yl = r[y:y + h, x:x + w]
    check(f"yellow mark under '{m['text']}' gone", not ((yl[..., 0] > 200) & (yl[..., 1] > 200) & (yl[..., 2] < 90)).any())

b = meta["sports"]["ink_bbox"]
check("'Спортивная площадка' inside the field box", 505 <= b[0] and b[2] <= 645 and 1197 <= b[1] and b[3] <= 1290)
others = {"Гарновский сквер": meta["garnovsky"]["cap_px"], "Открытая арка": 14, "ИЗМАЙЛОВСКИЙ ПРОСПЕКТ": 20, "120": 21}
check("'Спортивная площадка' is the smallest label", all(meta["sports"]["cap_px"] < v for v in others.values()),
      f"cap {meta['sports']['cap_px']} px vs " + ", ".join(f"{k} {v}" for k, v in others.items()))
print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
