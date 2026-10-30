"""Overlay walking/driving routes and a street label onto the original map screenshot.

The original image is loaded once and never transformed; all new graphics are drawn
on transparent layers (4x supersampled, then box-downsampled) and alpha-composited.
Coordinates are in pixels of the original image (954x2124). They were obtained by
registering the annotated screenshot onto the original (SIFT + RANSAC similarity,
RMS < 1 px) and snapping the hand-drawn strokes to the map geometry:
  arch through house 120 ............ y = 1179 (light passage strip y 1175-1182)
  courtyard driveway (vertical) ...... x = 346.5
  courtyard driveway (diagonal) ...... y = 952.3 - 0.385 (x - 460); route axis 3 px south of it
  driveway near museum (horizontal) .. y = 913
  museum facade below the check mark . y ~ 847-852 at x 610-626
"""
import json
import sys

import cv2
import numpy as np
from PIL import Image, ImageFont, ImageDraw

SRC, OUT = sys.argv[1], sys.argv[2]
SS = 4  # supersampling factor

base = Image.open(SRC).convert("RGB")
W, H = base.size
orig = np.asarray(base).copy()

RED = (227, 38, 43)
GREEN = (30, 158, 58)
TEXT = (36, 37, 40)
LINE_W = 8.8        # stroke width, px (x2)
HEAD_LEN = 20.0     # arrowhead length, px
DASH_BODY = 18.0    # dash stroke length, px (dash pattern scaled x2 with the stroke)
DASH_HEAD = 12.0    # length of the small pointer on every dash, px
DASH_HW = 12.0      # its base width
DASH_GAP = 12.0     # gap between dashes, px
HEAD_W = 18.0       # arrowhead base width, px
MID_W = 16.0        # base width of the intermediate arrowheads (narrower: must fit between the red line and the courtyard wall)
OFF = 10.4          # half-distance between parallel red/green centre lines: line gap 2*OFF-LINE_W = 12 px


# ---------- geometry helpers ----------
def line_pd(p, d):
    p, d = np.asarray(p, float), np.asarray(d, float)
    return p, d / np.linalg.norm(d)


def offset(line, dist):
    """Offset a directed line; dist < 0 => to the left of travel direction (image coords)."""
    p, d = line
    left = np.array([d[1], -d[0]])  # left normal for y-down coordinates
    return p - left * dist, d


def meet(l1, l2):
    (p1, d1), (p2, d2) = l1, l2
    A = np.array([d1, -d2]).T
    t = np.linalg.solve(A, p2 - p1)
    return p1 + d1 * t[0]


def fillet_path(pts, radii, step=0.25):
    """Polyline through pts with circular fillets of given radius at interior vertices."""
    pts = [np.asarray(p, float) for p in pts]
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        u = (b - a) / np.linalg.norm(b - a)
        v = (c - b) / np.linalg.norm(c - b)
        ang = np.arccos(np.clip(u @ v, -1, 1))
        r = radii[i - 1]
        if ang < 1e-6 or r <= 0:
            out.append(b)
            continue
        t = r * np.tan(ang / 2)
        p1, p2 = b - u * t, b + v * t
        cross = u[0] * v[1] - u[1] * v[0]
        n = np.array([-u[1], u[0]]) * np.sign(cross)
        ctr = p1 + n * r
        a0 = np.arctan2(*(p1 - ctr)[::-1])
        a1 = np.arctan2(*(p2 - ctr)[::-1])
        da = (a1 - a0 + np.pi) % (2 * np.pi) - np.pi
        k = max(2, int(abs(da) * r / step))
        out.append(p1)
        for s in np.linspace(0, 1, k)[1:-1]:
            ang_s = a0 + da * s
            out.append(ctr + r * np.array([np.cos(ang_s), np.sin(ang_s)]))
        out.append(p2)
    out.append(pts[-1])
    # densify straight parts
    dense = [out[0]]
    for q in out[1:]:
        p = dense[-1]
        n = max(1, int(np.linalg.norm(q - p) / step))
        for s in np.linspace(0, 1, n + 1)[1:]:
            dense.append(p + (q - p) * s)
    return np.array(dense)


# ---------- route geometry ----------
EAST, NORTH = (1, 0), (0, -1)
L_ARCH = line_pd((246, 1179), EAST)                 # through the arch
L_YARD = line_pd((355.5, 1179), NORTH)               # courtyard driveway, vertical (+9 px east: room for the 12 px gap)
L_DIAG = line_pd((460, 964.8), (1, -0.385))          # courtyard driveway, diagonal (+12.5 px south: clear of facade)
L_TOP = line_pd((600, 925), EAST)                    # driveway in front of the museum (+12 px: clear of the notch)
TIP_Y = 855                                          # arrow tips, just short of the facade


def curb_lane(y):  # middle of the northbound lane between the white dashed line and the blue dotted line
    return 226.0 - 0.0382 * (y - 1200)


def shared(side):
    """Vertices of the shared arch->courtyard section offset to one side (-1 red/left, +1 green/right)."""
    d = side * OFF
    a, y, g, t = (offset(L, d) for L in (L_ARCH, L_YARD, L_DIAG, L_TOP))
    return [meet(a, y), meet(y, g), meet(g, t)]


R_ARCH_TURN, R_DIAG, R_TOP = 14, 16, 20
red_v = [(curb_lane(1480), 1480), None] + shared(-1) + [(611, 925 - OFF), (611, TIP_Y)]
red_lane = line_pd((curb_lane(1480), 1480), (curb_lane(1176) - curb_lane(1480), 1176 - 1480))
red_v[1] = meet(red_lane, offset(L_ARCH, -OFF))
red = fillet_path(red_v, [12, R_ARCH_TURN - OFF, R_DIAG + OFF, R_TOP - OFF, 8])

walk_lane = line_pd((245.5, 1385), (4, -203))           # east sidewalk, kept clear of the facade (narrows to the south)
green_s_v = [(245.5, 1385), meet(walk_lane, offset(L_ARCH, OFF))] + shared(+1) + [(632, 925 + OFF), (632, TIP_Y)]
green_s = fillet_path(green_s_v, [8, R_ARCH_TURN + OFF, R_DIAG - OFF, R_TOP + OFF, 8])

green_n = fillet_path([(250, 985), (250, 1158)], [])   # stops short of the wider red line; 2 px off the facade

ROUTES = [("red_car", red, RED), ("green_walk_south", green_s, GREEN), ("green_walk_north", green_n, GREEN)]


# ---------- rasterise ----------
def head_at(path, s, width=MID_W):
    """Arrowhead polygon (same length as the final one) with its tip at arc length s, and its direction."""
    seg_len = np.r_[0, np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]
    i = min(np.searchsorted(seg_len, s), len(path) - 1)
    tip = path[i]
    d = tip - path[np.searchsorted(seg_len, s - 6)]
    d /= np.linalg.norm(d)
    nrm = np.array([-d[1], d[0]])
    base_c = tip - d * HEAD_LEN
    return np.array([tip, base_c + nrm * width / 2, base_c - nrm * width / 2]), d


def draw_arrow(path, mid_s=()):
    """Return (alpha, head polygon, end direction, dash pointers) for a dashed path ending in an arrowhead."""
    big = np.zeros((H * SS, W * SS), np.uint8)
    tip = path[-1]
    # tangent at the end
    k = len(path) - 1
    while np.linalg.norm(path[k] - tip) < 6 and k > 0:
        k -= 1
    d = (tip - path[k]) / np.linalg.norm(tip - path[k])
    nrm = np.array([-d[1], d[0]])
    base_c = tip - d * HEAD_LEN
    head = np.array([tip, base_c + nrm * HEAD_W / 2, base_c - nrm * HEAD_W / 2])
    # dashed stroke: every dash is a small pointer "—▸" towards the destination;
    # the pattern is anchored at the final arrowhead and repeated back to the start
    seg_len = np.r_[0, np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]
    period = DASH_BODY + DASH_HEAD + DASH_GAP
    dash_heads = []
    tip_s = seg_len[-1] - HEAD_LEN - DASH_GAP
    while tip_s - DASH_HEAD > 1:
        h0 = tip_s - DASH_HEAD                       # dash head base
        b0 = max(0.0, h0 - DASH_BODY + LINE_W / 2)   # body start (round cap adds LINE_W/2)
        body = path[(seg_len >= b0) & (seg_len <= h0)]
        if len(body) >= 2:
            pts = np.round(body * SS * 16).astype(np.int32)  # 4 fractional bits
            cv2.polylines(big, [pts.reshape(-1, 1, 2)], False, 255, int(round(LINE_W * SS)), cv2.LINE_8, shift=4)
        i = min(np.searchsorted(seg_len, tip_s), len(path) - 1)
        p_tip = path[i]
        dd = path[i] - path[np.searchsorted(seg_len, tip_s - 1.5)]   # local tangent at the tip
        dd /= np.linalg.norm(dd)
        p_base = p_tip - dd * DASH_HEAD
        nn = np.array([-dd[1], dd[0]])
        tri = np.array([p_tip, p_base + nn * DASH_HW / 2, p_base - nn * DASH_HW / 2])
        cv2.fillPoly(big, [np.round(tri * SS * 16).astype(np.int32).reshape(-1, 1, 2)], 255, cv2.LINE_8, shift=4)
        dash_heads.append({"s": float(tip_s), "tip": p_tip.round(2).tolist(), "dir": dd.round(4).tolist()})
        tip_s -= period
    mids = []
    for ms in mid_s:  # intermediate arrowheads along the route
        poly, md = head_at(path, ms)
        cv2.fillPoly(big, [np.round(poly * SS * 16).astype(np.int32).reshape(-1, 1, 2)], 255, cv2.LINE_8, shift=4)
        mids.append({"s": float(ms), "frac": float(ms / seg_len[-1]), "tip": poly[0].round(2).tolist(), "dir": md.round(4).tolist()})
    cv2.fillPoly(big, [np.round(head * SS * 16).astype(np.int32).reshape(-1, 1, 2)], 255, cv2.LINE_8, shift=4)
    a = cv2.resize(big, (W, H), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    return a, head, d, dash_heads[::-1], mids


layers = []
meta = {}
for name, path, col in ROUTES:
    a, head, d, dash_heads, _ = draw_arrow(path)
    layers.append((a, col))
    meta[name] = {"path": path.round(2).tolist(), "head": head.round(2).tolist(), "end_dir": d.round(4).tolist(),
                  "dash_heads": dash_heads}

# ---------- label ----------
LABEL = "ИЗМАЙЛОВСКИЙ ПРОСПЕКТ"
FONT = "/usr/share/fonts/opentype/inter/Inter-Medium.otf"
FS, TRACK = 27, 1.5  # cap height ~20 px as in "наб. РЕКИ ФОНТАНКИ"; tracking reduced to fit the mark
font = ImageFont.truetype(FONT, FS * SS)
advs = [font.getlength(ch) + TRACK * SS for ch in LABEL]
tw = int(sum(advs) - TRACK * SS) + 8 * SS
asc, desc = font.getmetrics()
th = asc + desc + 8 * SS
timg = Image.new("L", (tw, th), 0)
td = ImageDraw.Draw(timg)
x = 4 * SS
for ch, adv in zip(LABEL, advs):
    td.text((x, 4 * SS), ch, font=font, fill=255)
    x += adv
ink = np.asarray(timg)
cols = np.nonzero(ink.max(0))[0]
anchor = np.array([(cols[0] + cols[-1]) / 2, 4 * SS + asc], float)  # baseline midpoint (SS units)


def median_c(y):  # centre of the light dividing strip of Izmailovsky prospekt
    return 213.5 - 0.0861 * (y - 1040)


LABEL_Y = 1150.0                       # centre of the mark on image 2 (mapped), clear of the traffic light
BASE_OFF = -17.5                       # baseline so that the cap-height centre is on the 2nd southbound lane (x~175.5 at y 1150)
target = np.array([median_c(LABEL_Y) + BASE_OFF, LABEL_Y])
u = np.array([0.0861, -1.0]); u /= np.linalg.norm(u)   # reading direction: along the road, northwards
v = np.array([-u[1], u[0]])                             # glyph "down" (towards baseline) = east
Mx = np.array([[u[0], v[0], 0], [u[1], v[1], 0]], float)
Mx[:, 2] = target * SS - Mx[:, :2] @ anchor
big_t = cv2.warpAffine(ink, Mx, (W * SS, H * SS), flags=cv2.INTER_LINEAR)
ta = cv2.resize(big_t, (W, H), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
layers.insert(0, (ta, TEXT))
corners = np.array([[cols[0], 4 * SS], [cols[-1], 4 * SS], [cols[-1], th - 4 * SS], [cols[0], th - 4 * SS]], float)
meta["label"] = {"text": LABEL, "baseline_mid": target.tolist(),
                 "angle_deg_from_vertical": float(np.degrees(np.arctan2(u[0], -u[1]))),
                 "quad": ((Mx[:, :2] @ corners.T).T / SS + Mx[:, 2] / SS).round(1).tolist()}

# ---------- intermediate arrowheads: every 30-40 % of each route's length ----------
# Positions are searched inside the allowed window so that a head sits on a straight stretch and
# touches neither a building (nor the arch walls), nor the other colour, nor the label.
R_, G_, B_ = (orig[..., i].astype(int) for i in range(3))
bld = (R_ - B_ >= 7) & (R_ >= 215) & (R_ <= 240) & (G_ <= R_) & (np.abs(G_ - B_) < 12)
bld = cv2.morphologyEx(bld.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
# the arch is not exempt here: an intermediate head inside it would stick out of the narrow passage


def head_mask(poly):
    big = np.zeros((H * SS, W * SS), np.uint8)
    cv2.fillPoly(big, [np.round(poly * SS * 16).astype(np.int32).reshape(-1, 1, 2)], 255, cv2.LINE_8, shift=4)
    return cv2.resize(big, (W, H), interpolation=cv2.INTER_AREA) > 0


def pick_mids(path, blocked, lo=0.30, hi=0.40):
    total = np.sum(np.linalg.norm(np.diff(path, axis=0), axis=1))
    best = None
    fr = np.arange(lo, hi + 0.0001, 0.005)
    for f1 in fr:
        for g in fr:
            f2 = f1 + g
            if not lo <= 1 - f2 <= hi:
                continue
            score = abs(f1 - 1 / 3) + abs(g - 1 / 3) + abs(1 - f2 - 1 / 3)
            if best is not None and score >= best[0]:
                continue
            good = True
            for f in (f1, f2):
                poly, d = head_at(path, f * total)
                _, d0 = head_at(path, f * total - HEAD_LEN)
                if d @ d0 < np.cos(np.radians(3)) or (head_mask(poly) & blocked).any():
                    good = False
                    break
            if good:
                best = (score, [f1 * total, f2 * total])
    if best is None:
        # no free spot inside 30-40 %: widen the window step by step (red: courtyard wall at 60-70 %)
        assert hi - lo < 0.2, "no valid positions for intermediate arrowheads"
        return pick_mids(path, blocked, lo - 0.01, hi + 0.01)
    return best[1]


text_m = layers[0][0] > 0
alphas = {name: layers[i + 1][0] for i, (name, _, _) in enumerate(ROUTES)}
for i, (name, path, col) in enumerate(ROUTES):
    other = np.zeros((H, W), bool)
    for on, (_, _, oc) in zip(alphas, ROUTES):
        if oc != col:
            other |= alphas[on] > 0
    mid_s = pick_mids(path, bld | other | text_m)
    a, _, _, _, mids = draw_arrow(path, mid_s)
    alphas[name] = a
    layers[i + 1] = (a, col)
    meta[name]["mid_heads"] = mids

# ---------- composite ----------
out = orig.astype(np.float32)
for a, col in layers:
    out = out * (1 - a[..., None]) + np.array(col, np.float32) * a[..., None]
out = np.round(out).astype(np.uint8)
mask_any = np.zeros((H, W), bool)
for a, _ in layers:
    mask_any |= a > 0
out[~mask_any] = orig[~mask_any]  # guarantee: untouched pixels are bit-identical
Image.fromarray(out).save(OUT, optimize=True)

np.savez_compressed(OUT + ".layers.npz", text=layers[0][0], red=layers[1][0],
                    green_s=layers[2][0], green_n=layers[3][0])
json.dump(meta, open(OUT + ".meta.json", "w"), ensure_ascii=False)
print("saved", OUT, out.shape)
