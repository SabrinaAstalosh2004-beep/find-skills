"""Overlay walking (green) and driving (red) routes plus a street label on the
original map screenshot. The map itself is never modified: everything is drawn
on a separate transparent RGBA layer and alpha-composited on top."""
import math
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

SRC = sys.argv[1]
OUT = sys.argv[2]

SS = 4                      # supersampling of the overlay layer only
LINE_W = 3                  # stroke width, px
HEAD_L, HEAD_HW = 11, 5     # arrowhead length / half-width, px
GAP = 7                     # spacing between parallel routes, px
GREEN = (22, 150, 60, 255)
RED = (220, 30, 30, 255)


def unit(v):
    n = math.hypot(*v)
    return (v[0] / n, v[1] / n)


def left_normal(d):
    # screen coords (y down): left of travel direction
    return (d[1], -d[0])


def offset_polyline(pts, dist):
    """Miter offset of a polyline; positive dist = left of travel."""
    out = []
    for i, p in enumerate(pts):
        if i == 0:
            n = left_normal(unit((pts[1][0] - p[0], pts[1][1] - p[1])))
            out.append((p[0] + n[0] * dist, p[1] + n[1] * dist))
        elif i == len(pts) - 1:
            n = left_normal(unit((p[0] - pts[i - 1][0], p[1] - pts[i - 1][1])))
            out.append((p[0] + n[0] * dist, p[1] + n[1] * dist))
        else:
            n1 = left_normal(unit((p[0] - pts[i - 1][0], p[1] - pts[i - 1][1])))
            n2 = left_normal(unit((pts[i + 1][0] - p[0], pts[i + 1][1] - p[1])))
            k = 1 + n1[0] * n2[0] + n1[1] * n2[1]
            m = ((n1[0] + n2[0]) / k, (n1[1] + n2[1]) / k)
            out.append((p[0] + m[0] * dist, p[1] + m[1] * dist))
    return out


def fillet(pts, radius, step=0.25):
    """Replace every interior corner by a tangent circular arc; return dense points."""
    dense = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        d1 = unit((b[0] - a[0], b[1] - a[1]))
        d2 = unit((c[0] - b[0], c[1] - b[1]))
        cos_t = max(-1.0, min(1.0, d1[0] * d2[0] + d1[1] * d2[1]))
        theta = math.acos(cos_t)            # turning angle
        if theta < 1e-3:
            dense.append(b)
            continue
        r = radius
        t = r * math.tan(theta / 2)
        lim = 0.45 * min(math.dist(a, b), math.dist(b, c))
        if t > lim:
            t = lim
            r = t / math.tan(theta / 2)
        p1 = (b[0] - d1[0] * t, b[1] - d1[1] * t)
        cross = d1[0] * d2[1] - d1[1] * d2[0]
        n = left_normal(d1) if cross < 0 else (-left_normal(d1)[0], -left_normal(d1)[1])
        center = (p1[0] + n[0] * r, p1[1] + n[1] * r)
        a0 = math.atan2(p1[1] - center[1], p1[0] - center[0])
        sweep = theta if cross > 0 else -theta
        steps = max(2, int(abs(sweep) * r / step))
        dense.append(p1)
        for s in range(1, steps + 1):
            ang = a0 + sweep * s / steps
            dense.append((center[0] + r * math.cos(ang), center[1] + r * math.sin(ang)))
    dense.append(pts[-1])
    return dense


def resample(pts, step=0.5):
    out = [pts[0]]
    acc = 0.0
    for a, b in zip(pts, pts[1:]):
        seg = math.dist(a, b)
        if seg == 0:
            continue
        pos = step - acc
        while pos <= seg:
            out.append((a[0] + (b[0] - a[0]) * pos / seg, a[1] + (b[1] - a[1]) * pos / seg))
            pos += step
        acc = seg - (pos - step)
    if math.dist(out[-1], pts[-1]) > 1e-6:
        out.append(pts[-1])
    return out


def trim_end(pts, length):
    total = 0.0
    for i in range(len(pts) - 1, 0, -1):
        total += math.dist(pts[i], pts[i - 1])
        if total >= length:
            return pts[:i]
    return pts[:2]


def tangent_at(pts, i):
    j0, j1 = max(0, i - 4), min(len(pts) - 1, i + 4)
    return unit((pts[j1][0] - pts[j0][0], pts[j1][1] - pts[j0][1]))


def head_polygon(tip, d):
    n = left_normal(d)
    base = (tip[0] - d[0] * HEAD_L, tip[1] - d[1] * HEAD_L)
    return [tip,
            (base[0] + n[0] * HEAD_HW, base[1] + n[1] * HEAD_HW),
            (base[0] - n[0] * HEAD_HW, base[1] - n[1] * HEAD_HW)]


def nearest_index(pts, q):
    return min(range(len(pts)), key=lambda i: (pts[i][0] - q[0]) ** 2 + (pts[i][1] - q[1]) ** 2)


def draw_route(draw, raw_pts, radius, color, mid_heads, end_trim=0.0):
    pts = resample(fillet(raw_pts, radius))
    if end_trim:
        pts = trim_end(pts, end_trim)
    tip = pts[-1]
    d_end = tangent_at(pts, len(pts) - 1)
    # stroke stops at the arrowhead base so the tip stays sharp
    stroke = trim_end(pts, HEAD_L - 1)
    sc = [(x * SS, y * SS) for x, y in stroke]
    draw.line(sc, fill=color, width=LINE_W * SS, joint="curve")
    r = LINE_W * SS / 2
    x0, y0 = sc[0]
    draw.ellipse([x0 - r, y0 - r, x0 + r, y0 + r], fill=color)
    heads = [head_polygon(tip, d_end)]
    for q in mid_heads:
        i = nearest_index(pts, q)
        heads.append(head_polygon(pts[i], tangent_at(pts, i)))
    for h in heads:
        draw.polygon([(x * SS, y * SS) for x, y in h], fill=color)
    return pts


# --- geometry (pixel coordinates of the original image) -------------------
# Shared part: arch in building 120 (y≈1180) -> inner driveway (x≈348)
# -> driveway along the courtyard's north side -> passage to the destination.
BUNDLE = [(256, 1180), (349, 1180), (349, 1002), (611, 915), (613, 880), (618, 862)]

ROUTES = {
    # walking from the north, east sidewalk next to the facades (x=250)
    "green_n": dict(pts=[(250, 955), (250, 1173)] + offset_polyline(BUNDLE, +GAP)[1:],
                    color=GREEN, radius=9, end_trim=13,
                    heads=[(250, 1060), (341, 1110), (440, 965)]),
    # walking from the south, same sidewalk
    "green_s": dict(pts=[(250, 1400), (250, 1187)] + offset_polyline(BUNDLE, -GAP)[1:],
                    color=GREEN, radius=9, end_trim=13,
                    heads=[(250, 1300), (355, 1070), (500, 955)]),
    # driving north in the right-hand lane of Izmailovsky pr., right turn into the arch
    "red": dict(pts=[(233, 1480), (233, 1180)] + BUNDLE[1:],
                color=RED, radius=11, end_trim=0,
                heads=[(233, 1400), (233, 1290), (348, 1090), (470, 950)]),
}

LABEL = "ИЗМАЙЛОВСКИЙ ПРОСПЕКТ"
LABEL_CENTER = (151.5, 1486)   # axis of the blue mark on the carriageway
LABEL_LEN = 222 
HALO = 5.5                     # label halo, px
HALO_RGB = (246, 246, 248)
TEXT_RGB = (64, 64, 68)             # target text length along the road, px


def make_label(width, height):
    font_path = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
    size = 10
    while ImageFont.truetype(font_path, size * SS).getlength(LABEL) / SS < LABEL_LEN:
        size += 0.5
    f = ImageFont.truetype(font_path, (size - 0.5) * SS)
    bbox = f.getbbox(LABEL)
    pad = 8 * SS
    tw, th = bbox[2] - bbox[0] + 2 * pad, bbox[3] - bbox[1] + 2 * pad
    glyphs = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(glyphs).text((pad - bbox[0], pad - bbox[1]), LABEL, font=f, fill=255)
    # halo: glyph mask dilated by HALO px, then closed so counters and
    # letter gaps are filled like a map-label halo
    k = int(2 * HALO * SS) + 1
    halo = glyphs.filter(ImageFilter.MaxFilter(k))
    halo = halo.filter(ImageFilter.MaxFilter(4 * SS + 1)).filter(ImageFilter.MinFilter(4 * SS + 1))
    txt = Image.new("RGBA", (tw, th), HALO_RGB + (0,))
    txt.putalpha(halo)
    ink = Image.new("RGBA", (tw, th), TEXT_RGB + (255,))
    ink.putalpha(glyphs)
    txt.alpha_composite(ink)
    txt = txt.rotate(90, expand=True)          # reads bottom-to-top, along the road
    layer = Image.new("RGBA", (width * SS, height * SS), (0, 0, 0, 0))
    cx, cy = LABEL_CENTER[0] * SS, LABEL_CENTER[1] * SS
    layer.alpha_composite(txt, (int(cx - txt.width / 2), int(cy - txt.height / 2)))
    return layer


def main():
    base = Image.open(SRC).convert("RGB")      # read only, never written back
    W, H = base.size
    big = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    big.alpha_composite(make_label(W, H))
    draw = ImageDraw.Draw(big)
    dense = {}
    for name, r in ROUTES.items():
        dense[name] = draw_route(draw, r["pts"], r["radius"], r["color"], r["heads"], r["end_trim"])
    overlay = big.resize((W, H), Image.LANCZOS)

    result = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    result.save(OUT, format="PNG", optimize=True)
    overlay.save(OUT.replace(".png", "_overlay.png"))

    # --- verification ---------------------------------------------------
    check = Image.open(OUT).convert("RGB")
    assert check.size == base.size, "resolution changed"
    mask = overlay.getchannel("A").point(lambda a: 255 if a > 0 else 0)
    diff = ImageChops.difference(base, check).convert("L").point(lambda v: 255 if v else 0)
    outside = ImageChops.multiply(diff, ImageChops.invert(mask))
    print("size:", check.size)
    print("changed px:", sum(1 for v in diff.get_flattened_data() if v),
          "| overlay mask px:", sum(1 for v in mask.get_flattened_data() if v),
          "| changed outside mask:", sum(1 for v in outside.get_flattened_data() if v))

    # overlay pixels sitting on building fill (excluding the arch itself)
    bpx = base.load()
    apx = overlay.getchannel("A").load()
    hits = []
    for y in range(850, 1500):
        for x in range(180, 700):
            if apx[x, y] > 60 and not (254 <= x <= 338 and 1168 <= y <= 1192):
                r, g, b = bpx[x, y]
                if abs(r - 230) <= 4 and abs(g - 222) <= 4 and abs(b - 219) <= 4:
                    hits.append((x, y))
    print("route px on building fill (outside arch):", len(hits), hits[:15])

    # min distance between different routes' centerlines (no merging/crossing)
    names = list(dense)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = dense[names[i]][::4], dense[names[j]][::4]
            m = min(math.dist(p, q) for p in a for q in b)
            print(f"min centerline distance {names[i]} / {names[j]}: {m:.1f}px")

    # blue annotation pixels still visible
    rpx = check.load()
    blue = sum(1 for y in range(1370, 1600) for x in range(120, 180)
               if rpx[x, y][2] > 180 and rpx[x, y][0] < 80)
    print("blue mark px still visible:", blue)


if __name__ == "__main__":
    main()
