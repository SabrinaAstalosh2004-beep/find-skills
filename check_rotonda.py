"""Checks for remove_rotonda.py: only the "Ротонда" icon and name area changed, and nothing of it is left."""
import json
import sys

import numpy as np
from PIL import Image

MAP, APPROVED, OUT = sys.argv[1:4]  # original map, approved PNG, result
o = np.asarray(Image.open(MAP).convert("RGB")).astype(int)
a = np.asarray(Image.open(APPROVED).convert("RGB")).astype(int)
r = np.asarray(Image.open(OUT).convert("RGB")).astype(int)
mask = np.load(OUT + ".rotonda_mask.npy")
meta = json.load(open(OUT + ".rotonda.json"))
ok = True


def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


diff = np.any(r != a, -1)
check("map unchanged outside the removed label", not (diff & ~mask).any(), f"changed {diff.sum()} px")
check("no route, sign or caption touched", not (mask & np.any(a != o, -1)).any())
x0, y0, x1, y1 = meta["box"]
reg = r[y0:y1, x0:x1]
R, G, B = reg[..., 0], reg[..., 1], reg[..., 2]
teal = (G - R > 30) & (B - R > 15) & (reg.mean(-1) < 190)
check("no teal icon or letters left", teal.sum() == 0, f"{teal.sum()} px")
print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
