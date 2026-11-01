"""Единый расчётный слой. Все витрины, конструктор срезов, помощник и экспорт
используют только эти функции — расчётная логика не дублируется.

Ключевые соглашения (см. также каталог метрик в metrics.py):
* стоимость запасов — по позициям на балансе (консигнация поставщика исключается);
* средний остаток за период — хронологическое среднее по месячным срезам:
  (S0/2 + S1 + ... + S(n-1) + Sn/2) / n, где S0 — остаток на начало периода;
* оборачиваемость группы считается из сумм (средний остаток / потребление × дни),
  а не как среднее показателей обществ;
* при нулевом потреблении оборачиваемость не рассчитывается (статус «нет потребления»).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import db
from . import settings as cfg
from .filters import DIMENSIONS, SNAPSHOT_ONLY_DIMS, Ctx

BASE_COLS = ["stock_end", "stock_start", "stock_avg", "qty_end", "nez_end", "nez_start", "free_end", "reserved_end",
             "unavail_end", "noissue_end", "crit_end", "special_end", "slow_need_end", "n_items",
             "receipts", "consumption", "returns", "tr_in", "tr_out", "adjust", "reval", "sales", "writeoff",
             "nez_new", "nez_consumed", "nez_transferred", "nez_sold", "nez_written_off", "nez_reclass_out", "nez_reval",
             "open_po", "overdue_po", "plan_value", "deficit_value", "deficit_crit_value"]


def _dims_sql(dims: list[str], prefix: str = "") -> tuple[str, str, list[str]]:
    sel, grp, keys = [], [], []
    for i, d in enumerate(dims):
        idc, lbl, _ = DIMENSIONS[d]
        idc, lbl = prefix + idc, prefix + lbl
        sel.append(f"COALESCE(CAST({idc} AS VARCHAR), '—') AS {d}, ANY_VALUE(COALESCE(CAST({lbl} AS VARCHAR), '(не указано)')) AS {d}_label")
        grp.append(f"COALESCE(CAST({idc} AS VARCHAR), '—')")
        keys.append(d)
    return (", ".join(sel) + ", ") if sel else "", ("GROUP BY " + ", ".join(grp)) if grp else "", keys


def aggregate(ctx: Ctx, dims: list[str] | None = None, m1: int | None = None, m2: int | None = None,
              parts: tuple[str, ...] = ("snap", "mov", "nez", "po", "plan", "deficit")) -> pd.DataFrame:
    dims = dims or []
    m1 = ctx.m1 if m1 is None else m1
    m2 = ctx.m2 if m2 is None else m2
    n = m2 - m1 + 1
    sel, grp, keys = _dims_sql(dims)
    w = ctx.where()
    frames = []
    if "snap" in parts:
        frames.append(db.q(f"""
        SELECT {sel}
          SUM(CASE WHEN m={m2} THEN value ELSE 0 END) stock_end,
          SUM(CASE WHEN m={m1 - 1} THEN value ELSE 0 END) stock_start,
          SUM(value * CASE WHEN m IN ({m1 - 1},{m2}) THEN 0.5 ELSE 1 END) / {n} stock_avg,
          SUM(CASE WHEN m={m2} THEN qty ELSE 0 END) qty_end,
          SUM(CASE WHEN m={m2} THEN nez_value ELSE 0 END) nez_end,
          SUM(CASE WHEN m={m1 - 1} THEN nez_value ELSE 0 END) nez_start,
          SUM(CASE WHEN m={m2} THEN free_value ELSE 0 END) free_end,
          SUM(CASE WHEN m={m2} THEN reserved_value ELSE 0 END) reserved_end,
          SUM(CASE WHEN m={m2} THEN unavailable_value ELSE 0 END) unavail_end,
          SUM(CASE WHEN m={m2} THEN noissue_value ELSE 0 END) noissue_end,
          SUM(CASE WHEN m={m2} AND criticality='A — критичный' THEN value ELSE 0 END) crit_end,
          SUM(CASE WHEN m={m2} AND special_flag THEN value ELSE 0 END) special_end,
          SUM(CASE WHEN m={m2} THEN slow_with_need_value ELSE 0 END) slow_need_end,
          COUNT(DISTINCT CASE WHEN m={m2} AND qty>0 THEN material_id END) n_items
        FROM snap WHERE on_balance AND m BETWEEN {m1 - 1} AND {m2} AND {w} {grp}"""))
    if "mov" in parts and not (set(dims) & SNAPSHOT_ONLY_DIMS):
        frames.append(db.q(f"""
        SELECT {sel}
          SUM(CASE WHEN mtype='Поступление' THEN value ELSE 0 END) receipts,
          SUM(CASE WHEN mtype='Потребление' THEN value ELSE 0 END) consumption,
          SUM(CASE WHEN mtype='Возврат' THEN value ELSE 0 END) returns,
          SUM(CASE WHEN mtype='Перемещение (приход)' THEN value ELSE 0 END) tr_in,
          SUM(CASE WHEN mtype='Перемещение (расход)' THEN value ELSE 0 END) tr_out,
          SUM(CASE WHEN mtype='Корректировка' THEN value ELSE 0 END) adjust,
          SUM(CASE WHEN mtype='Переоценка' THEN value ELSE 0 END) reval,
          SUM(CASE WHEN mtype='Реализация' THEN value ELSE 0 END) sales,
          SUM(CASE WHEN mtype='Списание' THEN value ELSE 0 END) writeoff
        FROM v_mov WHERE on_balance AND m BETWEEN {m1} AND {m2} AND {w} {grp}"""))
    if "nez" in parts and not (set(dims) & SNAPSHOT_ONLY_DIMS):
        frames.append(db.q(f"""
        SELECT {sel} SUM(nez_new) nez_new, SUM(nez_consumed) nez_consumed, SUM(nez_transferred) nez_transferred,
          SUM(nez_sold) nez_sold, SUM(nez_written_off) nez_written_off, SUM(nez_reclass_out) nez_reclass_out,
          SUM(nez_reval) nez_reval
        FROM v_nezf WHERE on_balance AND m BETWEEN {m1} AND {m2} AND {w} {grp}"""))
    if "po" in parts and not (set(dims) & SNAPSHOT_ONLY_DIMS):
        frames.append(db.q(f"""
        SELECT {sel}
          SUM(CASE WHEN currency='RUB' THEN po_value ELSE 0 END) open_po,
          SUM(CASE WHEN currency='RUB' AND planned_delivery < (SELECT month_end FROM cal WHERE m={m2}) THEN po_value ELSE 0 END) overdue_po
        FROM v_po WHERE order_date <= (SELECT month_end FROM cal WHERE m={m2})
          AND actual_delivery > (SELECT month_end FROM cal WHERE m={m2}) AND {w} {grp}"""))
    if "plan" in parts and not (set(dims) & SNAPSHOT_ONLY_DIMS):
        dsel, dgrp, _ = _dims_sql(dims, "d.")
        frames.append(db.q(f"""
        SELECT {dsel} SUM(d.plan_qty * s.price) plan_value
        FROM v_dem d JOIN snapshot s ON s.position_id = d.position_id AND s.m = d.m
        WHERE d.on_balance AND d.m BETWEEN {m1} AND {m2} AND {ctx.where('d')} {dgrp}"""))
    if "deficit" in parts and not (set(dims) & SNAPSHOT_ONLY_DIMS):
        dfp = deficit_positions(ctx, asof=m2)
        if len(dfp):
            if keys:
                for d in dims:
                    idc, lbl, _ = DIMENSIONS[d]
                    dfp[d] = dfp[idc].astype(object).where(dfp[idc].notna(), "—").astype(str)
                    dfp[f"{d}_label"] = dfp[lbl].astype(object).where(dfp[lbl].notna(), "(не указано)").astype(str)
                g = dfp.groupby(keys).agg(**{f"{d}_label": (f"{d}_label", "first") for d in dims},
                                          deficit_value=("shortage_value", "sum"),
                                          deficit_crit_value=("crit_shortage_value", "sum")).reset_index()
            else:
                g = pd.DataFrame({"deficit_value": [dfp.shortage_value.sum()],
                                  "deficit_crit_value": [dfp.crit_shortage_value.sum()]})
            frames.append(g)
    out = None
    for f in frames:
        if out is None:
            out = f
        elif keys:
            lbls = [f"{d}_label" for d in dims]
            f2 = f.drop(columns=[c for c in lbls if c in f.columns and c in out.columns])
            out = out.merge(f2, on=keys, how="outer")
            for d in dims:  # подписи для строк, отсутствующих в первом наборе
                if f"{d}_label" in f.columns:
                    lm = f.set_index(d)[f"{d}_label"].to_dict()
                    out[f"{d}_label"] = out[f"{d}_label"].fillna(out[d].map(lm))
        else:
            out = pd.concat([out.reset_index(drop=True), f.reset_index(drop=True)], axis=1)
    if out is None:
        out = pd.DataFrame()
    for c in BASE_COLS:
        if c not in out.columns:
            out[c] = 0.0
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)
    for d in dims:
        out[f"{d}_label"] = out[f"{d}_label"].fillna(out[d])
    from .metrics import derive
    return derive(out, days=ctx.days(m1, m2), n_months=n)


def kpis(ctx: Ctx, m1=None, m2=None) -> dict:
    df = aggregate(ctx, [], m1, m2)
    return df.iloc[0].to_dict() if len(df) else {}


# ------------------------------------------------------------------------------------------
def series(ctx: Ctx, dims: list[str] | None = None, m_from: int | None = None, m_to: int | None = None,
           flows: bool = True) -> pd.DataFrame:
    """Помесячные ряды: остатки на конец месяца и движения за месяц."""
    dims = dims or []
    m_from = max(0, ctx.m1 if m_from is None else m_from)
    m_to = ctx.m2 if m_to is None else m_to
    sel, grp, keys = _dims_sql(dims)
    grp_m = ("GROUP BY m, " + grp.replace("GROUP BY ", "")) if grp else "GROUP BY m"
    w = ctx.where()
    s = db.q(f"""SELECT m, {sel} SUM(value) stock, SUM(nez_value) nez, SUM(free_value) free,
                 SUM(reserved_value) reserved, SUM(noissue_value) noissue, SUM(qty) qty
                 FROM snap WHERE on_balance AND m BETWEEN {m_from} AND {m_to} AND {w} {grp_m}""")
    if flows:
        f = db.q(f"""SELECT m, {sel}
              SUM(CASE WHEN mtype='Поступление' THEN value ELSE 0 END) receipts,
              SUM(CASE WHEN mtype='Потребление' THEN value ELSE 0 END) consumption,
              SUM(CASE WHEN mtype='Переоценка' THEN value ELSE 0 END) reval,
              SUM(CASE WHEN mtype IN ('Реализация','Списание') THEN value ELSE 0 END) disposal
              FROM v_mov WHERE on_balance AND m BETWEEN {m_from} AND {m_to} AND {w} {grp_m}""")
        lbls = [f"{d}_label" for d in dims]
        s = s.merge(f.drop(columns=lbls), on=["m"] + keys, how="outer")
    s = s.fillna({c: 0 for c in ["stock", "nez", "free", "reserved", "noissue", "qty", "receipts", "consumption", "reval", "disposal"] if c in s.columns})
    s = s.sort_values(["m"] + keys).reset_index(drop=True)
    s["label"] = s.m.map(db.month_label)
    return s


def turnover_ltm(ctx: Ctx, dims: list[str] | None = None, m_from: int | None = None, m_to: int | None = None,
                 window: int = 12) -> pd.DataFrame:
    """Скользящая оборачиваемость (LTM): хронологическое среднее остатка за 12 мес. / потребление за 12 мес. × дни."""
    from .generator import days_in_month
    dims = dims or []
    m_from = ctx.m1 if m_from is None else m_from
    m_to = ctx.m2 if m_to is None else m_to
    base = series(ctx, dims, max(0, m_from - window), m_to)
    keys = dims
    out = []
    groups = base.groupby(keys) if keys else [((), base)]
    for k, g in groups:
        g = g.set_index("m")
        for t in range(m_from, m_to + 1):
            a = t - window + 1
            if a - 1 < 0:
                continue
            st = [g.stock.get(x, 0.0) for x in range(a - 1, t + 1)]
            avg = (st[0] / 2 + sum(st[1:-1]) + st[-1] / 2) / window
            cons = sum(g.consumption.get(x, 0.0) for x in range(a, t + 1))
            days = sum(days_in_month(x) for x in range(a, t + 1))
            row = {"m": t, "label": db.month_label(t), "stock_avg": avg, "consumption": cons,
                   "turnover_days": (avg / cons * days) if cons > 0 else None}
            if keys:
                kk = k if isinstance(k, tuple) else (k,)
                for d, v in zip(keys, kk):
                    row[d] = v
                    row[f"{d}_label"] = g[f"{d}_label"].iloc[0]
            out.append(row)
    return pd.DataFrame(out)


def to_grain(df: pd.DataFrame, grain: str, stock_cols=("stock", "nez", "free", "reserved", "noissue", "qty"),
             keys: list[str] | None = None) -> pd.DataFrame:
    if grain == "month" or df.empty:
        return df
    keys = keys or []
    cal = db.q("SELECT m, quarter, CAST(year AS VARCHAR) AS year FROM cal")
    d = df.merge(cal, on="m")
    col = "quarter" if grain == "quarter" else "year"
    agg = {}
    for c in d.columns:
        if c in ("m", "label", "quarter", "year") or c in keys:
            continue
        if c in stock_cols:
            agg[c] = "last"
        elif c.endswith("_label"):
            agg[c] = "first"
        elif pd.api.types.is_numeric_dtype(d[c]):
            agg[c] = "sum"
    d = d.sort_values("m")
    g = d.groupby([col] + keys).agg({**agg, "m": "last"}).reset_index()
    g["label"] = g[col]
    return g.sort_values("m")


# ------------------------------------------------------------------------------------------
def deficit_positions(ctx: Ctx, asof: int | None = None, horizon: int | None = None) -> pd.DataFrame:
    """Риск дефицита на горизонте H мес.: потребность по плану vs свободный остаток + заказы со сроком в горизонте.

    Вероятность — скоринговая оценка (демо-методика): недостаточность покрытия, срок поставки
    относительно срока потребности и надёжность поставщика. Последствия — по критичности МТР.
    """
    asof = ctx.m2 if asof is None else asof
    H = horizon or int(cfg.get()["deficit_horizon_months"])
    w = ctx.where("v")
    df = db.q(f"""
    WITH need AS (
      SELECT position_id, SUM(plan_qty) need_qty,
             MIN(CASE WHEN plan_qty > 0 THEN m END) first_need_m
      FROM demand WHERE m BETWEEN {asof + 1} AND {asof + H} GROUP BY 1),
    s AS (SELECT position_id, qty, free_qty, price, unavailable_qty, reserved_qty_c FROM snap WHERE m = {asof}),
    po AS (
      SELECT position_id,
        SUM(CASE WHEN planned_delivery <= (SELECT month_end FROM cal WHERE m={asof + H}) THEN qty ELSE 0 END) po_in_h,
        SUM(qty) po_all,
        SUM(CASE WHEN planned_delivery < (SELECT month_end FROM cal WHERE m={asof}) THEN qty ELSE 0 END) po_overdue_qty
      FROM purchase_orders
      WHERE order_date <= (SELECT month_end FROM cal WHERE m={asof}) AND actual_delivery > (SELECT month_end FROM cal WHERE m={asof})
      GROUP BY 1),
    hist AS (SELECT position_id, SUM(unmet_value) unmet_12m FROM shortages WHERE m BETWEEN {asof - 11} AND {asof} GROUP BY 1)
    SELECT v.*, n.need_qty, n.first_need_m, COALESCE(s.qty,0) qty, COALESCE(s.free_qty,0) free_qty,
           COALESCE(s.unavailable_qty,0) unavailable_qty, COALESCE(s.price, 0) price,
           COALESCE(po.po_in_h,0) po_in_h, COALESCE(po.po_all,0) po_all, COALESCE(po.po_overdue_qty,0) po_overdue_qty,
           COALESCE(h.unmet_12m,0) unmet_12m, sp.base_reliability
    FROM need n JOIN v_pos v USING (position_id)
    LEFT JOIN s USING (position_id) LEFT JOIN po USING (position_id) LEFT JOIN hist h USING (position_id)
    LEFT JOIN suppliers sp ON sp.supplier_id = v.supplier_id
    WHERE n.need_qty > 0 AND v.on_balance AND {w}""")
    if df.empty:
        df["shortage_value"] = []
        df["crit_shortage_value"] = []
        return df
    price_fallback = db.q("SELECT position_id, price FROM snap WHERE m = (SELECT max(m) FROM snap)").set_index("position_id")["price"]
    df["price"] = np.where(df.price > 0, df.price, df.position_id.map(price_fallback).fillna(0))
    df["need_qty"] = np.where(df.unit == "шт", np.round(df.need_qty + 1e-9), df.need_qty)
    df["supply_qty"] = df.free_qty + df.po_in_h
    df["shortage_qty"] = (df.need_qty - df.supply_qty).clip(lower=0)
    df = df[df.shortage_qty > 0.05].copy()
    df["shortage_value"] = df.shortage_qty * df.price
    df["coverage_ratio"] = (df.supply_qty / df.need_qty).clip(upper=1)
    df["days_to_need"] = ((df.first_need_m.fillna(asof + 1) - asof) * 30.4).round()
    df["lead_exceeds"] = df.lead_days > df.days_to_need
    rel = df.base_reliability.fillna(0.9)
    df["probability"] = (0.55 * (1 - df.coverage_ratio) + 0.3 * df.lead_exceeds.astype(float) + 0.15 * (1 - rel)).clip(0, 1).round(2)
    df["consequence"] = df.criticality.map({"A — критичный": 3, "B — важный": 2}).fillna(1)
    df["risk_score"] = (df.probability * df.consequence * (1 + 0.5 * (df.days_to_need <= 31))).round(2)
    df["crit_shortage_value"] = np.where(df.criticality == "A — критичный", df.shortage_value, 0.0)
    df["unavailable_blocking"] = df.unavailable_qty > 0
    return df


def positions_at(ctx: Ctx, extra: str = "1=1", order: str = "value DESC", limit: int = 200, asof: int | None = None) -> pd.DataFrame:
    """Детализация до номенклатурной позиции на дату среза."""
    asof = ctx.m2 if asof is None else asof
    return db.q(f"""
    SELECT position_id, company_name, warehouse_name, direction_name, program, service_name, mclass, nsi_code,
           material_name, criticality, demand_type, replenishment_policy, project_name, project_status,
           qty, unit, price, value, free_value, reserved_value, unavailable_value, nez_value,
           days_no_issue, age_days, fut_need, last_receipt_date, last_issue_date, flag_nvi, flag_nli, flag_nr, flag_vr
    FROM snap WHERE on_balance AND m = {asof} AND qty > 0 AND {ctx.where()} AND ({extra})
    ORDER BY {order} LIMIT {int(limit)}""")


def pareto(df: pd.DataFrame, value_col: str, label_col: str) -> dict:
    d = df[[label_col, value_col]].copy()
    d = d[d[value_col] > 0].sort_values(value_col, ascending=False)
    tot = d[value_col].sum()
    if tot <= 0:
        return {"categories": [], "values": [], "cum_share": [], "thresholds": {}}
    d["cum"] = d[value_col].cumsum() / tot * 100
    th = {}
    for t in (50, 80, 90):
        th[str(t)] = int((d["cum"] < t).sum() + 1)
    return {"categories": d[label_col].tolist(), "values": d[value_col].round(0).tolist(),
            "cum_share": d["cum"].round(1).tolist(), "thresholds": th, "n_total": int(len(d))}


def safe_div(a, b):
    try:
        if b is None or b == 0 or (isinstance(b, float) and math.isnan(b)):
            return None
        return a / b
    except Exception:
        return None
