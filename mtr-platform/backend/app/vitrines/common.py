"""Общие конструкторы ответа витрины.

Ответ витрины: {id, title, subtitle, kpis[], sections[], notes[]}.
Секция относится к одному из пяти управленческих вопросов: what/where/why/risk/action.
Графики передаются как данные + тип; оформление строится на фронтенде единообразно.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

QUESTIONS = {"what": "1. Что произошло?", "where": "2. Где произошло?", "why": "3. Почему?",
             "risk": "4. Каковы риски и последствия?", "action": "5. Что делать?"}


def clean(v):
    if v is None:
        return None
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def rub(x: float | None, digits: int = 1) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    a = abs(x)
    s = "−" if x < 0 else ""
    if a >= 1e9:
        return f"{s}{a / 1e9:,.{digits}f} млрд ₽".replace(",", " ").replace(".", ",")
    if a >= 1e6:
        return f"{s}{a / 1e6:,.{digits}f} млн ₽".replace(",", " ").replace(".", ",")
    if a >= 1e3:
        return f"{s}{a / 1e3:,.0f} тыс. ₽".replace(",", " ")
    return f"{s}{a:,.0f} ₽".replace(",", " ")


def pct(x: float | None, digits: int = 1, sign: bool = False) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    s = f"{x:+.{digits}f}" if sign else f"{x:.{digits}f}"
    return s.replace(".", ",") + "%"


def days(x) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "нет потребления"
    return f"{x:,.0f} дн.".replace(",", " ")


def kpi(id: str, label: str, value, unit: str = "rub", prev=None, target=None, hib: bool | None = None,
        note: str | None = None, status: str | None = None, sub: str | None = None, metric: str | None = None) -> dict:
    v, p = clean(value), clean(prev)
    delta = (v - p) if (v is not None and p is not None) else None
    dpct = (delta / abs(p) * 100) if (delta is not None and p not in (None, 0)) else None
    state = None
    if target is not None and v is not None:
        ok = v <= target if hib is False else v >= target if hib else None
        state = None if ok is None else ("ok" if ok else "bad")
    return dict(id=id, label=label, value=v, unit=unit, prev=p, delta=clean(delta), delta_pct=clean(dpct),
                target=clean(target), hib=hib, note=note, status=status, state=state, sub=sub, metric=metric or id)


def section(id: str, q: str, title: str, subtitle: str | None = None, chart: dict | None = None,
            table: dict | None = None, note: str | None = None, controls: list | None = None, kind: str | None = None,
            span: int = 1, extra: dict | None = None, drill: dict | None = None) -> dict:
    return dict(id=id, q=q, title=title, subtitle=subtitle, chart=chart, table=table, note=note, controls=controls or [],
                kind=kind, span=span, drill=drill, **(extra or {}))


def control(key: str, label: str, options: list[tuple[str, str]], value: str) -> dict:
    return dict(key=key, label=label, options=[dict(value=a, label=b) for a, b in options], value=value)


def col(key: str, label: str, type: str = "text", **kw) -> dict:
    return dict(key=key, label=label, type=type, **kw)


def table(df: pd.DataFrame, cols: list[dict], drill: dict | None = None, limit: int = 300, row_key: str | None = None,
          total: bool = False) -> dict:
    keys = [c["key"] for c in cols]
    extra = [k for k in ([drill["key"]] if drill and drill.get("key") else []) + ([row_key] if row_key else []) if k and k not in keys]
    d = df.head(limit)
    rows = []
    for rec in d[[k for k in keys + extra if k in d.columns]].to_dict("records"):
        rows.append({k: clean(v) for k, v in rec.items()})
    t = dict(columns=cols, rows=rows, drill=drill, n_total=int(len(df)), row_key=row_key)
    if total and len(df):
        tot = {}
        for c in cols:
            if c["type"] in ("money", "num", "int") and c["key"] in df.columns:
                tot[c["key"]] = clean(df[c["key"]].sum())
        t["total"] = tot
    return t


# ---------------- графики ----------------
def line(x: list, series: list[dict], unit: str = "rub", **kw) -> dict:
    return dict(kind="line", x=x, series=[{**s, "data": [clean(v) for v in s["data"]]} for s in series], unit=unit, **kw)


def bar(categories: list, series: list[dict], unit: str = "rub", horizontal: bool = False, stacked: bool = False, **kw) -> dict:
    return dict(kind="bar", categories=[str(c) for c in categories],
                series=[{**s, "data": [clean(v) for v in s["data"]]} for s in series], unit=unit,
                horizontal=horizontal, stacked=stacked, **kw)


def waterfall(items: list[tuple[str, float, str]], unit: str = "rub", **kw) -> dict:
    """items: (подпись, значение, 'total'|'delta')."""
    return dict(kind="waterfall", items=[dict(name=a, value=clean(b), type=c) for a, b, c in items], unit=unit, **kw)


def heatmap(x: list, y: list, values: list[list], unit: str = "rub", labels: list[list] | None = None,
            diverging: bool = False, **kw) -> dict:
    return dict(kind="heatmap", x=[str(i) for i in x], y=[str(i) for i in y], values=[[clean(v) for v in r] for r in values],
                labels=labels, unit=unit, diverging=diverging, **kw)


def treemap(nodes: list[dict], unit: str = "rub", **kw) -> dict:
    return dict(kind="treemap", nodes=nodes, unit=unit, **kw)


def sankey(nodes: list[str], links: list[dict], unit: str = "rub", **kw) -> dict:
    return dict(kind="sankey", nodes=[dict(name=n) for n in nodes], links=links, unit=unit, **kw)


def pareto_chart(p: dict, unit: str = "rub", **kw) -> dict:
    return dict(kind="pareto", **p, unit=unit, **kw)


def scatter(points: list[dict], x_label: str, y_label: str, x_unit: str = "num", y_unit: str = "rub",
            size_label: str | None = None, groups: list[str] | None = None, **kw) -> dict:
    pts = [{k: clean(v) for k, v in p.items()} for p in points]
    return dict(kind="scatter", points=pts, x_label=x_label, y_label=y_label, x_unit=x_unit, y_unit=y_unit,
                size_label=size_label, groups=groups, **kw)


def gantt(items: list[dict], now_label: str, **kw) -> dict:
    return dict(kind="gantt", items=[{k: clean(v) for k, v in i.items()} for i in items], now=now_label, **kw)


def band(x: list, series: list[dict], lower: list, upper: list, unit="rub", band_label="Интервал P10–P90", **kw) -> dict:
    return dict(kind="band", x=x, series=[{**s, "data": [clean(v) for v in s["data"]]} for s in series],
                lower=[clean(v) for v in lower], upper=[clean(v) for v in upper], band_label=band_label, unit=unit, **kw)


def top(df: pd.DataFrame, col_: str, n: int = 10, asc: bool = False) -> pd.DataFrame:
    d = df[df[col_].notna()]
    return d.sort_values(col_, ascending=asc).head(n)


def opt(opts: dict, key: str, default: str) -> str:
    return opts.get(key) or default
