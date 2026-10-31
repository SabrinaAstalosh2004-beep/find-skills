"""Checks for add_polsky.py: only the old park label area changed; the new label is half the size."""
import json
import sys

import numpy as np
from PIL import Image

MAP, APPROVED, OUT = sys.argv[1:4]  # original map, approved PNG, result
o = np.asarray(Image.open(MAP).convert("RGB")).astype(int)
a = np.asarray(Image.open(APPROVED).convert("RGB")).astype(int)
r = np.asarray(Image.open(OUT).convert("RGB")).astype(int)
mask = np.load(OUT + ".polsky_mask.npy")
meta = json.load(open(OUT + ".polsky.json"))
ok = True


def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


diff = np.any(r != a, -1)
check("approved map unchanged outside the old/new park label", not (diff & ~mask).any(), f"changed {diff.sum()} px")
added = np.any(a != o, -1)
check("no route, sign or earlier caption touched", not (mask & added).any(), f"{(mask & added).sum()} px")
check("new label 'Польский сад' half the old size + 20 %", 0.5 < meta["new_cap_px"] / (meta["old_cap_px"] * 0.72) < 0.7,
      f"cap {meta['new_cap_px']} px vs old letters {meta['old_cap_px']} px (cap ~{meta['old_cap_px'] * 0.72:.0f})")
b = meta["new_bbox"]
check("new label moved right by 20 % of its width", abs(b[0] - meta["old_left"] - meta["shift_px"]) <= 2,
      f"x {b[0]} vs old {meta['old_left']} + {meta['shift_px']}")
reg = r[1168:1216, 690:938]
lum = reg.mean(-1)
green = reg[..., 1] - (reg[..., 0] + reg[..., 2]) / 2 > 4
dark_green = (lum < 150) & green
dark_green[:, b[0] - 690 - 2:b[2] - 690 + 3] = False
check("old large letters gone", dark_green.sum() == 0, f"{dark_green.sum()} px of dark label green left")
print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
