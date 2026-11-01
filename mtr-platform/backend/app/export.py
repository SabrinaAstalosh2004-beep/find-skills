"""Экспорт витрин в Excel и PDF (кириллица — шрифт DejaVu)."""
from __future__ import annotations

import io
import pathlib
import re

import pandas as pd

from . import db


def section_frames(sec: dict) -> list[tuple[str, pd.DataFrame]]:
    out = []
    t = sec.get("table")
    if t and t.get("rows"):
        cols = [c["key"] for c in t["columns"]]
        df = pd.DataFrame(t["rows"])
        df = df[[c for c in cols if c in df.columns]]
        df.columns = [next(c["label"] for c in t["columns"] if c["key"] == k) for k in df.columns]
        out.append(("Таблица", df))
    ch = sec.get("chart")
    if ch:
        k = ch["kind"]
        df = None
        if k in ("line", "band"):
            df = pd.DataFrame({"Период": ch["x"], **{s["name"]: s["data"] for s in ch["series"]}})
        elif k == "bar":
            df = pd.DataFrame({"Категория": ch["categories"], **{s["name"]: s["data"] for s in ch["series"] if len(s["data"]) == len(ch["categories"])}})
        elif k == "waterfall":
            df = pd.DataFrame([dict(Фактор=i["name"], Значение=i["value"], Тип=i["type"]) for i in ch["items"]])
        elif k == "heatmap":
            df = pd.DataFrame(ch["values"], index=ch["y"], columns=ch["x"]).reset_index()
        elif k == "pareto":
            df = pd.DataFrame({"Категория": ch["categories"], "Значение": ch["values"], "Накопленная доля, %": ch["cum_share"]})
        elif k == "scatter":
            df = pd.DataFrame(ch["points"])
        elif k == "treemap":
            rows = []
            for n in ch["nodes"]:
                for c in n.get("children", []) or [n]:
                    rows.append({"Уровень 1": n["name"], "Уровень 2": c["name"] if c is not n else "", "Значение": c["value"]})
            df = pd.DataFrame(rows)
        elif k == "sankey":
            df = pd.DataFrame(ch["links"])
        elif k == "gantt":
            df = pd.DataFrame(ch["items"])
        if df is not None and len(df):
            out.append(("Данные графика", df))
    return out


def to_xlsx(payload: dict) -> bytes:
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as xw:
        head = [["ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ" if payload.get("is_demo") else "Данные источника"], [f"Витрина {payload['id']}. {payload['title']}"],
                [f"Период: {payload['ctx']['period']}"], [f"Дата среза: {payload['ctx']['asof_label']}"], [f"Фильтры: {payload['ctx']['filters'] or 'нет'}"],
                [f"Роль: {payload['ctx'].get('role_label')}"], [""]]
        k = pd.DataFrame([dict(Показатель=x["label"], Значение=x["value"], Единица=x["unit"], Предыдущий=x.get("prev"), Цель=x.get("target"), Комментарий=x.get("sub") or x.get("note"))
                          for x in payload.get("kpis", [])])
        pd.DataFrame(head).to_excel(xw, sheet_name="Сводка", index=False, header=False)
        if len(k):
            k.to_excel(xw, sheet_name="Сводка", index=False, startrow=len(head))
        used = {"Сводка"}
        for i, s in enumerate(payload.get("sections", []), 1):
            for kind, df in section_frames(s):
                name = re.sub(r"[:\\/?*\[\]]", " ", f"{i}. {s['title']}")[:28]
                base, j = name, 2
                while name in used:
                    name = f"{base[:25]}~{j}"
                    j += 1
                used.add(name)
                pd.DataFrame([[s["title"]], [s.get("subtitle") or ""], [kind]]).to_excel(xw, sheet_name=name, index=False, header=False)
                df.to_excel(xw, sheet_name=name, index=False, startrow=4)
        ins = payload.get("insights") or []
        if ins:
            pd.DataFrame([dict(Проблема=x["title"], Наблюдение=x["observation"], Причина=x["cause"], Статус=x["cause_status"], Действие=x["action"],
                               Сумма=x["value_at_risk"], Ответственный=x["owner"]) for x in ins]).to_excel(xw, sheet_name="Отклонения и рекомендации", index=False)
    return bio.getvalue()


def _font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",
              "/Library/Fonts/Arial Unicode.ttf", "C:/Windows/Fonts/arial.ttf"]:
        if pathlib.Path(p).exists():
            try:
                pdfmetrics.registerFont(TTFont("Cyr", p))
                return "Cyr"
            except Exception:
                pass
    return "Helvetica"


def _fmt(v):
    if isinstance(v, float):
        if abs(v) >= 1e6:
            return f"{v / 1e6:,.1f} млн".replace(",", " ").replace(".", ",")
        return f"{v:,.1f}".replace(",", " ").replace(".", ",")
    return "" if v is None else str(v)


def to_pdf(payload: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    f = _font()
    st = ParagraphStyle("b", fontName=f, fontSize=8, leading=10)
    h1 = ParagraphStyle("h1", fontName=f, fontSize=14, leading=18, spaceAfter=6)
    h2 = ParagraphStyle("h2", fontName=f, fontSize=10, leading=13, spaceBefore=8, spaceAfter=3)
    demo = ParagraphStyle("d", fontName=f, fontSize=9, textColor=colors.HexColor("#b45309"))
    bio = io.BytesIO()
    doc = SimpleDocTemplate(bio, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=10 * mm, bottomMargin=10 * mm)
    el = []
    if payload.get("is_demo"):
        el.append(Paragraph("ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ — синтетический набор, не являются корпоративными показателями", demo))
    el.append(Paragraph(f"Витрина {payload['id']}. {payload['title']}", h1))
    el.append(Paragraph(f"Период: {payload['ctx']['period']} · срез: {payload['ctx']['asof_label']} · фильтры: {payload['ctx']['filters'] or 'нет'}", st))
    if payload.get("kpis"):
        data = [["Показатель", "Значение", "Предыдущий", "Комментарий"]] + [[Paragraph(x["label"], st), _fmt(x["value"]), _fmt(x.get("prev")),
                                                                           Paragraph(str(x.get("sub") or x.get("note") or ""), st)] for x in payload["kpis"]]
        t = Table(data, colWidths=[70 * mm, 35 * mm, 35 * mm, 130 * mm])
        t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), f), ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb"))]))
        el += [Spacer(1, 4), t]
    for s in payload.get("sections", []):
        el.append(Paragraph(s["title"], h2))
        if s.get("subtitle"):
            el.append(Paragraph(s["subtitle"], st))
        for kind, df in section_frames(s)[:1]:
            df = df.head(30)
            cols = list(df.columns)[:9]
            data = [[Paragraph(str(c), st) for c in cols]] + [[Paragraph(_fmt(v), st) for v in r] for r in df[cols].itertuples(index=False)]
            w = 270 * mm / max(1, len(cols))
            t = Table(data, colWidths=[w] * len(cols), repeatRows=1)
            t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), f), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            el.append(t)
        if s.get("note"):
            el.append(Paragraph("Примечание: " + s["note"], st))
    el.append(Spacer(1, 8))
    el.append(Paragraph("Методики — рабочие (демо), требуют подтверждения корпоративной методологией. Графики в PDF представлены таблицами данных; "
                        "для печати с графиками используйте «Печать» в интерфейсе.", st))
    doc.build(el)
    return bio.getvalue()
