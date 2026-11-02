"""Генерирует векторные иллюстрации книги (SVG) и их PNG-версии.

Все иллюстрации — оригинальные, нарисованы кодом в стиле «Шёлковая картография»
(см. design/philosophy.md). Запуск: python3 tools/plates.py
"""
import math
import random
from pathlib import Path

import fitz  # PyMuPDF — для растеризации SVG в PNG (EPUB/DOCX)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "art"

MILK = "#F5EFE4"
INK = "#1A1517"
BORDEAUX = "#6B1E2A"
GOLD = "#B3925E"
ASH = "#8C8078"   # тёплый серый для самых тонких линий

W = H = 1000


def svg(body, w=W, h=H, bg=None):
    rect = f'<rect width="{w}" height="{h}" fill="{bg}"/>' if bg else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'width="{w}" height="{h}">{rect}{body}</svg>')


def circle(x, y, r, fill="none", stroke="none", sw=1.0, op=1.0, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}" opacity="{op}"{d}/>')


def line(x1, y1, x2, y2, stroke=INK, sw=1.0, op=1.0, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="{stroke}" stroke-width="{sw}" opacity="{op}" stroke-linecap="round"{d}/>')


def path(d, stroke=INK, sw=1.0, op=1.0, fill="none", dash=None):
    ds = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" '
            f'opacity="{op}" stroke-linecap="round" stroke-linejoin="round"{ds}/>')


def ticks_frame(margin=60, n=40, length=8):
    """Тонкая рамка с засечками, как на полях старой карты."""
    out = [f'<rect x="{margin}" y="{margin}" width="{W-2*margin}" height="{H-2*margin}" '
           f'fill="none" stroke="{ASH}" stroke-width="0.8"/>']
    span = W - 2 * margin
    for i in range(n + 1):
        t = margin + span * i / n
        ln = length * (2 if i % 5 == 0 else 1)
        out.append(line(t, margin, t, margin - ln, ASH, 0.7))
        out.append(line(t, H - margin, t, H - margin + ln, ASH, 0.7))
        out.append(line(margin, t, margin - ln, t, ASH, 0.7))
        out.append(line(W - margin, t, W - margin + ln, t, ASH, 0.7))
    return "".join(out)


# ---------------------------------------------------------------- пролог
def plate_prologue():
    """Складки: лист бумаги помнит каждый сгиб."""
    rnd = random.Random(7)
    out = [ticks_frame()]
    # мелкая сетка
    for i in range(1, 30):
        t = 60 + 880 * i / 30
        out.append(line(t, 60, t, 940, ASH, 0.35, 0.55))
        out.append(line(60, t, 940, t, ASH, 0.35, 0.55))
    # линии сгибов
    folds = [((60, 330), (940, 290)), ((60, 640), (940, 700)), ((420, 60), (470, 940)),
             ((60, 60), (940, 940))]
    for (a, b) in folds:
        out.append(line(*a, *b, INK, 1.1, 0.85))
        out.append(line(a[0], a[1] + 4, b[0], b[1] + 4, INK, 0.4, 0.35))
    # микроразрывы волокон вдоль диагонали
    for k in range(120):
        t = rnd.random()
        x, y = 60 + 880 * t, 60 + 880 * t
        a = rnd.uniform(0, math.pi)
        l = rnd.uniform(3, 9)
        out.append(line(x, y, x + l * math.cos(a), y + l * math.sin(a), INK, 0.5, 0.6))
    # одна точка, ради которой всё
    out.append(circle(448, 314, 22, stroke=GOLD, sw=1.2))
    out.append(circle(448, 314, 6, fill=BORDEAUX))
    return svg("".join(out))


# ---------------------------------------------------------------- глава I
def plate_before():
    """Поле из многих точек и одна, которая ещё не знает о другой."""
    rnd = random.Random(11)
    out = [ticks_frame()]
    pts = []
    tries = 0
    while len(pts) < 720 and tries < 60000:
        tries += 1
        x, y = rnd.uniform(110, 890), rnd.uniform(110, 890)
        if all((x - a) ** 2 + (y - b) ** 2 > 24 ** 2 for a, b in pts):
            pts.append((x, y))
    gx, gy = 640, 380
    for x, y in pts:
        if (x - gx) ** 2 + (y - gy) ** 2 < 70 ** 2:
            continue
        out.append(circle(x, y, 2.1, fill=INK, op=0.82))
    out.append(circle(gx, gy, 42, stroke=ASH, sw=0.6, dash="2 5"))
    out.append(circle(gx, gy, 5.5, fill=GOLD))
    return svg("".join(out))


# ---------------------------------------------------------------- глава II
def plate_meeting():
    """Две дуги большого круга пересекаются в одной точке."""
    out = [ticks_frame()]
    cx, cy = 500, 500
    # параллели
    for r in range(60, 440, 38):
        out.append(circle(cx, cy, r, stroke=ASH, sw=0.45, op=0.7))
    # меридианы
    for k in range(24):
        a = math.pi * k / 12
        out.append(line(cx, cy, cx + 420 * math.cos(a), cy + 420 * math.sin(a), ASH, 0.35, 0.6))

    def arc(sign, color):
        pts = []
        for i in range(201):
            t = -1 + 2 * i / 200
            x = cx + 410 * t
            y = cy + sign * 260 * (t * t - 0.18) * (1 if sign > 0 else 1)
            pts.append((x, y))
        d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts)
        o = [path(d, color, 1.4)]
        for i in range(0, 201, 10):
            x, y = pts[i]
            o.append(line(x, y - 7, x, y + 7, color, 0.9))
        return "".join(o), pts

    a1, p1 = arc(1, INK)
    a2, p2 = arc(-1, BORDEAUX)
    out += [a1, a2]
    # точки пересечения (t^2 = 0.18)
    t = math.sqrt(0.18)
    for s in (-1, 1):
        x = cx + 410 * t * s
        if s > 0:
            out.append(circle(x, cy, 26, stroke=GOLD, sw=1.3))
            out.append(circle(x, cy, 6, fill=GOLD))
        else:
            out.append(circle(x, cy, 4, fill="none", stroke=INK, sw=0.8))
    return svg("".join(out))


# ---------------------------------------------------------------- глава III
def plate_between():
    """Интерференция: два источника волн и узор, который рождается между ними."""
    out = [ticks_frame()]
    a, b = (390, 500), (610, 500)
    for r in range(8, 300, 9):
        out.append(circle(*a, r, stroke=INK, sw=0.7, op=0.8))
    for r in range(8, 300, 9):
        out.append(circle(*b, r, stroke=BORDEAUX, sw=0.7, op=0.65))
    out.append(circle(500, 500, 7, fill=GOLD))
    return svg("".join(out))


# ---------------------------------------------------------------- глава IV
def plate_memory():
    """365 дней первого года. Закрашены те, что остались в сердце."""
    rnd = random.Random(3)
    out = [ticks_frame()]
    cols, rows = 21, 18
    size, gap = 28, 10
    w = cols * size + (cols - 1) * gap
    x0 = (W - w) / 2
    h = rows * size + (rows - 1) * gap
    y0 = (H - h) / 2
    n = 0
    special = {0, 41, 92, 150, 199, 233, 287, 318, 364}
    for r in range(rows):
        for c in range(cols):
            if n >= 365:
                break
            x, y = x0 + c * (size + gap), y0 + r * (size + gap)
            if n in special:
                out.append(f'<rect x="{x}" y="{y}" width="{size}" height="{size}" fill="{GOLD}"/>')
            elif rnd.random() < 0.16:
                out.append(f'<rect x="{x}" y="{y}" width="{size}" height="{size}" fill="{BORDEAUX}"/>')
            else:
                out.append(f'<rect x="{x+0.5}" y="{y+0.5}" width="{size-1}" height="{size-1}" '
                           f'fill="none" stroke="{INK}" stroke-width="0.8" opacity="0.7"/>')
            n += 1
    return svg("".join(out))


# ---------------------------------------------------------------- глава V
def plate_distance():
    """Две точки на расстоянии и изолинии вокруг каждой."""
    rnd = random.Random(5)
    out = [ticks_frame()]
    A, B = (230, 720), (770, 260)

    def contour(cx, cy, base, n, color, seed):
        r2 = random.Random(seed)
        ph = [r2.uniform(0, 6.28) for _ in range(4)]
        o = []
        for k in range(n):
            R = base + k * 15
            pts = []
            for i in range(181):
                a = 2 * math.pi * i / 180
                rr = R * (1 + 0.07 * math.sin(3 * a + ph[0]) + 0.05 * math.sin(5 * a + ph[1])
                          + 0.03 * math.sin(7 * a + ph[2]) * (k / n))
                pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
            d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + "Z"
            o.append(path(d, color, 0.7, 0.75))
        return "".join(o)

    out.append(contour(*A, 18, 9, INK, 1))
    out.append(contour(*B, 18, 9, BORDEAUX, 2))
    # геодезическая дуга
    mx, my = 380, 330
    out.append(path(f"M{A[0]} {A[1]} Q {mx} {my} {B[0]} {B[1]}", INK, 1.0, dash="6 9"))
    out.append(circle(*A, 5, fill=INK))
    out.append(circle(*B, 5, fill=BORDEAUX))
    # масштабная линейка
    y = 880
    for i in range(11):
        x = 300 + 40 * i
        out.append(line(x, y, x, y - (14 if i % 5 == 0 else 7), INK, 0.9))
        if i < 10 and i % 2 == 0:
            out.append(f'<rect x="{x}" y="{y-3}" width="40" height="3" fill="{INK}"/>')
    out.append(line(300, y, 700, y, INK, 0.9))
    out.append(circle(500, 490, 4, fill=GOLD))
    return svg("".join(out))


# ---------------------------------------------------------------- глава VI
def plate_letters():
    """Строки писем и 160 знаков одного спутникового сообщения."""
    rnd = random.Random(9)
    out = [ticks_frame()]
    # лист письма
    x0, y0 = 170, 170
    for r in range(17):
        y = y0 + r * 30
        ln = rnd.uniform(340, 560) if r % 6 != 5 else rnd.uniform(120, 260)
        # «почерк» — ломаная линия с небольшими отклонениями
        pts = []
        x = x0 + (40 if r % 6 == 0 else 0)
        while x < x0 + ln:
            pts.append((x, y + rnd.uniform(-2.2, 2.2)))
            x += rnd.uniform(5, 11)
        d = "M" + " L".join(f"{a:.1f} {b:.1f}" for a, b in pts)
        out.append(path(d, INK, 0.9, 0.8))
    # конверт
    ex, ey, ew, eh = 560, 640, 270, 170
    out.append(f'<rect x="{ex}" y="{ey}" width="{ew}" height="{eh}" fill="{MILK}" stroke="{BORDEAUX}" stroke-width="1.1"/>')
    out.append(path(f"M{ex} {ey} L{ex+ew/2} {ey+eh*0.58} L{ex+ew} {ey}", BORDEAUX, 1.1))
    out.append(circle(ex + ew / 2, ey + eh * 0.58, 13, fill=BORDEAUX))
    # 160 отметок
    for i in range(160):
        x = 170 + i * 4.2
        h = 10 if i % 10 == 0 else 5
        out.append(line(x, 880, x, 880 - h, GOLD if i == 159 else ASH, 0.9))
    return svg("".join(out))


# ---------------------------------------------------------------- глава VII
def plate_time():
    """Спираль дней. Каждый виток — год."""
    out = [ticks_frame()]
    cx, cy = 500, 500
    n = 365 * 4
    for i in range(n):
        t = i / 365
        a = 2 * math.pi * t
        r = 40 + 95 * t
        x, y = cx + r * math.cos(a - math.pi / 2), cy + r * math.sin(a - math.pi / 2)
        if i % 365 == 0:
            out.append(circle(x, y, 6, fill=GOLD))
        elif i % 30 == 0:
            out.append(circle(x, y, 2.4, fill=BORDEAUX))
        else:
            out.append(circle(x, y, 1.1, fill=INK, op=0.75))
    out.append(circle(cx, cy, 3, fill=INK))
    return svg("".join(out))


# ---------------------------------------------------------------- глава VIII
def plate_heart():
    """Два ритма, которые постепенно совпадают."""
    out = [ticks_frame()]
    for k in range(9):
        y = 180 + k * 80
        out.append(line(100, y, 900, y, ASH, 0.35, 0.6))

    def wave(phase_fn, ybase, color, sw):
        pts = []
        for i in range(801):
            x = 100 + i
            t = i / 800
            ph = phase_fn(t)
            beat = (x / 800 * 6 + ph) % 1
            y = 0
            if 0.40 < beat < 0.44:
                y = -110 * math.sin((beat - 0.40) / 0.04 * math.pi)
            elif 0.44 < beat < 0.47:
                y = 40 * math.sin((beat - 0.44) / 0.03 * math.pi)
            elif 0.6 < beat < 0.72:
                y = -18 * math.sin((beat - 0.6) / 0.12 * math.pi)
            pts.append((x, ybase + y))
        d = "M" + " L".join(f"{a:.1f} {b:.1f}" for a, b in pts)
        return path(d, color, sw)

    out.append(wave(lambda t: 0.0, 500, INK, 1.2))
    out.append(wave(lambda t: 0.33 * (1 - t) ** 2, 500, BORDEAUX, 1.2))
    out.append(circle(100 + 800 * (5.4 / 6), 500 - 110, 7, fill=GOLD))
    return svg("".join(out))


# ---------------------------------------------------------------- эпилог
def plate_open():
    """Незамкнутый круг: продолжение не дорисовано."""
    out = [ticks_frame()]
    cx, cy, R = 500, 500, 300
    for r in range(R - 120, R + 1, 20):
        out.append(circle(cx, cy, r, stroke=ASH, sw=0.4, op=0.6))
    a0, a1 = math.radians(-80), math.radians(250)
    x0, y0 = cx + R * math.cos(a0), cy + R * math.sin(a0)
    x1, y1 = cx + R * math.cos(a1), cy + R * math.sin(a1)
    out.append(path(f"M{x0:.1f} {y0:.1f} A {R} {R} 0 1 1 {x1:.1f} {y1:.1f}", GOLD, 2.2))
    # пунктир продолжения
    for k in range(1, 9):
        a = a1 + math.radians(2.6 * k)
        out.append(circle(cx + R * math.cos(a), cy + R * math.sin(a), 2.4 - k * 0.2, fill=GOLD))
    out.append(circle(x0, y0, 5, fill=BORDEAUX))
    return svg("".join(out))


# ---------------------------------------------------------------- обложка
def cover_art():
    """Фон обложки: две окружности, их общая область и навигационная роза."""
    w, h = 1480, 2100
    cx, cy = w / 2, 905
    r = 330
    d = 150
    o = []
    # тончайшая сетка
    for i in range(0, w + 1, 74):
        o.append(line(i, 0, i, h, GOLD, 0.35, 0.18))
    for j in range(0, h + 1, 74):
        o.append(line(0, j, w, j, GOLD, 0.35, 0.18))
    # роза ветров
    for k in range(128):
        a = 2 * math.pi * k / 128
        r1 = 470
        r2 = 470 + (26 if k % 16 == 0 else 14 if k % 4 == 0 else 7)
        o.append(line(cx + r1 * math.cos(a), cy + r1 * math.sin(a),
                      cx + r2 * math.cos(a), cy + r2 * math.sin(a), GOLD, 1.0, 0.8))
    o.append(circle(cx, cy, 470, stroke=GOLD, sw=0.9, op=0.7))
    o.append(circle(cx, cy, 500, stroke=GOLD, sw=0.5, op=0.45))
    # две окружности
    o.append(circle(cx - d, cy, r, stroke=MILK, sw=1.4, op=0.9))
    o.append(circle(cx + d, cy, r, stroke=GOLD, sw=1.4))
    # vesica — общая область, тонкая штриховка
    # штриховка общей области двух кругов: считаем отрезки аналитически
    hh = math.sqrt(r * r - d * d)
    for j in range(-int(hh), int(hh) + 1, 7):
        y = cy + j
        half = math.sqrt(r * r - j * j) - d   # полуширина линзы на этой высоте
        if half > 1:
            o.append(line(cx - half, y, cx + half, y, GOLD, 0.9, 0.55))
    o.append(circle(cx, cy, 7, fill=GOLD))
    return svg("".join(o), w, h, bg="#2B0D12")


PLATES = {
    "plate-prologue": plate_prologue,
    "plate-01": plate_before,
    "plate-02": plate_meeting,
    "plate-03": plate_between,
    "plate-04": plate_memory,
    "plate-05": plate_distance,
    "plate-06": plate_letters,
    "plate-07": plate_time,
    "plate-08": plate_heart,
    "plate-epilogue": plate_open,
    "cover-art": cover_art,
}


def rasterize(svg_path: Path, png_path: Path, width_px: int, bg=MILK):
    doc = fitz.open(str(svg_path))
    page = doc[0]
    zoom = width_px / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    pix.save(str(png_path))


def main():
    OUT.mkdir(exist_ok=True)
    for name, fn in PLATES.items():
        s = fn()
        if "<rect width" not in s[:400]:
            # фон молока для растровых версий (в PDF фон даёт страница)
            s_bg = s.replace('height="1000">', f'height="1000"><rect width="1000" height="1000" fill="{MILK}"/>', 1)
        else:
            s_bg = s
        (OUT / f"{name}.svg").write_text(s, encoding="utf-8")
        tmp = OUT / f".{name}.bg.svg"
        tmp.write_text(s_bg, encoding="utf-8")
        rasterize(tmp, OUT / f"{name}.png", 1600)
        tmp.unlink()
    print("plates:", ", ".join(PLATES))


if __name__ == "__main__":
    main()
