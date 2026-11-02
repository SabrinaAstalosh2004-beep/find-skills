"""Создаёт reference.docx — набор стилей Word для редактируемой рукописи."""
import subprocess
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor

BODY = "EB Garamond"
DISPLAY = "Cormorant Garamond"
INK = RGBColor(0x1A, 0x15, 0x17)
BORDEAUX = RGBColor(0x6B, 0x1E, 0x2A)
GOLD = RGBColor(0xA8, 0x85, 0x50)
ASH = RGBColor(0x8C, 0x80, 0x78)


def _font(style, name, size, color=INK, italic=None, bold=False, caps=False):
    f = style.font
    f.name = name
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rFonts")
    if rfonts is None:
        rfonts = rpr.makeelement("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rFonts", {})
        rpr.append(rfonts)
    for a in ("ascii", "hAnsi", "cs", "eastAsia"):
        rfonts.set(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}{a}", name)
    f.size = Pt(size)
    f.color.rgb = color
    f.bold = bold
    if italic is not None:
        f.italic = italic
    f.small_caps = caps


def _para(style, align=None, before=0, after=0, indent=None, line=None, keep=False, page_before=False):
    pf = style.paragraph_format
    if align is not None:
        pf.alignment = align
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    if indent is not None:
        pf.first_line_indent = indent
    if line:
        pf.line_spacing = line
    pf.keep_with_next = keep
    pf.page_break_before = page_before


def get_style(doc, name):
    for st in doc.styles:  # прямой поиск: python-docx переименовывает «Heading 1» при обращении по ключу
        if st.name == name:
            return st
    s = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    s.base_style = get_style(doc, "Normal")
    return s


def make_reference(out: Path):
    data = subprocess.run(["pandoc", "--print-default-data-file", "reference.docx"],
                          capture_output=True, check=True).stdout
    out.write_bytes(data)
    doc = Document(str(out))
    C = WD_ALIGN_PARAGRAPH.CENTER

    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(14.8), Cm(21.0)
    sec.left_margin = sec.right_margin = Cm(1.8)
    sec.top_margin, sec.bottom_margin = Cm(1.8), Cm(2.0)

    for name in ("Normal", "Body Text", "First Paragraph", "Compact"):
        s = get_style(doc, name)
        _font(s, BODY, 11)
        _para(s, WD_ALIGN_PARAGRAPH.JUSTIFY, 0, 0, Cm(0.6), 1.25)
    _para(get_style(doc, "First Paragraph"), indent=Cm(0))

    h1 = get_style(doc, "Heading 1")
    _font(h1, DISPLAY, 24, INK, italic=False)
    _para(h1, C, 72, 18, Cm(0), keep=True, page_before=True)
    for n, size in (("Heading 2", 10), ("Heading 3", 13)):
        s = get_style(doc, n)
        _font(s, DISPLAY, size, GOLD if n == "Heading 2" else INK, italic=(n == "Heading 3"),
              caps=(n == "Heading 2"))
        _para(s, C, 18, 6, Cm(0), keep=True)
    get_style(doc, "Title").font.name = DISPLAY

    spec = {
        "Plate": dict(f=(BODY, 10), p=(C, 0, 24, Cm(0))),
        "Photo": dict(f=(BODY, 10), p=(C, 24, 6, Cm(0))),
        "Caption": dict(f=(DISPLAY, 12, INK, True), p=(C, 6, 12, Cm(0))),
        "Quote Page": dict(f=(DISPLAY, 17, INK, True), p=(C, 120, 6, Cm(0), 1.2)),
        "Quote Source": dict(f=(DISPLAY, 9, GOLD, False, False, True), p=(C, 12, 12, Cm(0))),
        "Dedication": dict(f=(DISPLAY, 16, INK, True), p=(C, 120, 0, Cm(0), 1.3)),
        "Epigraph": dict(f=(DISPLAY, 14, INK, True), p=(C, 120, 0, Cm(0), 1.3)),
        "Letter": dict(f=(DISPLAY, 13, INK, False), p=(WD_ALIGN_PARAGRAPH.LEFT, 0, 8, Cm(0), 1.2)),
        "Messages": dict(f=(BODY, 10.5), p=(WD_ALIGN_PARAGRAPH.LEFT, 0, 10, Cm(0))),
        "Notes": dict(f=(BODY, 10.5), p=(WD_ALIGN_PARAGRAPH.LEFT, 0, 8, Cm(0))),
        "Song Note": dict(f=(DISPLAY, 12, ASH, True), p=(C, 12, 12, Cm(0))),
        "Chronology": dict(f=(BODY, 10.5), p=(WD_ALIGN_PARAGRAPH.LEFT, 0, 8, Cm(0))),
        "Small Note": dict(f=(BODY, 9.5, ASH, True), p=(WD_ALIGN_PARAGRAPH.LEFT, 12, 6, Cm(0))),
        "Poem": dict(f=(BODY, 11), p=(C, 0, 6, Cm(0))),
        "Poem Year": dict(f=(DISPLAY, 9, ASH, False, False, True), p=(C, 4, 18, Cm(0))),
        "Sayings": dict(f=(DISPLAY, 13, INK, True), p=(C, 18, 2, Cm(0))),
        "Final": dict(f=(DISPLAY, 24, INK, True), p=(C, 180, 6, Cm(0))),
        "Final Sub": dict(f=(DISPLAY, 10, GOLD, False, False, True), p=(C, 12, 0, Cm(0))),
        "Colophon": dict(f=(DISPLAY, 9, ASH, False, False, True), p=(C, 300, 0, Cm(0))),
        "Imprint": dict(f=(BODY, 8.5, ASH), p=(WD_ALIGN_PARAGRAPH.LEFT, 0, 4, Cm(0))),
        "Half Title": dict(f=(DISPLAY, 16, INK, True), p=(C, 160, 0, Cm(0))),
        "Title Author": dict(f=(DISPLAY, 10, GOLD, False, False, True), p=(C, 60, 40, Cm(0))),
        "Title Main": dict(f=(DISPLAY, 38, BORDEAUX, False), p=(C, 0, 0, Cm(0), 1.0)),
        "Title Sub": dict(f=(DISPLAY, 13, INK, True), p=(C, 24, 0, Cm(0))),
        "Title Place": dict(f=(DISPLAY, 9, ASH, False, False, True), p=(C, 140, 0, Cm(0))),
    }
    for name, d in spec.items():
        s = get_style(doc, name)
        f = d["f"]
        _font(s, f[0], f[1], *(f[2:] if len(f) > 2 else ()))
        p = d["p"]
        _para(s, p[0], p[1], p[2], p[3], p[4] if len(p) > 4 else None)
    doc.save(str(out))


if __name__ == "__main__":
    make_reference(Path("reference.docx"))
