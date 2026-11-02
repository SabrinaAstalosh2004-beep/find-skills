"""Контактные листы страниц PDF для визуальной проверки: python3 tools/preview.py file.pdf out_prefix"""
import sys, pymupdf
from PIL import Image
pdf, prefix = sys.argv[1], sys.argv[2]
doc = pymupdf.open(pdf)
cols, tw = 8, 260
thumbs = []
for p in doc:
    pix = p.get_pixmap(matrix=pymupdf.Matrix(tw / p.rect.width, tw / p.rect.width), alpha=False)
    thumbs.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
th = thumbs[0].height
per = cols * 4
for s in range(0, len(thumbs), per):
    chunk = thumbs[s:s + per]
    rows = (len(chunk) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw + 8), rows * (th + 8)), "#777")
    for i, t in enumerate(chunk):
        sheet.paste(t, ((i % cols) * (tw + 8), (i // cols) * (th + 8)))
    sheet.save(f"{prefix}-{s // per + 1}.png")
print(len(doc), "pages")
