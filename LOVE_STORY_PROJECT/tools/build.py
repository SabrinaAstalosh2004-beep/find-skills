"""Сборка книги «Атлас одной любви» во все форматы.

    python3 tools/build.py

Что делает:
  1. рисует иллюстрации (tools/plates.py);
  2. берёт ваши фото из photos/ (photo-01.jpg …) или ставит элегантную заглушку;
  3. собирает PDF для печати (A5 + вылеты), PDF для iPhone, EPUB и DOCX
     в папку ../LOVE_STORY_FINAL.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
BUILD = ROOT / "build"
FINAL = ROOT.parent / "LOVE_STORY_FINAL"
SRC = ROOT / "content" / "book.md"
FONTS = ROOT / "fonts"
NAME = "Атлас_одной_любви"

sys.path.insert(0, str(TOOLS))


def log(*a):
    print("·", *a, flush=True)


# ------------------------------------------------------------------ фото
SIZES = {"portrait": (1200, 1600), "landscape": (1600, 1200), "full": (1480, 2100)}
ORIENT_RU = {"portrait": "вертикальное · 3 : 4", "landscape": "горизонтальное · 4 : 3",
             "full": "на всю страницу · вертикальное"}


def photo_slots():
    text = SRC.read_text(encoding="utf-8")
    slots = {}
    for m in re.finditer(r'\{\.photo slot="(\d+)"[^}]*orient="(\w+)"', text):
        slots[m.group(1)] = m.group(2)
    for m in re.finditer(r'\{\.pair slots="([\d,]+)"', text):
        for s in m.group(1).split(","):
            slots[s] = "portrait"
    for m in re.finditer(r'\{\.bleed slot="(\d+)"', text):
        slots[m.group(1)] = "full"
    return dict(sorted(slots.items()))


def find_user_photo(slot):
    for ext in ("jpg", "jpeg", "png", "webp", "JPG", "JPEG", "PNG", "heic", "HEIC"):
        p = ROOT / "photos" / f"photo-{slot}.{ext}"
        if p.exists():
            return p
    return None


def placeholder(slot, orient):
    w, h = SIZES[orient]
    im = Image.new("RGB", (w, h), "#ECE5D8")
    d = ImageDraw.Draw(im)
    gold, ash, bord = (168, 133, 80), (140, 128, 120), (107, 30, 42)
    m1, m2 = int(w * .045), int(w * .06)
    d.rectangle([m1, m1, w - m1, h - m1], outline=gold, width=2)
    d.rectangle([m2, m2, w - m2, h - m2], outline=(206, 190, 160), width=1)
    cx, cy = w // 2, h // 2 - int(h * .03)
    r = int(min(w, h) * .085)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=gold, width=2)
    d.line([cx - r * 1.6, cy, cx + r * 1.6, cy], fill=gold, width=1)
    d.line([cx, cy - r * 1.6, cx, cy + r * 1.6], fill=gold, width=1)
    d.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=bord)
    f1 = ImageFont.truetype(str(FONTS / "CormorantSC-Medium.ttf"), int(w * .04))
    f2 = ImageFont.truetype(str(FONTS / "CormorantGaramond-Italic.ttf"), int(w * .042))
    t1 = "  ".join(f"ФОТО {slot}")  # разрядка
    t1 = f"Ф О Т О   {slot}"
    tw = d.textlength(t1, font=f1)
    d.text((cx - tw / 2, cy + r * 2.1), t1, font=f1, fill=bord)
    t2 = ORIENT_RU[orient]
    tw = d.textlength(t2, font=f2)
    d.text((cx - tw / 2, cy + r * 2.1 + w * .065), t2, font=f2, fill=ash)
    t3 = f"положите файл photos/photo-{slot}.jpg"
    f3 = ImageFont.truetype(str(FONTS / "CormorantGaramond-Regular.ttf"), int(w * .03))
    tw = d.textlength(t3, font=f3)
    d.text((cx - tw / 2, h - m2 - w * .075), t3, font=f3, fill=ash)
    return im


def prepare_photos():
    full, mob = BUILD / "photos", BUILD / "photos_m"
    for p in (full, mob):
        shutil.rmtree(p, ignore_errors=True)
        p.mkdir(parents=True)
    report = []
    for slot, orient in photo_slots().items():
        src = find_user_photo(slot)
        if src:
            if src.suffix.lower() == ".heic":
                try:
                    import pillow_heif
                    pillow_heif.register_heif_opener()
                except ImportError:
                    sys.exit("Для HEIC установите: pip install pillow-heif (или сохраните фото как JPG)")
            im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")  # только поворот по EXIF
            report.append((slot, orient, src.name))
        else:
            im = placeholder(slot, orient)
            report.append((slot, orient, None))
        a = im.copy(); a.thumbnail((3000, 3000)); a.save(full / f"photo-{slot}.jpg", quality=92)
        b = im.copy(); b.thumbnail((1200, 1200)); b.save(mob / f"photo-{slot}.jpg", quality=80, optimize=True)
    return report


# ------------------------------------------------------------------ pandoc
def pandoc(args, target, art_ext, photo_dir="photos"):
    env = dict(os.environ, BOOK_TARGET=target, ART_EXT=art_ext, PHOTO_DIR=photo_dir)
    cmd = ["pandoc", str(SRC), "-f", "markdown", "--lua-filter", str(TOOLS / "book.lua")] + args
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=BUILD)
    if r.returncode != 0:
        sys.exit(f"pandoc ({target}) error:\n{r.stderr}")
    if r.stderr.strip():
        log(f"pandoc {target}:", r.stderr.strip()[:500])
    return r.stdout


def html_doc(body, css_files, photo_dir):
    css = "\n".join((TOOLS / "css" / c).read_text(encoding="utf-8") for c in css_files)
    if photo_dir != "photos":
        body = body.replace('src="photos/', f'src="{photo_dir}/')
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            f'<title>Атлас одной любви</title><style>{css}</style></head><body>{body}</body></html>')


def build_pdf(kind):
    from weasyprint import HTML
    if kind == "print":
        body = pandoc(["-t", "html5"], "print", "svg")
        html = html_doc(body, ["base.css", "print.css"], "photos")
        out = FINAL / f"{NAME}_print_A5.pdf"
        opts = dict()
    else:
        body = pandoc(["-t", "html5"], "mobile", "svg")
        html = html_doc(body, ["base.css", "mobile.css"], "photos_m")
        out = FINAL / f"{NAME}_iPhone.pdf"
        opts = dict(jpeg_quality=80, dpi=220, optimize_images=True)
    (BUILD / f"{kind}.html").write_text(html, encoding="utf-8")
    HTML(string=html, base_url=str(BUILD) + "/").write_pdf(
        str(out), pdf_variant=None, uncompressed_pdf=False,
        metadata=True, **opts)
    log("PDF", kind, "→", out.name)
    return out


def render_cover_png(print_pdf):
    import pymupdf
    doc = pymupdf.open(str(print_pdf))
    page = doc[0]
    mm = 72 / 25.4
    r = page.rect
    clip = pymupdf.Rect(r.x0 + 3 * mm, r.y0 + 3 * mm, r.x1 - 3 * mm, r.y1 - 3 * mm)
    zoom = 1600 / clip.width
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False)
    out = BUILD / "art" / "cover.png"
    pix.save(str(out))
    Image.open(out).convert("RGB").save(BUILD / "art" / "cover.jpg", quality=90)
    return out


def build_epub():
    fonts = ["EBGaramond-Regular.ttf", "EBGaramond-Italic.ttf", "CormorantGaramond-Light.ttf",
             "CormorantGaramond-Italic.ttf", "CormorantSC-Medium.ttf"]
    out = FINAL / f"{NAME}.epub"
    args = ["-t", "epub3", "-o", str(out), "--css", str(TOOLS / "css" / "epub.css"),
            "--epub-cover-image", str(BUILD / "art" / "cover.jpg"), "--toc", "--toc-depth=1",
            "--split-level=1", "--epub-title-page=false", "--resource-path", str(BUILD),
            "-M", "lang=ru-RU"]
    for f in fonts:
        args += ["--epub-embed-font", str(FONTS / f)]
    pandoc(args, "epub", "png", "photos_m")
    log("EPUB →", out.name)
    return out


def build_docx():
    from make_reference import make_reference
    ref = BUILD / "reference.docx"
    make_reference(ref)
    out = FINAL / f"{NAME}_рукопись.docx"
    pandoc(["-t", "docx", "-o", str(out), "--reference-doc", str(ref), "--resource-path", str(BUILD)],
           "docx", "png", "photos_m")
    log("DOCX →", out.name)
    return out


def main():
    BUILD.mkdir(exist_ok=True)
    FINAL.mkdir(exist_ok=True)
    import plates
    plates.main()
    shutil.rmtree(BUILD / "art", ignore_errors=True)
    shutil.copytree(ROOT / "art", BUILD / "art")
    report = prepare_photos()
    real = [r for r in report if r[2]]
    log(f"фото: {len(real)} ваших, {len(report) - len(real)} заглушек")
    pdf = build_pdf("print")
    render_cover_png(pdf)
    shutil.copy(BUILD / "art" / "cover.jpg", FINAL / "Обложка.jpg")
    build_pdf("mobile")
    build_epub()
    build_docx()
    fdir = FINAL / "Шрифты_для_DOCX"
    fdir.mkdir(exist_ok=True)
    for f in FONTS.glob("*"):
        shutil.copy(f, fdir / f.name)
    log("готово:", FINAL)


if __name__ == "__main__":
    main()
