import json
import sys

import cv2
import numpy as np
from PIL import Image

SRC, OUT = sys.argv[1], sys.argv[2]
o = np.asarray(Image.open(SRC).convert("RGB")).astype(int)
r = np.asarray(Image.open(OUT).convert("RGB")).astype(int)
L = np.load(OUT + ".layers.npz")
meta = json.load(open(OUT + ".meta.json"))
ok = True


def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


# 1. size
check("size identical", o.shape == r.shape, f"{o.shape[1]}x{o.shape[0]} -> {r.shape[1]}x{r.shape[0]}")

# 2. pixels outside the drawn masks are unchanged
union = np.zeros(o.shape[:2], bool)
for k in L.files:
    union |= L[k] > 0
diff = np.any(o != r, axis=-1)
check("no changed pixel outside masks", not np.any(diff & ~union),
      f"changed={diff.sum()}, mask={union.sum()} px ({100 * union.mean():.2f}% of image), outside={np.sum(diff & ~union)}")

# 3. arch: the only passage through the building along the prospekt (light strip y 1175-1182)
ARCH_X, ARCH_Y = (262, 334), (1160, 1198)  # passage y 1175-1182 plus the width of both lines
for name in ("red_car", "green_walk_south"):
    p = np.array(meta[name]["path"])
    inside = p[(p[:, 0] >= ARCH_X[0]) & (p[:, 0] <= ARCH_X[1])]
    check(f"{name} passes through the arch", len(inside) and inside[:, 1].min() >= ARCH_Y[0] and inside[:, 1].max() <= ARCH_Y[1],
          f"y in arch span {inside[:, 1].min():.1f}-{inside[:, 1].max():.1f}")
pn = np.array(meta["green_walk_north"]["path"])
check("green_walk_north ends at the arch entrance (continues on green line)",
      np.hypot(*(pn[-1] - [252, 1179])) < 25 and abs(pn[-1][0] - 251) < 2, f"tip {pn[-1].round(1).tolist()}")

# 4. arrowheads point towards destination
DEST = np.array([626, 822])  # vertex of the check mark (mapped)
for name, goal in (("red_car", DEST), ("green_walk_south", DEST), ("green_walk_north", np.array([250, 1182]))):
    p = np.array(meta[name]["path"])
    d = np.array(meta[name]["end_dir"])
    tip = p[-1]
    seg = np.diff(p, axis=0)
    # remaining distance along the route decreases strictly (no back-tracking)
    check(f"{name}: head points to goal", (goal - tip) @ d > 0, f"tip {tip.round(1).tolist()}, dir {d.tolist()}")
    # every dash pointer is aligned with the direction of travel and they follow each other forwards
    dh = meta[name]["dash_heads"]
    cum = np.r_[0, np.cumsum(np.linalg.norm(seg, axis=1))]
    fwd = [float(np.array(h["dir"]) @ (seg[min(np.searchsorted(cum, h["s"]), len(seg)) - 1]
                                       / np.linalg.norm(seg[min(np.searchsorted(cum, h["s"]), len(seg)) - 1])))
           for h in dh]
    gaps = np.diff([h["s"] for h in dh])
    check(f"{name}: all {len(dh)} dash pointers face the direction of travel", min(fwd) > 0.95 and np.all(gaps > 0),
          f"min cos {min(fwd):.3f}, covered {dh[0]['s']:.0f}..{dh[-1]['s']:.0f} of {cum[-1]:.0f} px")
    # intermediate arrowheads: spacing 30-40 % of the route length, facing the direction of travel
    mh = meta[name].get("mid_heads", [])
    fr = [0.0] + [h["frac"] for h in mh] + [1.0]
    sp = np.diff(fr)
    cosm = [float(np.array(h["dir"]) @ (seg[min(np.searchsorted(cum, h["s"]), len(seg)) - 1]
                                        / np.linalg.norm(seg[min(np.searchsorted(cum, h["s"]), len(seg)) - 1])))
            for h in mh]
    check(f"{name}: {len(mh)} intermediate arrowheads every 30-40 % (+-3 %) facing forward",
          len(mh) == 2 and np.all((sp >= 0.269) & (sp <= 0.431)) and min(cosm) > 0.99,
          ("" if np.all((sp >= 0.299) & (sp <= 0.401)) else "WIDENED, ") + "spacing " + " / ".join(f"{100 * x:.1f}%" for x in sp) + f", min cos {min(cosm):.3f}")
for name in ("red_car", "green_walk_south"):
    tip = np.array(meta[name]["path"][-1])
    check(f"{name} ends at the museum facade under the check mark", abs(tip[0] - DEST[0]) <= 16 and 0 < tip[1] - DEST[1] < 40,
          f"tip {tip.round(1).tolist()}")

# building mask (beige building fill) of the ORIGINAL
R, G, B = o[..., 0], o[..., 1], o[..., 2]
bld = (R - B >= 7) & (R >= 215) & (R <= 240) & (G <= R) & (np.abs(G - B) < 12)
bld = cv2.morphologyEx(bld.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
arch = np.zeros_like(bld)
arch[ARCH_Y[0]:ARCH_Y[1] + 1, 255:340] = True
for k, name in (("red", "red"), ("green_s", "green south"), ("green_n", "green north")):
    hit = (L[k] > 0.05) & bld & ~arch
    ys, xs = np.nonzero(hit)
    check(f"{name}: no building crossing outside the arch", hit.sum() == 0,
          f"{hit.sum()} px" + (f" at x{xs.min()}-{xs.max()} y{ys.min()}-{ys.max()}" if hit.sum() else ""))

# red on the prospekt runs in the middle of its lane (white dashed line .. blue dotted line)
LANE_R = {1200: (214.5, 237.5), 1260: (210.5, 236), 1300: (207.5, 235.5), 1380: (202.5, 233), 1420: (201.5, 233), 1480: (199.5, 231)}
pr = np.array(meta["red_car"]["path"])
devr = [abs(np.interp(y, pr[::-1, 1], pr[::-1, 0]) - (a + b) / 2) for y, (a, b) in LANE_R.items()]
check("red in the middle of its lane on the prospekt", max(devr) < 1.5, "deviation " + ", ".join(f"{d:.1f}" for d in devr) + " px")

# 5. red and green never overlap; label overlaps nothing drawn
green = (L["green_s"] > 0) | (L["green_n"] > 0)
check("red/green overlap", np.sum((L["red"] > 0) & green) == 0, f"{np.sum((L['red'] > 0) & green)} px")
d_rg = cv2.distanceTransform((~(L["red"] > 0)).astype(np.uint8), cv2.DIST_L2, 5)
print(f"     min gap red->green: {d_rg[green].min():.2f} px")
routes = (L["red"] > 0) | green
check("label does not touch the arrows", np.sum((L["text"] > 0) & routes) == 0)

# 6. label position
q = np.array(meta["label"]["quad"])
ctr = q.mean(0)
MARK_ANG = 4.1  # angle of the mark on image 2 (mapped)
# 2nd southbound lane: between the two white dashed lines west of the dividing strip
LANE2 = {1000: (184, 198), 1100: (172, 186), 1150: (169, 182), 1200: (162, 176.5), 1300: (153, 167)}
def lab_c(y):  # midpoint of the letters' ink across the road at height y
    xs = np.nonzero((L["text"][y - 6:y + 7] > 0.3).any(0))[0]
    return (xs.min() + xs.max()) / 2
dev = [abs(lab_c(y) - (a + b) / 2) for y, (a, b) in LANE2.items()]
check("label centred on the 2nd lane", max(dev) < 3.5, "deviation " + ", ".join(f"{d:.1f}" for d in dev) + " px")
check("label still at the mark along the road", abs(ctr[1] - 1149) < 5, f"centre y {ctr[1]:.1f}")
check("label parallel to the road", abs(meta["label"]["angle_deg_from_vertical"] - MARK_ANG) < 2,
      f"{meta['label']['angle_deg_from_vertical']:.1f} deg vs mark {MARK_ANG} deg / dividing strip 4.9 deg")
t = L["text"] > 0
for nm, (x0, x1, y0, y1) in {"lane arrow": (218, 227, 1204, 1231), "traffic light": (226, 248, 892, 930)}.items():
    check(f"label clear of {nm}", not t[y0:y1 + 1, x0:x1 + 1].any())
ys, xs = np.nonzero(t)
check("label inside roadway (x 125..246)", xs.min() >= 125 and xs.max() <= 246, f"x {xs.min()}-{xs.max()}, y {ys.min()}-{ys.max()}")

print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
