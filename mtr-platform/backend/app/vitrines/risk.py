"""Витрины 12–15: критический ЗИП и надёжность, потребность/прогноз/покрытие, дефициты, закупки."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import db, engine, forecast
from .. import settings as cfg
from ..filters import Ctx
from .common import (band, bar, col, control, days, heatmap, kpi, line, opt, pct, rub, scatter, section, table)


def qty_matrix(ctx: Ctx, extra: str, m_to: int) -> tuple[pd.DataFrame, np.ndarray]:
    """Помесячное потребление (кол-во) по позициям m=1..m_to — только данные до даты среза."""
    pos = db.q(f"SELECT DISTINCT position_id FROM snap WHERE m={m_to} AND on_balance AND {ctx.where()} AND ({extra})")
    if pos.empty:
        return pos, np.zeros((0, m_to))
    mv = db.q(f"""SELECT position_id, m, SUM(qty) q FROM movements WHERE mtype='Потребление' AND m BETWEEN 1 AND {m_to}
                 AND position_id IN (SELECT position_id FROM snap WHERE m={m_to} AND on_balance AND {ctx.where()} AND ({extra})) GROUP BY 1,2""")
    idx = {p: i for i, p in enumerate(pos.position_id)}
    M = np.zeros((len(pos), m_to))
    for r in mv.itertuples():
        M[idx[r.position_id], r.m - 1] = r.q
    return pos, M


def position_backtest(M: np.ndarray, start: int = 12, methods=None) -> pd.DataFrame:
    methods = methods or list(forecast.METHODS)
    if M.shape[0] == 0 or M.shape[1] <= start:
        return pd.DataFrame()
    abs_err = {m: 0.0 for m in methods}
    sum_err = {m: 0.0 for m in methods}
    act = M[:, start:].sum()
    for row in M:
        for m in methods:
            f = forecast.one_step(row, m)[start:]
            e = f - row[start:]
            abs_err[m] += np.abs(e).sum()
            sum_err[m] += e.sum()
    return pd.DataFrame([dict(method=forecast.METHODS[m], key=m, wape=abs_err[m] / act * 100 if act else None,
                              bias=sum_err[m] / act * 100 if act else None) for m in methods])


# ======================================================================================
def zip_table(ctx: Ctx) -> pd.DataFrame:
    sl = cfg.get()["zip"]["service_level"]
    extra = "demand_type = 'Нерегулярный' AND criticality IN ('A — критичный','B — важный')"
    pos, M = qty_matrix(ctx, extra, ctx.m2)
    if pos.empty:
        return pd.DataFrame()
    info = db.q(f"""
    WITH po AS (SELECT position_id, SUM(qty) q FROM purchase_orders WHERE order_date <= (SELECT month_end FROM cal WHERE m={ctx.m2})
                AND actual_delivery > (SELECT month_end FROM cal WHERE m={ctx.m2}) GROUP BY 1)
    SELECT s.position_id, s.company_id, s.company_name, s.material_name, s.nsi_code, s.mclass, s.criticality, s.equipment_model, s.lead_days,
           s.qty, s.free_qty, s.reserved_qty_c, s.unavailable_qty, s.price, s.value, s.repairable, s.replenishment_policy, COALESCE(po.q,0) po_q
    FROM snap s LEFT JOIN po USING (position_id) WHERE s.m={ctx.m2} AND {extra} AND s.on_balance AND {ctx.where('s')}""")
    eq = db.q("SELECT company_id, equipment_model, failure_rate_year, mtbf_hours, mttr_hours, units FROM equipment")
    rows = []
    for i, pid in enumerate(pos.position_id):
        y = M[i]
        cls = forecast.classify(y)
        meth = forecast.recommended_method(cls) if cls != "Нет спроса" else "tsb"
        lam = forecast.next_level(y, meth) if cls != "Нет спроса" else 0.0
        rows.append((pid, cls, forecast.METHODS[meth], lam, int((y > 0).sum()), float(y.sum())))
    f = pd.DataFrame(rows, columns=["position_id", "demand_class", "method", "lambda_month", "months_with_demand", "qty_hist"])
    d = info.merge(f, on="position_id").merge(eq, on=["company_id", "equipment_model"], how="left")
    d["lead_m"] = d.lead_days / 30.4
    d["required"] = [max(forecast.poisson_quantile(l * L, sl), 1 if c == "A — критичный" else 0) for l, L, c in zip(d.lambda_month, d.lead_m, d.criticality)]
    d["available"] = d.free_qty + d.reserved_qty_c + d.po_q
    d["gap"] = d.required - d.available
    d["risk_value"] = d.gap.clip(lower=0) * d.price
    d["excess_qty"] = (-d.gap).clip(lower=0)
    d["excess_value"] = d.excess_qty * d.price
    d["status"] = np.where(d.gap > 0, "Риск отсутствия ЗИП", np.where(d.excess_qty >= 2, "Избыток с учётом надёжности", "Норма"))
    return d


def v12(ctx: Ctx, opts: dict) -> dict:
    sl = cfg.get()["zip"]["service_level"]
    d = zip_table(ctx)
    if d.empty:
        return dict(kpis=[], sections=[section("empty", "what", "Нет позиций ЗИП в периметре", None)])
    crit = d[d.criticality == "A — критичный"]
    kpis = [kpi("crit", "Критический ЗИП (A)", crit.value.sum(), sub=f"{len(crit)} позиций"),
            kpi("all", "ЗИП A+B в анализе", d.value.sum(), sub=f"{len(d)} позиций"),
            kpi("risk", "Риск отсутствия ЗИП", d.risk_value.sum(), hib=False, sub=f"{int((d.gap > 0).sum())} позиций"),
            kpi("excess", "Избыток с учётом надёжности", d.excess_value.sum(), note="Оптимизация — только после технического согласования"),
            kpi("sl", "Целевой уровень обслуживания", sl * 100, "pct", note="Настраиваемый параметр (демо)")]
    sec = []
    byeq = d.assign(eqm=d.equipment_model.fillna("Без привязки к оборудованию")).groupby("eqm").agg(v=("value", "sum"), n=("position_id", "count"),
                                                                                                      risk=("risk_value", "sum")).reset_index().sort_values("v", ascending=False)
    sec.append(section("byeq", "what", "Структура ЗИП по оборудованию", "Стоимость запаса и риск отсутствия по моделям оборудования",
                       chart=bar(byeq.eqm.tolist(), [dict(name="Запас ЗИП", data=byeq.v.tolist()), dict(name="Риск отсутствия", data=byeq.risk.tolist(), color="bad")])))
    eq = db.q(f"""SELECT e.*, c.company_name FROM equipment e JOIN companies c USING (company_id) WHERE {ctx.with_filters(**{k: None for k in ctx.filters if k not in ('company','segment','ownership')}).where('c')}""")
    sec.append(section("eq", "where", "Надёжность оборудования (данные ТОиР, демо)", "Интенсивность отказов, MTBF, MTTR",
                       table=table(eq.sort_values("failure_rate_year", ascending=False), [col("company_name", "Общество"), col("equipment_name", "Оборудование"),
                                   col("criticality", "Критичность"), col("failure_rate_year", "Отказов в год", "num"), col("mtbf_hours", "MTBF, ч", "int"),
                                   col("mttr_hours", "MTTR, ч", "int")])))
    sec.append(section("req", "why", f"Потребность в ЗИП по надёжности: уровень обслуживания {pct(sl * 100, 0)}",
                       "λ — прогноз интенсивности потребления (метод по классу спроса: TSB для прерывистого — учитывает устаревание спроса и показал наименьшее смещение на истории; SES для регулярного); "
                       "требуемый запас — квантиль Пуассона спроса за срок поставки; для критичных — не менее 1",
                       table=table(d.sort_values(["gap", "price"], ascending=[False, False]), [
                           col("company_name", "Общество"), col("material_name", "ЗИП"), col("criticality", "Критичн."), col("demand_class", "Класс спроса"),
                           col("method", "Метод"), col("lambda_month", "λ, ед./мес.", "num"), col("lead_days", "Срок поставки, дн.", "int"),
                           col("required", "Требуется", "int"), col("available", "Доступно (вкл. заказы)", "num"), col("gap", "Разрыв", "num"),
                           col("mtbf_hours", "MTBF, ч", "int"), col("mttr_hours", "MTTR, ч", "int"), col("status", "Статус", "status")],
                           row_key="position_id"), span=2))
    risk = d[d.gap > 0].sort_values("risk_value", ascending=False)
    pts = [dict(name=f"{r.material_name} · {r.company_name}", x=r.lead_days, y=r.gap, size=r.risk_value, group=r.criticality) for r in risk.itertuples()]
    sec.append(section("risk", "risk", f"Риски отсутствия запасных частей: {len(risk)} позиций, {rub(risk.risk_value.sum())}",
                       "X — срок поставки; Y — недостающее количество; размер — стоимость; длительный срок поставки повышает последствия",
                       chart=scatter(pts, "Срок поставки, дн.", "Недостаёт, ед.", "days", "num", "Стоимость", groups=["A — критичный", "B — важный"])))
    pos, M = qty_matrix(ctx, "demand_type = 'Нерегулярный'", ctx.m2)
    bt = position_backtest(M[:600], start=12)
    if len(bt):
        best = bt.sort_values("wape").iloc[0]
        sec.append(section("bt", "why", f"Проверка моделей нерегулярного спроса на истории: лучший метод — {best.method}",
                           "Rolling origin, прогноз на 1 мес. только по данным до месяца прогноза; WAPE по позициям (до 600)",
                           chart=bar(bt.method.tolist(), [dict(name="WAPE, %", data=bt.wape.round(1).tolist())], unit="pct"),
                           table=table(bt, [col("method", "Метод"), col("wape", "WAPE, %", "pct"), col("bias", "Смещение, %", "pct")])))
    ex = d[d.status == "Избыток с учётом надёжности"].sort_values("excess_value", ascending=False)
    sec.append(section("excess", "action", f"Избыточные запасы ЗИП с учётом надёжности: {rub(ex.excess_value.sum())}",
                       "Решение об оптимизации — только с техническим согласованием (учёт производственных последствий, MTTR, критичности)",
                       table=table(ex, [col("company_name", "Общество"), col("material_name", "ЗИП"), col("criticality", "Критичн."),
                                        col("required", "Требуется", "int"), col("available", "Доступно", "num"), col("excess_value", "Избыток", "money"),
                                        col("repairable", "Ремонтопригоден", "status")], row_key="position_id", total=True), span=2))
    return dict(kpis=kpis, sections=sec)


# ======================================================================================
def v13(ctx: Ctx, opts: dict) -> dict:
    dtp = opt(opts, "dtype", "all")
    c = ctx if dtp == "all" else ctx.with_filters(demand_type=[dtp])
    k = engine.kpis(c)
    w = c.where("d")
    pv = db.q(f"""SELECT d.m, SUM(d.plan_qty * s.price) plan, SUM(d.plan_init_qty * s.price) plan_init FROM v_dem d JOIN snapshot s ON s.position_id=d.position_id AND s.m=d.m
                 WHERE d.on_balance AND d.m BETWEEN {max(1, c.m2 - 23)} AND {c.m2} AND {w} GROUP BY 1 ORDER BY 1""")
    s = engine.series(c, [], max(1, c.m2 - 23), c.m2)
    s = s.merge(pv, on="m", how="left")
    hz = int(opt(opts, "h", "6"))
    sec = []
    sec.append(section("pf", "what", f"План vs факт потребления: план превышает факт на {pct(k['plan_bias_pct'])}",
                       "План — оперативная версия на месяц; первоначальный годовой план — для оценки изменения потребности",
                       chart=line(s.label.tolist(), [dict(name="Факт потребления", data=s.consumption.tolist()), dict(name="План (оперативный)", data=s.plan.tolist(), dashed=True),
                                                     dict(name="План (первоначальный)", data=s.plan_init.tolist(), dashed=True, muted=True)]),
                       controls=[control("dtype", "Тип спроса", [("all", "Все"), ("Регулярный", "Регулярный"), ("Нерегулярный", "Нерегулярный"), ("Проектный", "Проектный")], dtp)],
                       span=2))
    bs = engine.aggregate(c, ["service"], parts=("mov", "plan"))
    bs = bs[bs.consumption > 0].sort_values("plan_bias_pct", ascending=False)
    sec.append(section("bias", "where", "Систематическое завышение/занижение потребности по службам", "(План − Факт) / Факт за период",
                       chart=bar(bs.service_label.tolist(), [dict(name="Отклонение плана, %", data=bs.plan_bias_pct.round(1).tolist(), signed=True, invert=True)], unit="pct", horizontal=True),
                       table=table(bs, [col("service_label", "Служба"), col("plan_value", "План", "money"), col("consumption", "Факт", "money"),
                                        col("plan_bias_pct", "Отклонение", "pct")])))
    acc = []
    for dt_ in ["Регулярный", "Нерегулярный", "Проектный"]:
        if dtp != "all" and dt_ != dtp:
            continue
        pos, M = qty_matrix(ctx.with_filters(demand_type=[dt_]), "1=1", c.m2)
        M = M[:500]
        bt = position_backtest(M, start=12)
        if len(bt):
            if len(pos):
                ids = ",".join(f"'{p}'" for p in pos.position_id[:500])
                pl = db.q(f"""SELECT d.position_id, d.m, d.plan_qty FROM demand d WHERE d.position_id IN ({ids}) AND d.m BETWEEN 13 AND {c.m2}""")
                act = M[:, 12:]
                P = np.zeros_like(act)
                ix = {p: i for i, p in enumerate(pos.position_id[:500])}
                for r in pl.itertuples():
                    P[ix[r.position_id], r.m - 13] = r.plan_qty
                if act.sum() > 0:
                    bt = pd.concat([bt, pd.DataFrame([dict(method="План потребности (оперативный)", key="plan", wape=np.abs(P - act).sum() / act.sum() * 100,
                                                           bias=(P - act).sum() / act.sum() * 100)])])
            bt["demand_type"] = dt_
            acc.append(bt)
    if acc:
        A = pd.concat(acc, ignore_index=True)
        best_idx = set(A.groupby("demand_type").wape.idxmin().dropna().astype(int)) if A.wape.notna().any() else set()
        A["best"] = ["Лучший" if i in best_idx else "" for i in A.index]
        sec.append(section("acc", "why", "Точность прогнозирования: методы против базовых и против плана",
                           "Историческая проверка без использования будущих данных (rolling origin, горизонт 1 мес., позиции до 500 на тип спроса)",
                           table=table(A, [col("demand_type", "Тип спроса"), col("method", "Метод"), col("wape", "WAPE, %", "pct"), col("bias", "Смещение, %", "pct"),
                                           col("best", "", "status")]), span=2))
    # прогноз остатка
    hist = engine.series(c, [], 1, c.m2)
    y = hist.consumption.to_numpy()
    meth = "ses"
    lvl = forecast.next_level(y, meth)
    sig = forecast.residual_sigma(y, meth)
    po = db.q(f"""SELECT date_trunc('month', planned_delivery) mm, SUM(po_value) v FROM v_po WHERE currency='RUB' AND order_date <= (SELECT month_end FROM cal WHERE m={c.m2})
                 AND actual_delivery > (SELECT month_end FROM cal WHERE m={c.m2}) AND {c.where()} GROUP BY 1""")
    cal = db.q("SELECT m, month_start FROM cal")
    po["mm"] = pd.to_datetime(po.mm).dt.normalize()
    cal["month_start"] = pd.to_datetime(cal.month_start).dt.normalize()
    po = po.merge(cal, left_on="mm", right_on="month_start", how="left")
    po["m"] = po.m.fillna(c.m2 + 1).clip(lower=c.m2 + 1)
    arr = po.groupby("m").v.sum()
    rec_rate = float(hist.receipts.tail(12).mean())
    S_only = S_rr = float(hist.stock.iloc[-1])
    xs, mid, only, lo, hi, recs = [], [], [], [], [], []
    for i in range(1, hz + 1):
        m = c.m2 + i
        po_m = float(arr.get(m, 0.0))
        S_only = max(0.0, S_only + po_m - lvl)
        S_rr = max(0.0, S_rr + max(po_m, rec_rate) - lvl)
        xs.append(db.month_label(m))
        mid.append(S_rr)
        only.append(S_only)
        lo.append(max(0.0, S_rr - 1.2816 * sig * np.sqrt(i)))
        hi.append(S_rr + 1.2816 * sig * np.sqrt(i))
        recs.append(max(po_m, rec_rate))
    sec.append(section("proj", "risk", f"Прогноз остатка на {hz} мес. при сохранении текущей ситуации: {rub(mid[-1])} (нижняя оценка {rub(only[-1])})",
                       f"Основная оценка: остаток + поступления (не меньше среднего темпа за 12 мес. {rub(rec_rate)}/мес. и не меньше открытых заказов) − прогноз потребления (SES); "
                       "интервал P10–P90 по ошибкам прогноза потребления. Нижняя оценка — только уже размещённые заказы.",
                       chart=band(xs, [dict(name="Прогноз остатка (текущий темп поступлений)", data=mid), dict(name="Нижняя оценка: только открытые заказы", data=only, dashed=True),
                                       dict(name="Поступления в прогнозе", data=recs, type="bar", muted=True)], lo, hi),
                       controls=[control("h", "Горизонт", [("3", "3 мес."), ("6", "6 мес."), ("12", "12 мес.")], str(hz))]))
    cov = db.q(f"""
    WITH po AS (SELECT position_id, SUM(qty) q FROM purchase_orders WHERE order_date <= (SELECT month_end FROM cal WHERE m={c.m2})
                AND actual_delivery > (SELECT month_end FROM cal WHERE m={c.m2}) GROUP BY 1)
    SELECT s.position_id, company_name, material_name, demand_type, qty, free_qty, reserved_qty_c, COALESCE(po.q,0) po_q, fut_need_12, price,
           (free_qty + COALESCE(po.q,0)) / NULLIF(fut_need_12,0) cov_ratio,
           GREATEST(free_qty + COALESCE(po.q,0) - fut_need_12, 0) * price over_value,
           GREATEST(fut_need_12 - free_qty - COALESCE(po.q,0), 0) * price under_value
    FROM snap s LEFT JOIN po USING (position_id) WHERE s.m={c.m2} AND s.on_balance AND s.fut_need_12 > 0 AND {c.where('s')}""")
    over = cov[cov.cov_ratio > 1.5].sort_values("over_value", ascending=False)
    under = cov[cov.cov_ratio < 0.5].sort_values("under_value", ascending=False)
    kpis = [kpi("plan", "Плановая потребность за период", k["plan_value"]), kpi("fact", "Фактическое потребление", k["consumption"]),
            kpi("bias", "Отклонение плана от факта", k["plan_bias_pct"], "pct", hib=False),
            kpi("free", "Доступный (свободный) запас", k["free_end"]), kpi("res", "Резервы", k["reserved_end"]), kpi("po", "Будущие поступления (заказы)", k["open_po"]),
            kpi("over", "Избыточное покрытие (> 150% потребности 12 мес.)", over.over_value.sum(), hib=False),
            kpi("under", "Недостаточное покрытие (< 50%)", under.under_value.sum(), hib=False)]
    cc = [col("company_name", "Общество"), col("material_name", "МТР"), col("demand_type", "Спрос"), col("free_qty", "Свободно", "num"),
          col("po_q", "Заказано", "num"), col("fut_need_12", "Потребность 12 мес.", "num"), col("cov_ratio", "Покрытие, раз", "num")]
    sec.append(section("over", "action", f"Избыточное покрытие: {rub(over.over_value.sum())}", "Кандидаты на отмену заказов/сокращение пополнения",
                       table=table(over, cc + [col("over_value", "Излишек", "money")], row_key="position_id", total=True)))
    sec.append(section("under", "action", f"Недостаточное покрытие: {rub(under.under_value.sum())}", "Требуется подтверждение потребности и источника покрытия",
                       table=table(under, cc + [col("under_value", "Недостаёт", "money")], row_key="position_id", total=True)))
    return dict(kpis=kpis, sections=sec)


# ======================================================================================
def supplier_stats(ctx: Ctx) -> pd.DataFrame:
    return db.q(f"""SELECT po_supplier_id supplier_id, supplier_name, COUNT(*) n, SUM(po_value) value,
                   AVG(CASE WHEN actual_delivery <= planned_delivery THEN 1.0 ELSE 0.0 END) * 100 on_time,
                   AVG(date_diff('day', planned_delivery, actual_delivery)) avg_delay,
                   AVG(date_diff('day', order_date, actual_delivery)) avg_lead
                   FROM v_po WHERE actual_delivery BETWEEN (SELECT month_start FROM cal WHERE m={ctx.m2 - 11}) AND (SELECT month_end FROM cal WHERE m={ctx.m2})
                   AND {ctx.where()} GROUP BY 1,2 ORDER BY on_time""")


def v14(ctx: Ctx, opts: dict) -> dict:
    k = engine.kpis(ctx)
    d = engine.deficit_positions(ctx)
    sh = db.q(f"""SELECT sh.m, SUM(sh.unmet_value) v, SUM(CASE WHEN v.criticality='A — критичный' THEN sh.unmet_value ELSE 0 END) vc FROM shortages sh
                 JOIN v_pos v USING (position_id) WHERE sh.m BETWEEN {max(1, ctx.m2 - 23)} AND {ctx.m2} AND {ctx.where('v')} GROUP BY 1 ORDER BY 1""")
    act_period = sh[sh.m.between(ctx.m1, ctx.m2)].v.sum() if len(sh) else 0
    long_ = d[d.lead_days > 180] if len(d) else d
    unav = d[d.unavailable_qty > 0] if len(d) else d
    kpis = [kpi("actual", "Фактические дефициты за период", act_period, hib=False, note="Неудовлетворённая потребность в момент отпуска"),
            kpi("proj", f"Прогнозируемый дефицит ({cfg.get()['deficit_horizon_months']} мес.)", k["deficit_value"], hib=False, sub=f"{len(d)} позиций"),
            kpi("crit", "в т.ч. критичные МТР", k["deficit_crit_value"], hib=False),
            kpi("long", "Длительный срок поставки (>180 дн.)", long_.shortage_value.sum() if len(long_) else 0, hib=False),
            kpi("overdue", "Просроченные поставки", k["overdue_po"], hib=False),
            kpi("unav", "Запас есть, но недоступен", k["unavail_end"], hib=False, note="Брак, ответхранение, блокировки")]
    sec = []
    sec.append(section("hist", "what", "Фактические дефициты по месяцам", "Стоимость неудовлетворённой потребности",
                       chart=bar([db.month_label(m) for m in sh.m], [dict(name="Критичные", data=sh.vc.tolist(), color="bad"),
                                                                     dict(name="Прочие", data=(sh.v - sh.vc).tolist())], stacked=True)))
    if len(d):
        by = d.groupby("company_name").agg(v=("shortage_value", "sum"), vc=("crit_shortage_value", "sum"), n=("position_id", "count")).reset_index().sort_values("v")
        sec.append(section("where", "where", "Прогнозируемые дефициты по обществам", None,
                           chart=bar(by.company_name.tolist(), [dict(name="Критичные", data=by.vc.tolist(), color="bad"),
                                                                dict(name="Прочие", data=(by.v - by.vc).tolist())], horizontal=True, stacked=True)))
        top_ = d.sort_values("risk_score", ascending=False).head(200)
        pts = [dict(name=f"{r.material_name} · {r.company_name}", x=r.days_to_need, y=r.probability, size=r.shortage_value, group=r.criticality,
                    position_id=r.position_id) for r in top_.itertuples()]
        sec.append(section("map", "risk", "Карта риска: вероятность × последствия × срок до потребности",
                           "Размер — стоимость непокрытой потребности; цвет — последствия (критичность). Вероятность — скоринг: покрытие, срок поставки, надёжность поставщика.",
                           chart=scatter(pts, "Дней до возникновения дефицита", "Вероятность (скоринг)", "days", "ratio", "Непокрыто",
                                         groups=["A — критичный", "B — важный", "C — стандартный"]), span=2))
        sec.append(section("list", "risk", "Позиции с недостаточным покрытием", "Критичные позиции без подтверждённого источника покрытия — в начале списка",
                           table=table(d.sort_values(["consequence", "risk_score"], ascending=False), [
                               col("company_name", "Общество"), col("material_name", "МТР"), col("criticality", "Критичность"), col("need_qty", "Потребность", "num"),
                               col("free_qty", "Свободно", "num"), col("po_in_h", "Заказы в горизонте", "num"), col("shortage_qty", "Недостаёт", "num"),
                               col("shortage_value", "Стоимость", "money"), col("lead_days", "Срок поставки", "int"), col("days_to_need", "Дней до дефицита", "int"),
                               col("probability", "Вероятн.", "num"), col("unavailable_qty", "Недоступно на складе", "num")], row_key="position_id", total=True), span=2))
    ss = supplier_stats(ctx)
    sec.append(section("supp", "why", "Отклонения графиков поставок по поставщикам (12 мес.)", "Доля поставок в срок и среднее отклонение",
                       chart=bar(ss.supplier_name.tolist(), [dict(name="Поставки в срок, %", data=ss.on_time.round(1).tolist())], unit="pct", horizontal=True),
                       table=table(ss, [col("supplier_name", "Поставщик"), col("n", "Поставок", "int"), col("value", "Стоимость", "money"), col("on_time", "В срок", "pct"),
                                        col("avg_delay", "Ср. отклонение, дн.", "num"), col("avg_lead", "Ср. срок, дн.", "num")])))
    od = db.q(f"""SELECT po_id, company_name, material_name, supplier_name, po_value, planned_delivery, criticality,
                 date_diff('day', planned_delivery, (SELECT month_end FROM cal WHERE m={ctx.m2})) overdue_days
                 FROM v_po WHERE currency='RUB' AND order_date <= (SELECT month_end FROM cal WHERE m={ctx.m2}) AND actual_delivery > (SELECT month_end FROM cal WHERE m={ctx.m2})
                 AND planned_delivery < (SELECT month_end FROM cal WHERE m={ctx.m2}) AND {ctx.where()} ORDER BY po_value DESC""")
    sec.append(section("overdue", "risk", f"Просроченные закупочные обязательства: {len(od)} заказов на {rub(od.po_value.sum())}", None,
                       table=table(od, [col("po_id", "Заказ"), col("company_name", "Общество"), col("material_name", "МТР"), col("supplier_name", "Поставщик"),
                                        col("criticality", "Критичность"), col("po_value", "Стоимость", "money"), col("overdue_days", "Просрочка, дн.", "int")], total=True)))
    from .v16 import redistribution_candidates
    rc = redistribution_candidates(ctx, only_deficit=True)
    sec.append(section("close", "action", f"Закрытие дефицита перераспределением: {rub(rc.value.sum() if len(rc) else 0)}",
                       "Межскладское и межобщественное перемещение свободного запаса без собственной потребности",
                       table=table(rc, [col("material_name", "МТР"), col("target_company", "Дефицит"), col("source_company", "Источник"), col("scope", "Тип"),
                                        col("qty", "Кол-во", "num"), col("value", "Стоимость", "money"), col("transit_days", "Срок, дн.", "int"),
                                        col("approval", "Согласование")], total=True) if len(rc) else None, span=2))
    return dict(kpis=kpis, sections=sec)


# ======================================================================================
def v15(ctx: Ctx, opts: dict) -> dict:
    a = ctx.m2
    me = f"(SELECT month_end FROM cal WHERE m={a})"
    w = ctx.where()
    po = db.q(f"""SELECT * FROM v_po WHERE {w} AND currency='RUB'""")
    me_d = db.q(f"SELECT month_end FROM cal WHERE m={a}").month_end.iloc[0]
    me_d = pd.Timestamp(me_d)
    for c_ in ("req_date", "order_date", "planned_delivery", "actual_delivery", "need_date"):
        po[c_] = pd.to_datetime(po[c_])
    open_ = po[(po.order_date <= me_d) & (po.actual_delivery > me_d)]
    reqs = po[(po.req_date <= me_d) & (po.order_date > me_d)]
    exp3 = open_[open_.planned_delivery <= me_d + pd.DateOffset(months=3)]
    overdue = open_[open_.planned_delivery < me_d]
    mism = open_[(open_.need_date - open_.planned_delivery).dt.days > 60]
    withfree = db.q(f"""
    SELECT p.po_id, p.company_name, p.material_name, p.po_value, p.order_date, s.free_qty, s.fut_need_3
    FROM v_po p JOIN cal ON p.order_date BETWEEN cal.month_start AND cal.month_end
    JOIN snap s ON s.position_id = p.position_id AND s.m = cal.m - 1
    WHERE cal.m BETWEEN {ctx.m1} AND {a} AND s.free_qty >= s.fut_need_3 AND s.fut_need_3 > 0 AND p.currency='RUB' AND {ctx.where('p')}
    ORDER BY p.po_value DESC""")
    changed = db.q(f"""SELECT p.po_id, p.company_name, p.project_name, p.project_status, p.material_name, p.po_value, p.order_date
                      FROM v_po p JOIN projects pr ON pr.project_id = p.project_id JOIN cal ON cal.m = pr.event_m
                      WHERE pr.status IN ('Перенесён','Отменён','Изменено техническое решение') AND p.order_date < cal.month_start
                      AND p.actual_delivery > cal.month_start AND {ctx.where('p')}""")
    cons = db.q(f"""SELECT proc_model, SUM(value) v FROM snap WHERE m={a} AND balance_ownership <> 'Собственный' AND {w} GROUP BY 1""")
    kpis = [kpi("reqs", "Открытые заявки (не размещены)", reqs.po_value.sum(), sub=f"{len(reqs)} шт."),
            kpi("open", "Открытые заказы", open_.po_value.sum(), sub=f"{len(open_)} шт."),
            kpi("exp3", "Ожидаемые поступления 3 мес.", exp3.po_value.sum()),
            kpi("overdue", "Просроченные поставки", overdue.po_value.sum(), hib=False),
            kpi("withfree", "Закупки при наличии свободного запаса", withfree.po_value.sum(), hib=False, note="Свободный остаток на начало месяца заказа ≥ потребности 3 мес."),
            kpi("changed", "Потребность изменилась после заказа", changed.po_value.sum(), hib=False),
            kpi("cons", "Консигнационный запас (вне баланса)", cons.v.sum(), note="Не входит в стоимость запасов на балансе")]
    sec = []
    open_["dm"] = open_.planned_delivery.dt.to_period("M").astype(str)
    pip = open_.groupby("dm").po_value.sum().head(18)
    sec.append(section("pipe", "what", f"Портфель открытых заказов по срокам поставки: {rub(open_.po_value.sum())}", None,
                       chart=bar(pip.index.tolist(), [dict(name="Плановые поступления", data=pip.tolist())]), span=2))
    mdl = db.q(f"""
    WITH d AS (SELECT po_proc_model model, COUNT(*) n, SUM(po_value) v, AVG(date_diff('day', order_date, actual_delivery)) lead,
               AVG(CASE WHEN actual_delivery <= planned_delivery THEN 1.0 ELSE 0 END)*100 on_time, AVG(date_diff('day', planned_delivery, actual_delivery)) delay
               FROM v_po WHERE actual_delivery BETWEEN (SELECT month_start FROM cal WHERE m={a - 11}) AND {me} AND {w} GROUP BY 1),
    st AS (SELECT proc_model model, SUM(value) stock, SUM(CASE WHEN m={a} THEN 1 ELSE 0 END) npos FROM snap WHERE m={a} AND {w} GROUP BY 1),
    c AS (SELECT proc_model model, SUM(value) cons12 FROM v_mov WHERE mtype='Потребление' AND m BETWEEN {a - 11} AND {a} AND {w} GROUP BY 1),
    mix AS (SELECT proc_model model, mclass, SUM(value) v, ROW_NUMBER() OVER (PARTITION BY proc_model ORDER BY SUM(value) DESC) rn FROM snap WHERE m={a} AND {w} GROUP BY 1,2)
    SELECT d.*, st.stock, c.cons12, st.stock / NULLIF(c.cons12/12, 0) coverage, mix.mclass top_class
    FROM d LEFT JOIN st USING (model) LEFT JOIN c USING (model) LEFT JOIN mix ON mix.model = d.model AND mix.rn = 1""")
    fin = cfg.get()["finance"]
    mdl["tco_holding"] = mdl.stock * (fin["cost_of_capital"] + fin["storage_rate"] + fin["obsolescence_rate"])
    sec.append(section("models", "why", "Сравнение закупочных моделей", "Модели применяются к разным классам МТР — прямое сравнение без сопоставимых условий некорректно. "
                       "Лучшая модель не объявляется.",
                       table=table(mdl, [col("model", "Модель"), col("n", "Поставок 12 мес.", "int"), col("v", "Стоимость", "money"), col("lead", "Ср. срок, дн.", "num"),
                                         col("on_time", "В срок", "pct"), col("delay", "Ср. отклонение, дн.", "num"), col("stock", "Запас", "money"),
                                         col("coverage", "Покрытие, мес.", "num"), col("tco_holding", "Стоимость владения (год)", "money"),
                                         col("top_class", "Основной класс МТР")]), span=2))
    gap = (open_.need_date - open_.planned_delivery).dt.days
    bins = [-10000, -30, 0, 30, 90, 180, 10000]
    lbl = ["Позже потребности > 30 дн.", "Позже до 30 дн.", "Раньше до 30 дн.", "Раньше 30–90 дн.", "Раньше 90–180 дн.", "Раньше > 180 дн."]
    hb = open_.assign(b=pd.cut(gap, bins, labels=lbl)).groupby("b", observed=False).po_value.sum().reindex(lbl).fillna(0)
    sec.append(section("early", "why", f"Несоответствие сроков поставки срокам потребления: досрочно > 60 дн. — {rub(mism.po_value.sum())}",
                       "Разница между датой потребности и плановой датой поставки по открытым заказам", chart=bar(lbl, [dict(name="Открытые заказы", data=hb.tolist())])))
    sec.append(section("free", "risk", f"Закупки при наличии свободного запаса за период: {rub(withfree.po_value.sum())}", None,
                       table=table(withfree, [col("po_id", "Заказ"), col("company_name", "Общество"), col("material_name", "МТР"), col("order_date", "Дата заказа", "date"),
                                              col("po_value", "Стоимость", "money"), col("free_qty", "Свободно на дату", "num"), col("fut_need_3", "Потребность 3 мес.", "num")], total=True)))
    sec.append(section("changed", "risk", f"Изменение потребности после размещения заказа: {rub(changed.po_value.sum())}", "Проект перенесён/отменён/изменено тех. решение после даты заказа",
                       table=table(changed, [col("po_id", "Заказ"), col("company_name", "Общество"), col("project_name", "Проект"), col("project_status", "Статус", "status"),
                                             col("material_name", "МТР"), col("po_value", "Стоимость", "money")], total=True)))
    cand = db.q(f"""
    WITH op AS (SELECT po_id, position_id, company_name, material_name, project_status, po_value, po_qty, planned_delivery FROM v_po
                WHERE currency='RUB' AND order_date <= {me} AND actual_delivery > {me} AND {w}),
    s AS (SELECT position_id, free_qty, fut_need_12 FROM snap WHERE m={a})
    SELECT op.*, s.free_qty, s.fut_need_12,
      CASE WHEN op.project_status IN ('Перенесён','Отменён') THEN 'Работы перенесены/отменены'
           ELSE 'Свободный остаток покрывает потребность 12 мес.' END reason
    FROM op JOIN s USING (position_id) WHERE op.project_status IN ('Перенесён','Отменён') OR s.free_qty >= s.fut_need_12
    ORDER BY po_value DESC""")
    sec.append(section("cancel", "action", f"Кандидаты на отмену/перенос заказов: {rub(cand.po_value.sum())}",
                       "До решения проверить условия договора и штрафные санкции; решение — за закупками и инициатором",
                       table=table(cand, [col("po_id", "Заказ"), col("company_name", "Общество"), col("material_name", "МТР"), col("po_value", "Стоимость", "money"),
                                          col("planned_delivery", "Поставка", "date"), col("free_qty", "Свободно", "num"), col("fut_need_12", "Потребн. 12 мес.", "num"),
                                          col("reason", "Основание")], total=True), span=2))
    return dict(kpis=kpis, sections=sec)
