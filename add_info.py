"""Add the metro walking-time caption and the two information blocks to the approved map.

  * "(10 минут пешком)" in small type next to the metro logo (overlay, everything else unchanged);
  * block "КАК ДОБРАТЬСЯ" over the lower part of the map, its top level with the end of the yellow metro
    arrow; block "ВХОД В ЗДАНИЕ" right below it on a strip appended below the screenshot.
Texts are taken verbatim from the request; codes are set in bold for readability.
"""
import json
import re
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SRC, OUT = sys.argv[1], sys.argv[2]
SS = 4

base = Image.open(SRC).convert("RGB")
W, H = base.size
orig = np.asarray(base).copy()

F = "/usr/share/fonts/opentype/inter/Inter-{}.otf"
DARK = (36, 37, 40)
WHITE = (255, 255, 255)
RED = (227, 38, 43)
GREEN = (30, 158, 58)
BLUE = (33, 110, 224)

# ---------- 1. metro caption ----------
METRO_TEXT = "(10 минут пешком)"
METRO_LINES = ["(10 минут", "пешком)"]  # 30 px does not fit in one line between the logo and the image edge
METRO_POS = (760.0, 1450.0 - 104.0)       # left edge, centre of the two lines: right of the logo ring, below "Ротонда"
mfont = ImageFont.truetype(F.format("SemiBold"), 30 * SS)   # 2x the first version (15 px)
mcap = mfont.getbbox("Н")[3] - mfont.getbbox("Н")[1]
masc, _ = mfont.getmetrics()
mline = round(mcap * 1.5)
txt = Image.new("L", (W * SS, H * SS), 0)
halo = Image.new("L", (W * SS, H * SS), 0)
for i, s_ in enumerate(METRO_LINES):
    pos = (METRO_POS[0] * SS, METRO_POS[1] * SS - (mcap + mline) / 2 + i * mline - (masc - mcap))
    ImageDraw.Draw(txt).text(pos, s_, font=mfont, fill=255)
    ImageDraw.Draw(halo).text(pos, s_, font=mfont, fill=255, stroke_width=3 * SS, stroke_fill=255)
a_t = cv2.resize(np.asarray(txt), (W, H), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
a_h = cv2.resize(np.asarray(halo), (W, H), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
mp = orig.astype(np.float32)
for a, col in ((a_h, WHITE), (a_t, DARK)):
    mp = mp * (1 - a[..., None]) + np.array(col, np.float32) * a[..., None]
mp = np.round(mp).astype(np.uint8)
caption_mask = a_h > 0
mp[~caption_mask] = orig[~caption_mask]
ys, xs = np.nonzero(a_t > 0.3)
caption_bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]

# ---------- 2. information blocks ----------
BLOCKS = [
    {"title": "КАК ДОБРАТЬСЯ", "accent": DARK, "parts": [
        ("head", "НА МАШИНЕ", RED),
        ("item", "1.", "С Измайловского проспекта следуйте по красным стрелкам на схеме через открытую арку во двор."),
        ("item", "2.", "Сразу после арки поверните налево и двигайтесь вдоль здания до конца по красной стрелке."),
        ("note", "! Во дворе и в конце маршрута, вас ждёт бесплатная парковка."),
        ("head", "ПЕШКОМ", GREEN),
        ("item", "1.", "С Измайловского проспекта следуйте по зелёным стрелкам на схеме через открытую арку во двор."),
        ("item", "2.", "Сразу после арки поверните налево и идите вдоль здания до конца по зелёной стрелке."),
    ]},
    {"title": "ВХОД В ЗДАНИЕ", "accent": BLUE, "parts": [
        ("item", "1.", "Подойдите к двери с козырьком, отмеченной геометкой на схеме."),
        ("item", "2.", "На домофоне наберите **#0115**."),
        ("item", "3.", "Поднимитесь по лестнице на 3-й этаж."),
        ("item", "4.", "Дверь слева."),
        ("item", "5.", "На домофоне двери наберите **0115**."),
        ("item", "6.", "Войдите внутрь — кабинет № 3."),
    ]},
]

BG = (242, 243, 245)
CARD_EDGE = (218, 221, 226)
NOTE_BG = (255, 236, 153)
MARGIN, PAD, RADIUS, GAP = 20, 26, 18, 18
fr = {k: ImageFont.truetype(F.format(k), s) for k, s in (("Regular", 24), ("SemiBold", 24), ("Bold", 24))}
f_title = ImageFont.truetype(F.format("Bold"), 30)
f_head = ImageFont.truetype(F.format("Bold"), 25)
LINE = 34
INNER = W - 2 * MARGIN - 2 * PAD
NUM_W = 34


def runs(text, bold_font="Bold", base_font="Regular"):
    """Split '**bold**' markup into (word, font) tokens, keeping trailing spaces."""
    out = []
    for i, seg in enumerate(re.split(r"\*\*", text)):
        for w in re.findall(r"\S+\s*", seg):
            out.append((w, fr[bold_font] if i % 2 else fr[base_font]))
    return out


def wrap(tokens, width):
    lines, cur, cw = [], [], 0.0
    for w, f in tokens:
        ww = f.getlength(w.rstrip())
        if cur and cw + ww > width:
            lines.append(cur)
            cur, cw = [], 0.0
        cur.append((w, f))
        cw += f.getlength(w)
    if cur:
        lines.append(cur)
    return lines


def layout(block):
    """List of draw ops and the block height."""
    ops, y = [], PAD
    ops.append(("text", PAD, y, block["title"], f_title, block["accent"]))
    y += 30 + 22
    for p in block["parts"]:
        if p[0] == "head":
            y += 6
            ops.append(("bar", PAD, y + 2, 6, 22, p[2]))
            ops.append(("text", PAD + 14, y, p[1], f_head, p[2]))
            y += 25 + 16
        elif p[0] == "item":
            ops.append(("text", PAD, y, p[1], fr["SemiBold"], DARK))
            for ln in wrap(runs(p[2]), INNER - NUM_W):
                x = PAD + NUM_W
                for w, f in ln:
                    ops.append(("text", x, y, w, f, DARK))
                    x += f.getlength(w)
                y += LINE
            y += 8
        elif p[0] == "note":
            lines = wrap(runs(p[1], base_font="SemiBold"), INNER - 28)
            h = len(lines) * LINE + 18
            ops.append(("round", PAD, y - 4, INNER, h, NOTE_BG))
            yy = y + 5
            for ln in lines:
                x = PAD + 14
                for w, f in ln:
                    ops.append(("text", x, yy, w, f, DARK))
                    x += f.getlength(w)
                yy += LINE
            y += h + 14
    return ops, y + PAD - 8


laid = [layout(b) for b in BLOCKS]
# "КАК ДОБРАТЬСЯ" lies on the map, its top at the level where the yellow metro arrow ends;
# "ВХОД В ЗДАНИЕ" follows right below it; the canvas is extended below the map as far as needed.
ARROW_END_Y = 1523                  # bottom of the car icon = tip of the yellow arrow (group raised 104 px)
tops = [ARROW_END_Y + 3]
for _, h in laid[:-1]:
    tops.append(tops[-1] + h + GAP)
total_h = max(H, tops[-1] + laid[-1][1] + MARGIN)
canvas = Image.new("RGB", (W, total_h), BG)
canvas.paste(Image.fromarray(mp), (0, 0))
d = ImageDraw.Draw(canvas)
cards = []
for (ops, h), b, y0 in zip(laid, BLOCKS, tops):
    box = [MARGIN, y0, W - MARGIN, y0 + h]
    d.rounded_rectangle(box, radius=RADIUS, fill=WHITE, outline=CARD_EDGE, width=2)
    d.rounded_rectangle([MARGIN, y0, MARGIN + 8, y0 + h], radius=4, fill=b["accent"])
    for op in ops:
        if op[0] == "text":
            _, x, y, s, f, col = op
            d.text((MARGIN + x, y0 + y), s, font=f, fill=col)
        elif op[0] == "bar":
            _, x, y, w, hh, col = op
            d.rounded_rectangle([MARGIN + x, y0 + y, MARGIN + x + w, y0 + y + hh], radius=3, fill=col)
        elif op[0] == "round":
            _, x, y, w, hh, col = op
            d.rounded_rectangle([MARGIN + x, y0 + y, MARGIN + x + w, y0 + y + hh], radius=10, fill=col)
    cards.append(box)

canvas.save(OUT, optimize=True)
json.dump({"metro_caption": METRO_TEXT, "caption_bbox": caption_bbox, "map_height": H, "cards": cards,
           "size": list(canvas.size)}, open(OUT + ".info.json", "w"), ensure_ascii=False)
np.save(OUT + ".info_mask.npy", caption_mask)
print("saved", OUT, canvas.size)
