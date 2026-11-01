"""Витрины 1–5: пульт руководителя, уровень и динамика, оборачиваемость, НЭЗ, ТОП-10 и Парето."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import db, engine, insights
from .. import settings as cfg
from ..filters import DIMENSIONS, Ctx
from .common import (bar, clean, col, control, days, gantt, heatmap, kpi, line, opt, pareto_chart, pct, rub, scatter,
                     section, table, top, treemap, waterfall)

DIM_OPTS = [("company", "Общества"), ("dgroup", "CAPEX/OPEX/RevEx"), ("direction", "Направления"), ("program", "Программы"),
            ("service", "Технические службы"), ("mclass", "Классы МТР"), ("segment", "Бизнес-сегменты"), ("warehouse", "Склады")]


def _company_scope_where(ctx: Ctx, alias: str = "c") -> str:
    keep = {"company", "segment", "ownership"}
    w = ctx.with_filters(**{k: None for k in ctx.filters if k not in keep})
    return w.where(alias)


def _non_company_filters(ctx: Ctx) -> bool:
    return any(k not in ("company", "segment", "ownership") for k in ctx.filters)


def _realized_effect(ctx: Ctx) -> float:
    w = _company_scope_where(ctx, "c")
    d = db.q(f"""SELECT SUM(a.actual_effect) v FROM actions a JOIN companies c USING (company_id)
                WHERE a.status = 'Выполнено, эффект подтверждён' AND {w}""", cache=False)
    return float(d.v.iloc[0] or 0)


# ======================================================================================
def v01(ctx: Ctx, opts: dict) -> dict:
    k = engine.kpis(ctx)
    t = cfg.get()["targets"]
    m2 = ctx.m2
    s = engine.series(ctx, [], max(0, m2 - 24), m2)
    st = s.set_index("m").stock
    at = lambda m: float(st.get(m, np.nan)) if m >= 0 else None
    d_m, d_q, d_y = at(m2 - 1), at(m2 - 3), at(m2 - 12)
    fin = db.q(f"""SELECT SUM(current_assets) ca FROM finance f JOIN companies c USING (company_id) WHERE f.m={m2} AND {_company_scope_where(ctx)}""")
    ca = float(fin.ca.iloc[0] or 0)
    g = engine.aggregate(ctx, ["dgroup"], parts=("snap",)).set_index("dgroup")
    capex = float(g.stock_end.get("CAPEX", 0))
    opex = float(g.stock_end.get("OPEX", 0)) + float(g.stock_end.get("RevEx", 0))
    cr = ctx.cmp_range()
    kp = engine.kpis(ctx, *cr) if cr else {}
    eff = _realized_effect(ctx)
    year_growth = (k["stock_end"] / d_y - 1) * 100 if d_y else None
    checks = [
        ("Доля НЭЗ", k["nez_share"], t["nez_share_pct"], False),
        ("Оборачиваемость", k["turnover_days"], t["turnover_days"], False),
        ("Рост запасов за год", year_growth, t["stock_growth_pct_year"], False),
        ("Риск дефицита, млн ₽", k["deficit_value"] / 1e6, t["deficit_value_mln"], False),
    ]
    off = [c for c in checks if c[1] is not None and not np.isnan(c[1]) and c[1] > c[2]]
    kpis = [
        kpi("stock_end", "Стоимость запасов МТР", k["stock_end"], prev=kp.get("stock_end"), hib=False,
            sub=f"за мес. {rub(k['stock_end'] - d_m) if d_m else '—'} · за кв. {rub(k['stock_end'] - d_q) if d_q else '—'} · за год {rub(k['stock_end'] - d_y) if d_y else '—'}"),
        kpi("fin_share", "Доля в оборотных активах", k["stock_end"] / ca * 100 if ca else None, "pct",
            note="Финансовая база — оборотные активы обществ (демо). При фильтре по МТР/направлениям показатель отражает долю отфильтрованных запасов."
            if _non_company_filters(ctx) else "Финансовая база — оборотные активы обществ (демо)"),
        kpi("capex_opex", "CAPEX / OPEX+RevEx", capex, sub=f"OPEX+RevEx: {rub(opex)} · CAPEX {pct(capex / k['stock_end'] * 100 if k['stock_end'] else None)}"),
        kpi("nez_end", "НЭЗ", k["nez_end"], prev=kp.get("nez_end"), hib=False, sub=f"доля {pct(k['nez_share'])} при цели {pct(t['nez_share_pct'])}",
            target=None, status="bad" if k["nez_share"] > t["nez_share_pct"] else "ok"),
        kpi("turnover_days", "Оборачиваемость", k["turnover_days"], "days", prev=kp.get("turnover_days"), target=t["turnover_days"], hib=False,
            note=f"Расчёт: средний остаток / потребление × {ctx.days()} дн. (хронологическое среднее)"),
        kpi("noissue_end", f"Без потребления ≥ {cfg.get()['no_consumption_days']} дн.", k["noissue_end"], prev=kp.get("noissue_end"), hib=False,
            note="Включает страховой запас; не тождественно НЭЗ"),
        kpi("free_end", "Свободный / зарезервированный", k["free_end"], sub=f"резерв {rub(k['reserved_end'])} · недоступно {rub(k['unavail_end'])}"),
        kpi("deficit_value", "Потребность с риском дефицита", k["deficit_value"], hib=False, target=t["deficit_value_mln"] * 1e6,
            sub=f"в т.ч. критичные МТР {rub(k['deficit_crit_value'])}"),
        kpi("effect", "Подтверждённый эффект мероприятий", eff, sub="по реестру мероприятий (накопленно)", hib=True),
        kpi("targets", "Отклонение от целей", len(off), "count", sub=("; ".join(c[0] for c in off) or "все в пределах целей") + " (цели — демо)",
            status="bad" if off else "ok"),
    ]
    sections = []
    s24 = s[s.m > m2 - 24] if len(s) > 1 else s
    sections.append(section("dyn", "what", f"Запасы {('выросли' if k['stock_delta'] >= 0 else 'снизились')} на {rub(abs(k['stock_delta']))} "
                            f"({pct(k['stock_delta_pct'], sign=True)}) за {ctx.n_months} мес.; НЭЗ — {pct(k['nez_share'])} при цели {pct(t['nez_share_pct'])}",
                            "Динамика за 24 месяца: запасы на конец месяца, НЭЗ, свободный запас и потребление",
                            chart=line(s24.label.tolist(), [
                                dict(name="Запасы", data=s24.stock.tolist(), area=True),
                                dict(name="Свободный запас", data=s24.free.tolist()),
                                dict(name="НЭЗ", data=s24.nez.tolist(), color="bad"),
                                dict(name="Потребление за месяц", data=s24.consumption.tolist(), type="bar", muted=True)]),
                            span=2))
    to = engine.turnover_ltm(ctx, [], max(12, m2 - 23), m2)
    sections.append(section("turn", "what", f"Оборачиваемость (LTM): {days(to.turnover_days.iloc[-1] if len(to) else None)} при цели {t['turnover_days']:.0f} дн.",
                            "Скользящие 12 месяцев: средний остаток / потребление × дни",
                            chart=line(to.label.tolist(), [dict(name="Оборачиваемость, дн.", data=to.turnover_days.tolist())], unit="days",
                                       mark_line=dict(value=t["turnover_days"], label="Цель (демо)"))))
    dd = engine.aggregate(ctx, ["direction"], parts=("snap",)).sort_values("stock_end", ascending=True)
    dd = dd[dd.stock_end > 0]
    sections.append(section("struct", "where", f"Структура: крупнейшее направление — {dd.direction_label.iloc[-1] if len(dd) else '—'}",
                            "Запасы по направлениям формирования: эффективная часть и НЭЗ",
                            chart=bar(dd.direction_label.tolist(), [dict(name="Без признаков НЭЗ", data=(dd.stock_end - dd.nez_end).tolist()),
                                                                    dict(name="НЭЗ", data=dd.nez_end.tolist(), color="bad")],
                                      horizontal=True, stacked=True), drill={"dim": "direction"}))
    c = engine.aggregate(ctx, ["company"])
    grp = engine.kpis(ctx)
    metrics_hm = [("stock_delta_pct", "Δ запасов, %", "pct", False), ("nez_share", "Доля НЭЗ, %", "pct", False),
                  ("turnover_days", "Оборачиваемость, дн.", "days", False), ("coverage_months", "Покрытие, мес.", "months", False),
                  ("deficit_value", "Риск дефицита", "rub", False), ("overdue_po", "Просрочка поставок", "rub", False)]
    c = c.sort_values("stock_end", ascending=False)
    vals, labels = [], []
    for r in c.itertuples():
        rv, rl = [], []
        for mk, ml, u, hib in metrics_hm:
            v = getattr(r, mk)
            gv = grp.get(mk)
            if mk in ("deficit_value", "overdue_po"):
                base = (gv or 0) / max(1, len(c))
                score = np.clip((v - base) / base, -1, 1) if base else 0
            else:
                score = np.clip((v - gv) / abs(gv), -1, 1) if (gv and v is not None and not np.isnan(v)) else None
            rv.append(None if score is None or (isinstance(score, float) and np.isnan(score)) else float(score))
            rl.append(rub(v) if u == "rub" else (days(v) if u == "days" else (pct(v) if u == "pct" else (f"{v:.1f}" if v == v else "—"))))
        vals.append(rv)
        labels.append(rl)
    sections.append(section("heat", "where", "Тепловая карта обществ: отклонение от среднего по группе",
                            "Цвет — относительное отклонение от группового значения (красный — хуже группы); подпись — фактическое значение",
                            chart=heatmap([m[1] for m in metrics_hm], c.company_label.tolist(), vals, labels=labels, diverging=True, unit="score"),
                            drill={"dim": "company", "keys": c.company.tolist()}, span=2))
    c["problem"] = c.nez_end + c.deficit_value
    tp = c.sort_values("problem", ascending=False).head(10)
    sections.append(section("top_problem", "where", "ТОП-10 проблемных обществ",
                            "Проблемная сумма = НЭЗ + потребность с риском дефицита (обе части раскрыты отдельно)",
                            table=table(tp, [col("company_label", "Общество"), col("stock_end", "Запасы", "money"), col("nez_end", "НЭЗ", "money"),
                                             col("nez_share", "Доля НЭЗ", "pct"), col("deficit_value", "Риск дефицита", "money"),
                                             col("turnover_days", "Оборач.", "days"), col("problem", "Проблемная сумма", "money")],
                                        drill={"dim": "company", "key": "company"})))
    cm = engine.aggregate(ctx, ["company", "mclass"], parts=("snap", "mov", "nez"))
    neg = cm.sort_values("stock_delta", ascending=False).head(10)
    pos_ = cm.sort_values("stock_delta", ascending=True).head(10)
    cols_chg = [col("company_label", "Общество"), col("mclass_label", "Класс МТР"), col("stock_delta", "Δ запасов", "money"),
                col("nez_delta", "Δ НЭЗ", "money"), col("consumption", "Потребление", "money")]
    sections.append(section("neg", "where", "ТОП-10 негативных изменений (рост запасов)", "Общество × класс МТР за период",
                            table=table(neg, cols_chg, drill={"dim": "company", "key": "company"})))
    sections.append(section("pos", "where", "ТОП-10 положительных изменений (снижение запасов)", "Общество × класс МТР за период",
                            table=table(pos_, cols_chg, drill={"dim": "company", "key": "company"})))
    dfp = engine.deficit_positions(ctx).sort_values("shortage_value", ascending=False).head(150)
    pts = [dict(name=f"{r.material_name} · {r.company_name}", x=r.days_to_need, y=r.probability, size=r.shortage_value,
                group=r.criticality, position_id=r.position_id) for r in dfp.itertuples()]
    sections.append(section("riskmap", "risk", f"Карта критических рисков: {int((dfp.criticality == 'A — критичный').sum())} критичных позиций с риском дефицита",
                            "Вероятность дефицита (скоринг) × срок до потребности; размер — стоимость непокрытой потребности; цвет — критичность",
                            chart=scatter(pts, "Дней до потребности", "Вероятность дефицита (скоринг 0–1)", "days", "ratio", "Непокрытая потребность",
                                          groups=["A — критичный", "B — важный", "C — стандартный"])))
    ins = insights.compute(ctx)
    top_i = [i for i in ins if i["type"] != "engine_error"][:10]
    df_i = pd.DataFrame([dict(title=i["title"], cause=f"{i['cause']} [{i['cause_status']}]", value=i["value_at_risk"], action=i["action"],
                              owner=i["owner"], decision="Да" if i["decision_needed"] else "Нет", kind=i["kind"], id=i["id"]) for i in top_i])
    sections.append(section("decide", "action", f"Что требует решения руководителя: {sum(1 for i in top_i if i['decision_needed'])} из {len(top_i)} приоритетных проблем",
                            "Сформировано аналитическим механизмом; причины — со статусом достоверности. Решения принимаются ответственными по матрице полномочий.",
                            table=table(df_i, [col("title", "Проблема"), col("cause", "Причина / гипотеза"), col("value", "Сумма под риском", "money"),
                                               col("action", "Рекомендуемое действие"), col("owner", "Владелец (матрица полномочий)"),
                                               col("decision", "Нужно решение", "status")], row_key="id") if len(df_i) else None,
                            kind="decisions", span=2))
    return dict(kpis=kpis, sections=sections)


# ======================================================================================
def v02(ctx: Ctx, opts: dict) -> dict:
    k = engine.kpis(ctx)
    cr = ctx.cmp_range()
    kp = engine.kpis(ctx, *cr) if cr else {}
    kpis = [kpi("stock_start", "Запасы на начало", k["stock_start"]), kpi("stock_end", "Запасы на конец", k["stock_end"], prev=kp.get("stock_end"), hib=False),
            kpi("stock_delta", "Изменение", k["stock_delta"], sub=pct(k["stock_delta_pct"], sign=True), hib=False),
            kpi("qty_driven_delta", "В т.ч. движение количества", k["qty_driven_delta"]),
            kpi("reval", "В т.ч. переоценка", k["reval"], note="Изменение цены, не физического объёма"),
            kpi("receipts", "Поступление", k["receipts"], prev=kp.get("receipts")), kpi("consumption", "Потребление", k["consumption"], prev=kp.get("consumption")),
            kpi("qty_end", "Номенклатурных позиций с остатком", k["n_items"], "count")]
    sec = []
    wf = [("Запасы на начало", k["stock_start"], "total"), ("Поступление", k["receipts"], "delta"), ("Возвраты", k["returns"], "delta"),
          ("Перемещения (приход)", k["tr_in"], "delta"), ("Потребление", -k["consumption"], "delta"),
          ("Перемещения (расход)", -k["tr_out"], "delta"), ("Реализация", -k["sales"], "delta"), ("Списание", -k["writeoff"], "delta"),
          ("Корректировки", k["adjust"], "delta"), ("Переоценка", k["reval"], "delta")]
    if abs(k["discrepancy"]) > 1:
        wf.append(("Расхождение учёта (контроль качества)", k["discrepancy"], "delta"))
    wf.append(("Запасы на конец", k["stock_end"], "total"))
    sec.append(section("wf", "what", f"Факторы изменения: {rub(k['stock_delta'])} = движение количества {rub(k['qty_driven_delta'])} + переоценка {rub(k['reval'])}"
                       + (f" + расхождение {rub(k['discrepancy'])}" if abs(k["discrepancy"]) > 1 else ""),
                       f"Сверка: начальный остаток + движения + переоценка = конечный остаток · {ctx.period_label()}",
                       chart=waterfall(wf), span=2,
                       note="Сверка выполняется по сумме фактов движения. Ненулевое «Расхождение учёта» означает остатки, не подтверждённые документами движения (см. контроль качества данных)."))
    s = engine.series(ctx, [], max(0, ctx.m1 - 12), ctx.m2)
    sg = engine.to_grain(s, ctx.grain)
    cur = sg[sg.m >= ctx.m1]
    ser = [dict(name="Запасы на конец периода", data=cur.stock.tolist(), area=True)]
    if ctx.grain == "month" and len(s) > 12:
        prev_map = s.set_index("m").stock
        ser.append(dict(name="Тот же месяц год назад", data=[prev_map.get(m - 12) for m in cur.m], dashed=True))
    sec.append(section("dyn", "what", f"Динамика запасов за {ctx.n_months} мес. ({ {'month': 'по месяцам', 'quarter': 'по кварталам', 'year': 'по годам'}[ctx.grain] })",
                       "Сравнение с аналогичным периодом прошлого года", chart=line(cur.label.tolist(), ser)))
    dim = opt(opts, "dim", "company")
    a = engine.aggregate(ctx, [dim], parts=("snap", "mov")).sort_values("stock_delta", ascending=False)
    sec.append(section("bydim", "where", f"Изменение запасов: {DIMENSIONS[dim][2].lower()}",
                       "Абсолютное и относительное изменение; переключите разрез",
                       chart=bar(a[f"{dim}_label"].tolist(), [dict(name="Изменение запасов", data=a.stock_delta.tolist(), signed=True)]),
                       table=table(a, [col(f"{dim}_label", DIMENSIONS[dim][2]), col("stock_start", "На начало", "money"), col("stock_end", "На конец", "money"),
                                       col("stock_delta", "Изменение", "money"), col("stock_delta_pct", "Изменение, %", "pct"),
                                       col("receipts", "Поступление", "money"), col("consumption", "Потребление", "money"), col("reval", "Переоценка", "money")],
                                   drill={"dim": dim, "key": dim}, total=True),
                       controls=[control("dim", "Разрез", DIM_OPTS, dim)], drill={"dim": dim}, span=2))
    sd = engine.series(ctx, ["dgroup"], ctx.m1, ctx.m2, flows=False)
    piv = sd.pivot_table(index="m", columns="dgroup_label", values="stock", aggfunc="sum").fillna(0)
    shares = piv.div(piv.sum(axis=1), axis=0) * 100
    sec.append(section("share", "where", "Изменение структуры запасов (доли CAPEX / OPEX / RevEx)", "100% — запасы на конец месяца",
                       chart=bar([db.month_label(m) for m in shares.index], [dict(name=c, data=shares[c].round(1).tolist()) for c in shares.columns],
                                 unit="pct", stacked=True)))
    fl = s[s.m >= ctx.m1]
    sec.append(section("flows", "why", "Поступление против потребления по месяцам",
                       "Положительное сальдо формирует прирост запасов", chart=bar(fl.label.tolist(), [
                           dict(name="Поступление", data=fl.receipts.tolist()), dict(name="Потребление", data=(-fl.consumption).tolist()),
                           dict(name="Сальдо", data=(fl.receipts - fl.consumption).tolist(), type="line")])))
    act = db.q(f"""SELECT a.m, SUM(a.activity_index * w.v) / SUM(w.v) idx FROM activity a
                  JOIN (SELECT company_id, SUM(value) v FROM snap WHERE m={ctx.m1 - 1} AND on_balance AND {ctx.where()} GROUP BY 1) w USING (company_id)
                  WHERE a.m BETWEEN {ctx.m1 - 1} AND {ctx.m2} GROUP BY 1 ORDER BY 1""")
    st_ = s.set_index("m").stock
    base = st_.get(ctx.m1 - 1, np.nan)
    if len(act) and base:
        a0 = act.idx.iloc[0]
        sec.append(section("act", "why", "Запасы относительно производственной активности (индекс, начало периода = 100)",
                           "Индекс активности — взвешенный по запасам обществ (демо). Совместная динамика не доказывает причинную связь.",
                           chart=line([db.month_label(m) for m in act.m], [
                               dict(name="Запасы", data=[st_.get(m, np.nan) / base * 100 for m in act.m]),
                               dict(name="Производственная активность", data=(act.idx / a0 * 100).tolist(), dashed=True)], unit="index")))
    s2 = engine.series(ctx, [], 1, ctx.m2)
    s2["net"] = s2.stock.diff()
    mu, sd_ = s2.net.mean(), s2.net.std()
    s2["z"] = (s2.net - mu) / (sd_ or 1)
    an = s2[s2.z.abs() > 2]
    sec.append(section("anom", "why", f"Нетипичные отклонения: {len(an)} мес. с изменением > 2σ",
                       "Помесячное изменение запасов за всю историю; аномалии — по z-оценке",
                       chart=bar(s2.label.tolist(), [dict(name="Изменение за месяц", data=s2.net.tolist(), signed=True,
                                                          highlight=[bool(x) for x in (s2.z.abs() > 2)])]),
                       table=table(an.assign(z=an.z.round(1)), [col("label", "Месяц"), col("net", "Изменение", "money"), col("z", "z-оценка", "num"),
                                                                col("receipts", "Поступление", "money"), col("reval", "Переоценка", "money")])))
    cm = engine.aggregate(ctx, ["company", "mclass"], parts=("snap", "mov", "po")).sort_values("stock_delta", ascending=False).head(15)
    cm["rec"] = np.where(cm.receipts > cm.consumption * 1.1, "Проверить обоснованность поступлений и открытые заказы",
                         np.where(cm.reval > cm.stock_delta * 0.5, "Рост в основном за счёт переоценки — действий по объёму не требуется", "Проверить структуру движения"))
    sec.append(section("act_tbl", "action", "Основные источники прироста и рекомендуемые проверки",
                       "Рекомендация формируется по соотношению поступлений, потребления и переоценки",
                       table=table(cm, [col("company_label", "Общество"), col("mclass_label", "Класс МТР"), col("stock_delta", "Прирост", "money"),
                                        col("receipts", "Поступление", "money"), col("consumption", "Потребление", "money"), col("reval", "Переоценка", "money"),
                                        col("open_po", "Открытые заказы", "money"), col("rec", "Рекомендация")], drill={"dim": "company", "key": "company"}),
                       span=2))
    return dict(kpis=kpis, sections=sec)


# ======================================================================================
def v03(ctx: Ctx, opts: dict) -> dict:
    k = engine.kpis(ctx)
    t = cfg.get()["targets"]
    cr = ctx.cmp_range()
    kp = engine.kpis(ctx, *cr) if cr else {}
    dim = opt(opts, "dim", "company")
    a = engine.aggregate(ctx, [dim], parts=("snap", "mov"))
    nocons = int((a.consumption <= 0).sum())
    kpis = [kpi("turnover_days", "Оборачиваемость", k["turnover_days"], "days", prev=kp.get("turnover_days"), target=t["turnover_days"], hib=False,
                note="Группа: Σ средних остатков / Σ потребления × дни (не среднее по обществам)"),
            kpi("stock_avg", "Средний остаток", k["stock_avg"], prev=kp.get("stock_avg"), hib=False,
                note="Хронологическое среднее по месячным срезам (среднедневные остатки в источнике отсутствуют)"),
            kpi("consumption", "Потребление за период", k["consumption"], prev=kp.get("consumption"), hib=True),
            kpi("coverage_months", "Покрытие запасом", k["coverage_months"], "months", prev=kp.get("coverage_months"), hib=False),
            kpi("holding_cost", "Стоимость владения (год)", k["holding_cost"], hib=False, note="Ставки — допущения демо; не является расходом P&L в полном объёме"),
            kpi("nocons", "Срезов без потребления", nocons, "count", sub="оборачиваемость не рассчитывается")]
    sec = []
    to = engine.turnover_ltm(ctx, ["dgroup"], max(12, ctx.m2 - 23), ctx.m2)
    tg = engine.turnover_ltm(ctx, [], max(12, ctx.m2 - 23), ctx.m2)
    ser = [dict(name="Группа (в периметре)", data=tg.turnover_days.tolist())]
    for g_, gg in to.groupby("dgroup_label"):
        ser.append(dict(name=g_, data=gg.set_index("m").reindex(tg.m).turnover_days.tolist(), dashed=True))
    sec.append(section("dyn", "what", f"Оборачиваемость {('ухудшилась' if (kp.get('turnover_days') or 0) < (k['turnover_days'] or 0) else 'улучшилась')}: "
                       f"{days(kp.get('turnover_days'))} → {days(k['turnover_days'])}", "LTM-оборачиваемость: группа и CAPEX/OPEX/RevEx",
                       chart=line(tg.label.tolist(), ser, unit="days", mark_line=dict(value=t["turnover_days"], label="Цель (демо)")), span=2))
    if cr:
        ap = engine.aggregate(ctx, [dim], cr[0], cr[1], parts=("snap", "mov"))[[dim, "turnover_days", "stock_avg", "consumption"]]
        a = a.merge(ap, on=dim, how="left", suffixes=("", "_prev"))
        a["turn_chg"] = a.turnover_days - a.turnover_days_prev
    else:
        a["turnover_days_prev"] = np.nan
        a["turn_chg"] = np.nan
    a["status"] = np.where(a.consumption > 0, "Рассчитано", "Нет потребления")
    a = a.sort_values("turnover_days", ascending=False, na_position="first")
    sec.append(section("cmp", "where", f"Сравнение: {DIMENSIONS[dim][2].lower()}", "Переключите разрез: общества, CAPEX/OPEX, службы, классы",
                       chart=bar(a[a.consumption > 0][f"{dim}_label"].tolist(), [dict(name="Оборачиваемость, дн.", data=a[a.consumption > 0].turnover_days.tolist())],
                                 unit="days", horizontal=True, mark_line=dict(value=t["turnover_days"], label="Цель")),
                       table=table(a, [col(f"{dim}_label", DIMENSIONS[dim][2]), col("stock_avg", "Средний остаток", "money"), col("consumption", "Потребление", "money"),
                                       col("turnover_days", "Оборач., дн.", "days"), col("turnover_days_prev", "Ранее, дн.", "days"),
                                       col("turn_chg", "Изменение, дн.", "num"), col("status", "Статус", "status")], drill={"dim": dim, "key": dim}),
                       controls=[control("dim", "Разрез", DIM_OPTS, dim)], span=2))
    r = a[a.turn_chg.notna()].sort_values("turn_chg")
    sec.append(section("rank", "where", "Рейтинг ускорения и замедления оборачиваемости", "Изменение к периоду сравнения, дней (минус — ускорение)",
                       chart=bar(r[f"{dim}_label"].tolist(), [dict(name="Изменение, дн.", data=r.turn_chg.tolist(), signed=True, invert=True)],
                                 unit="days", horizontal=True)))
    cm = engine.aggregate(ctx, ["company", "mclass"], parts=("snap", "mov"))
    cm = cm[cm.stock_avg > 0].sort_values("stock_avg", ascending=False).head(80)
    med_t = float(np.nanmedian(cm.turnover_days)) if cm.turnover_days.notna().any() else 0
    pts = [dict(name=f"{r_.company_label} · {r_.mclass_label}", x=min(r_.turnover_days, 2000) if r_.turnover_days == r_.turnover_days else 2000,
                y=r_.stock_avg, size=r_.stock_avg, group=("Нет потребления" if r_.consumption <= 0 else ("Медленные" if r_.turnover_days > med_t else "Быстрые")))
           for r_ in cm.itertuples()]
    sec.append(section("matrix", "why", "Матрица «Стоимость запаса × Оборачиваемость»",
                       f"Общество × класс МТР (80 крупнейших по среднему остатку); медиана оборачиваемости {med_t:.0f} дн.; «нет потребления» показано на правой границе",
                       chart=scatter(pts, "Оборачиваемость, дн.", "Средний остаток", "days", "rub", "Средний остаток",
                                     groups=["Быстрые", "Медленные", "Нет потребления"], vline=med_t)))
    if cr and kp.get("consumption"):
        A0, C0, D0 = kp["stock_avg"], kp["consumption"], ctx.days(*cr)
        A1, C1, D1 = k["stock_avg"], k["consumption"], ctx.days()
        T0, T1 = A0 / C0 * D0, (A1 / C1 * D1 if C1 else np.nan)
        e_a = (A1 - A0) / C0 * D0
        e_c = A1 / C1 * D0 - A1 / C0 * D0 if C1 else np.nan
        e_d = A1 / C1 * (D1 - D0) if C1 else np.nan
        sec.append(section("factor", "why", f"Разложение изменения оборачиваемости: {T1 - T0:+.0f} дн.",
                           "Метод цепных подстановок: влияние среднего остатка, потребления и длительности периода",
                           chart=waterfall([("Период сравнения", T0, "total"), ("Изменение среднего остатка", e_a, "delta"),
                                            ("Изменение потребления", e_c, "delta"), ("Число дней", e_d, "delta"), ("Текущий период", T1, "total")], unit="days")))
    tm = engine.aggregate(ctx, ["mclass", "company"], parts=("snap", "mov"))
    nodes = []
    for cls, g_ in tm.groupby("mclass_label"):
        nodes.append(dict(name=cls, value=float(g_.stock_avg.sum()), children=[
            dict(name=r_.company_label, value=float(r_.stock_avg), turnover=clean(r_.turnover_days)) for r_ in g_.itertuples() if r_.stock_avg > 0]))
    sec.append(section("tree", "risk", "Карта отвлечения капитала: класс МТР → общество", "Площадь — средний остаток; подсказка — оборачиваемость",
                       chart=treemap(nodes), span=2))
    thr = int(cfg.get()["coverage_excess_months"])
    ex = db.q(f"""
    WITH c AS (SELECT position_id, SUM(value) cons12 FROM movements WHERE mtype='Потребление' AND m BETWEEN {ctx.m2 - 11} AND {ctx.m2} GROUP BY 1)
    SELECT s.position_id, company_name, mclass, material_name, nsi_code, criticality, s.value, COALESCE(c.cons12,0) cons12,
           CASE WHEN COALESCE(c.cons12,0) > 0 THEN s.value / (c.cons12/12) END cov,
           GREATEST(s.value - COALESCE(c.cons12,0)/12*{thr}, 0) excess
    FROM snap s LEFT JOIN c USING (position_id)
    WHERE s.m={ctx.m2} AND s.on_balance AND s.demand_type='Регулярный' AND s.criticality <> 'A — критичный' AND {ctx.where('s')}
      AND s.value > COALESCE(c.cons12,0)/12*{thr}
    ORDER BY excess DESC LIMIT 100""")
    sec.append(section("excess", "action", f"Избыточное покрытие (> {thr} мес.) по регулярным некритичным позициям: {rub(ex.excess.sum())}",
                       "Кандидаты на сокращение пополнения. Для проектных запасов и критического ЗИП — см. витрины 9 и 12 (иные показатели).",
                       table=table(ex, [col("company_name", "Общество"), col("material_name", "МТР"), col("nsi_code", "Код НСИ"), col("mclass", "Класс"),
                                        col("value", "Остаток", "money"), col("cons12", "Потребление 12 мес.", "money"), col("cov", "Покрытие, мес.", "num"),
                                        col("excess", "Превышение", "money")], row_key="position_id", total=True), span=2))
    return dict(kpis=kpis, sections=sec)


# ======================================================================================
def _nez_involvement(ctx: Ctx) -> pd.DataFrame:
    """Пути вовлечения НЭЗ. Потребность других обществ учитывается только непокрытая
    (план 6 мес. − свободный остаток − открытые заказы) и ограничивает вовлекаемое количество."""
    return db.q(f"""
    WITH po AS (SELECT position_id, SUM(qty) q FROM purchase_orders WHERE order_date <= (SELECT month_end FROM cal WHERE m={ctx.m2})
                AND actual_delivery > (SELECT month_end FROM cal WHERE m={ctx.m2}) GROUP BY 1),
    gap AS (SELECT s.material_id, s.company_id, SUM(GREATEST(s.fut_need_6 - s.free_qty - COALESCE(po.q,0), 0)) gap
            FROM snap s LEFT JOIN po USING (position_id) WHERE s.m={ctx.m2} AND {ctx.access_clause('s')} GROUP BY 1,2),
    tot AS (SELECT material_id, SUM(gap) g FROM gap GROUP BY 1),
    ag AS (SELECT mt.analog_group, SUM(g.gap) g FROM gap g JOIN materials mt USING (material_id)
           WHERE mt.analog_group IS NOT NULL AND mt.analog_status = 'Подтверждён' GROUP BY 1),
    base AS (
      SELECT s.position_id, s.company_id, s.company_name, s.material_name, s.nsi_code, s.mclass, s.direction_name, s.service_name,
             s.project_status, s.days_no_issue, s.age_days, s.nez_value, s.nez_qty, s.price, s.value, s.qty, s.unit, s.repairable, s.special_flag,
             COALESCE(t.g,0) - COALESCE(own.gap,0) AS other_gap, COALESCE(a.g,0) analog_gap, s.analog_status
      FROM snap s LEFT JOIN tot t USING (material_id) LEFT JOIN gap own ON own.material_id = s.material_id AND own.company_id = s.company_id
      LEFT JOIN ag a ON a.analog_group = s.analog_group
      WHERE s.m={ctx.m2} AND s.on_balance AND s.nez_value > 0 AND {ctx.where('s')})
    SELECT *,
      CASE WHEN other_gap >= 1 THEN 'Потребность в другом обществе'
           WHEN analog_gap >= 1 THEN 'Аналог с потребностью (на тех. проверку)'
           WHEN special_flag THEN 'В процессе выбытия (НВИ/НЛИ/НР/ВР)'
           WHEN repairable THEN 'Ремонтопригоден: оценить восстановление/обмен'
           ELSE 'Путь вовлечения не подтверждён' END AS route,
      CASE WHEN other_gap >= 1 THEN LEAST(nez_qty, other_gap) * price ELSE 0 END AS involvable_value
    FROM base""")


def v04(ctx: Ctx, opts: dict) -> dict:
    k = engine.kpis(ctx)
    s_ = cfg.get()
    T, H = s_["nez"]["no_issue_days"], s_["nez"]["need_horizon_months"]
    cr = ctx.cmp_range()
    kp = engine.kpis(ctx, *cr) if cr else {}
    kpis = [kpi("nez_end", "НЭЗ", k["nez_end"], prev=kp.get("nez_end"), hib=False, sub=f"доля {pct(k['nez_share'])}"),
            kpi("nez_delta", "Изменение НЭЗ за период", k["nez_delta"], hib=False),
            kpi("nez_new", "Вновь сформировано", k["nez_new"], hib=False),
            kpi("nez_involved", "Вовлечено из НЭЗ", k["nez_involved"], hib=True,
                sub=f"потребл. {rub(k['nez_consumed'])} · перемещ. {rub(k['nez_transferred'])} · реализ. {rub(k['nez_sold'])} · списано {rub(k['nez_written_off'])}"),
            kpi("nez_reclass_out", "Вышло из категории", k["nez_reclass_out"], note="Появилась подтверждённая потребность или движение"),
            kpi("slow_need_end", "Без движения, но с подтверждённой потребностью", k["slow_need_end"],
                note="Не включается в НЭЗ (покрыто подтверждённой потребностью на горизонте)")]
    sec = []
    sg = engine.series(ctx, ["dgroup"], max(1, ctx.m2 - 23), ctx.m2, flows=False)
    piv = sg.pivot_table(index="m", columns="dgroup_label", values="nez", aggfunc="sum").fillna(0)
    tot = engine.series(ctx, [], max(1, ctx.m2 - 23), ctx.m2, flows=False).set_index("m")
    sec.append(section("dyn", "what", f"НЭЗ: {rub(k['nez_start'])} → {rub(k['nez_end'])} ({pct((k['nez_end'] / k['nez_start'] - 1) * 100 if k['nez_start'] else None, sign=True)})",
                       f"Правило (настраиваемое): без потребления ≥ {T} дн. и не покрыто подтверждённой потребностью на {H} мес.; страховой запас и критичные МТР исключены",
                       chart=bar([db.month_label(m) for m in piv.index], [dict(name=c, data=piv[c].tolist()) for c in piv.columns] +
                                 [dict(name="Доля НЭЗ, %", data=(tot.nez / tot.stock * 100).reindex(piv.index).round(1).tolist(), type="line", y2=True, unit="pct")],
                                 stacked=True), span=2))
    sec.append(section("wf", "what", "Движение НЭЗ за период: формирование и вовлечение", "Помесячное разложение по позициям; точная сверка начального и конечного остатка НЭЗ",
                       chart=waterfall([("НЭЗ на начало", k["nez_start"], "total"), ("Вновь сформированы", k["nez_new"], "delta"),
                                        ("Потребление", -k["nez_consumed"], "delta"), ("Перераспределение", -k["nez_transferred"], "delta"),
                                        ("Реализация", -k["nez_sold"], "delta"), ("Списание", -k["nez_written_off"], "delta"),
                                        ("Выход из категории", -k["nez_reclass_out"], "delta"), ("Переоценка", k["nez_reval"], "delta"),
                                        ("НЭЗ на конец", k["nez_end"], "total")])))
    dim = opt(opts, "dim", "direction")
    a = engine.aggregate(ctx, [dim], parts=("snap", "nez")).sort_values("nez_end", ascending=False)
    a = a[a.nez_end > 0]
    sec.append(section("bydim", "where", f"Структура НЭЗ: {DIMENSIONS[dim][2].lower()}", "Абсолютная сумма, доля и прирост",
                       chart=bar(a[f"{dim}_label"].tolist(), [dict(name="НЭЗ", data=a.nez_end.tolist(), color="bad")], horizontal=True),
                       table=table(a, [col(f"{dim}_label", DIMENSIONS[dim][2]), col("nez_end", "НЭЗ", "money"), col("nez_share", "Доля", "pct"),
                                       col("nez_delta", "Прирост", "money"), col("nez_new", "Сформировано", "money"), col("nez_involved", "Вовлечено", "money")],
                                   drill={"dim": dim, "key": dim}, total=True),
                       controls=[control("dim", "Разрез", DIM_OPTS, dim)], drill={"dim": dim}))
    ab = engine.aggregate(ctx, ["age_bucket"], parts=("snap",)).sort_values("age_bucket")
    nb = engine.aggregate(ctx, ["noissue_bucket"], parts=("snap",)).sort_values("noissue_bucket")
    sec.append(section("age", "where", "Распределение НЭЗ: давность поступления и период без потребления",
                       "Раздельный анализ: возраст по дате последнего поступления и срок с даты последнего фактического потребления",
                       chart=bar([x.split(". ", 1)[1] for x in ab.age_bucket.tolist()], [
                           dict(name="НЭЗ по давности поступления", data=ab.nez_end.tolist()),
                           dict(name="НЭЗ по периоду без потребления", data=nb.set_index("noissue_bucket").reindex(ab.age_bucket.tolist()).nez_end.fillna(0).tolist() if len(nb) else [])])))
    inv = _nez_involvement(ctx)
    top_ = inv.sort_values("nez_value", ascending=False).head(300)
    pts = [dict(name=f"{r.material_name} · {r.company_name}", x=r.days_no_issue, y=r.nez_value, size=r.nez_value, group=r.route,
                position_id=r.position_id) for r in top_.itertuples()]
    routes = ["Потребность в другом обществе", "Аналог с потребностью (на тех. проверку)", "В процессе выбытия (НВИ/НЛИ/НР/ВР)",
              "Ремонтопригоден: оценить восстановление/обмен", "Путь вовлечения не подтверждён"]
    sec.append(section("matrix", "why", "Матрица «Возраст × Стоимость × Возможность вовлечения»",
                       "300 крупнейших позиций НЭЗ; X — дней без потребления, Y — стоимость НЭЗ, цвет — подтверждённый путь вовлечения",
                       chart=scatter(pts, "Дней без потребления", "Стоимость НЭЗ", "days", "rub", "Стоимость", groups=routes, ylog=True), span=2))
    cross = db.q(f"""SELECT age_bucket, noissue_bucket, SUM(nez_value) v FROM snap WHERE m={ctx.m2} AND on_balance AND {ctx.where()} AND nez_value>0 GROUP BY 1,2""")
    xs = sorted(cross.noissue_bucket.unique())
    ys = sorted(cross.age_bucket.unique())
    vals = [[float(cross[(cross.age_bucket == y) & (cross.noissue_bucket == x)].v.sum()) for x in xs] for y in ys]
    sec.append(section("cross", "why", "Давность поступления × период без потребления (стоимость НЭЗ)",
                       "Позволяет отделить «новые, но не используемые» запасы от «старых и давно не используемых»",
                       chart=heatmap([x.split(". ", 1)[1] for x in xs], ["Поступл. " + y.split(". ", 1)[1] for y in ys], vals)))
    cause = db.q(f"""SELECT COALESCE(project_status, 'Не проектный запас') src, SUM(nez_value) v FROM snap
                   WHERE m={ctx.m2} AND on_balance AND nez_value > 0 AND {ctx.where()} GROUP BY 1 ORDER BY 2 DESC""")
    cause["basis"] = np.where(cause.src.isin(["Перенесён", "Отменён", "Изменено техническое решение", "Завершён"]),
                              "Подтверждено статусом проекта", "Причина не установлена — требуется анализ владельца")
    sec.append(section("cause", "why", "Источники НЭЗ, подтверждённые данными",
                       "Причина указывается только при наличии подтверждающих данных (статус проекта в учётной системе)",
                       table=table(cause, [col("src", "Источник / статус проекта"), col("v", "НЭЗ", "money"), col("basis", "Основание")], total=True)))
    rk = db.q(f"""SELECT position_id, company_name, material_name, mclass, days_no_issue, value, fut_need, criticality
                FROM snap WHERE m={ctx.m2} AND on_balance AND nez_value = 0 AND NOT nez_protected AND qty > 0
                AND days_no_issue BETWEEN {T - 90} AND {T - 1} AND fut_need < qty AND {ctx.where()} ORDER BY value DESC LIMIT 100""")
    sec.append(section("newrisk", "risk", f"Риск формирования новых НЭЗ в ближайшие 90 дн.: {rub(rk.value.sum())}",
                       f"Позиции без потребления {T - 90}–{T - 1} дн., потребность не покрывает остаток",
                       table=table(rk, [col("company_name", "Общество"), col("material_name", "МТР"), col("mclass", "Класс"),
                                        col("days_no_issue", "Дней без потребл.", "int"), col("value", "Стоимость", "money")], row_key="position_id", total=True)))
    agg_route = inv.groupby("route").nez_value.sum().reindex(routes).fillna(0)
    sec.append(section("routes", "action", "Пути вовлечения НЭЗ", "Распределение стоимости НЭЗ по подтверждённым возможностям",
                       chart=bar(routes, [dict(name="НЭЗ", data=agg_route.tolist())], horizontal=True)))
    inv["action"] = inv.route.map({routes[0]: "Предложить перераспределение (витрина 16)", routes[1]: "Направить на техническую проверку взаимозаменяемости",
                                   routes[2]: "Контроль сроков выбытия (витрина 18)", routes[3]: "Расчёт ремонт/обмен (витрина 17)",
                                   routes[4]: "Запросить подтверждение потребности у владельца; при отсутствии — включить в план реализации"})
    sec.append(section("list", "action", "Позиции НЭЗ: рекомендуемые действия", "Отсортировано по стоимости; решение — за владельцем запаса",
                       table=table(inv.sort_values("nez_value", ascending=False), [col("company_name", "Общество"), col("material_name", "МТР"),
                                   col("nsi_code", "Код НСИ"), col("service_name", "Служба"), col("days_no_issue", "Дней без потребл.", "int"),
                                   col("nez_value", "НЭЗ", "money"), col("route", "Путь вовлечения"), col("action", "Действие")], row_key="position_id"),
                       span=2))
    return dict(kpis=kpis, sections=sec)


# ======================================================================================
RATINGS = [
    ("r1", "1. Общества по стоимости запасов"), ("r2", "2. Общества по абсолютному приросту запасов"), ("r3", "3. Общества по приросту НЭЗ"),
    ("r4", "4. Общества по доле НЭЗ (с абсолютной суммой)"), ("r5", "5. Общества с худшей оборачиваемостью"), ("r6", "6. Классы МТР по накоплению"),
    ("r7", "7. Технические службы по НЭЗ"), ("r8", "8. Направления по НЭЗ"), ("r9", "9. Номенклатура по стоимости"),
    ("r10", "10. Позиции по длительности отсутствия потребления"), ("r11", "11. Крупнейшие невостребованные закупки"),
    ("r12", "12. Рост остатков при снижении потребления"), ("r13", "13. Запас в одних обществах — потребность в других"),
    ("r14", "14. Риски формирования новых НЭЗ"), ("r15", "15. Возможности предотвращения закупок"), ("r16", "16. Положительные практики и улучшения"),
]


def rating(ctx: Ctx, rid: str, n: int = 10) -> tuple[pd.DataFrame, list[dict], str]:
    T = cfg.get()["nez"]["no_issue_days"]
    if rid in ("r1", "r2", "r3", "r4", "r5"):
        a = engine.aggregate(ctx, ["company"], parts=("snap", "mov", "nez"))
        base = [col("company_label", "Общество"), col("stock_end", "Запасы", "money")]
        if rid == "r1":
            return top(a, "stock_end", n), base + [col("stock_delta", "Изменение", "money"), col("nez_end", "НЭЗ", "money")], "company"
        if rid == "r2":
            return top(a, "stock_delta", n), base + [col("stock_delta", "Прирост", "money"), col("stock_delta_pct", "Прирост, %", "pct")], "company"
        if rid == "r3":
            return top(a, "nez_delta", n), base + [col("nez_delta", "Прирост НЭЗ", "money"), col("nez_end", "НЭЗ", "money")], "company"
        if rid == "r4":
            a = a[a.stock_end > 100e6]
            return top(a, "nez_share", n), base + [col("nez_share", "Доля НЭЗ", "pct"), col("nez_end", "НЭЗ (абс.)", "money")], "company"
        return top(a[a.consumption > 0], "turnover_days", n), base + [col("turnover_days", "Оборачиваемость", "days"), col("consumption", "Потребление", "money")], "company"
    if rid == "r6":
        a = engine.aggregate(ctx, ["mclass"], parts=("snap", "mov"))
        return top(a, "stock_delta", n), [col("mclass_label", "Класс МТР"), col("stock_delta", "Прирост", "money"), col("stock_end", "Запасы", "money"),
                                          col("receipts", "Поступление", "money"), col("consumption", "Потребление", "money")], "mclass"
    if rid in ("r7", "r8"):
        d = "service" if rid == "r7" else "direction"
        a = engine.aggregate(ctx, [d], parts=("snap", "nez"))
        return top(a, "nez_end", n), [col(f"{d}_label", DIMENSIONS[d][2]), col("nez_end", "НЭЗ", "money"), col("nez_share", "Доля", "pct"),
                                      col("nez_delta", "Прирост", "money")], d
    if rid == "r9":
        a = engine.aggregate(ctx, ["material"], parts=("snap",))
        return top(a, "stock_end", n), [col("material_label", "Номенклатура"), col("stock_end", "Запасы", "money"), col("nez_end", "НЭЗ", "money")], "material"
    if rid == "r10":
        d = db.q(f"""SELECT material_id, material_name, company_name, days_no_issue, value, criticality, replenishment_policy FROM snap
                    WHERE m={ctx.m2} AND on_balance AND qty>0 AND value > 1e5 AND {ctx.where()} ORDER BY days_no_issue DESC, value DESC LIMIT {n}""")
        return d, [col("material_name", "МТР"), col("company_name", "Общество"), col("days_no_issue", "Дней без потребления", "int"),
                   col("value", "Стоимость", "money"), col("replenishment_policy", "Политика"), col("criticality", "Критичность")], "material_id"
    if rid == "r11":
        d = db.q(f"""SELECT material_id, material_name, company_name, last_receipt_date, value, days_no_issue FROM snap
                    WHERE m={ctx.m2} AND on_balance AND qty>0 AND last_receipt_date >= (SELECT month_start FROM cal WHERE m={max(0, ctx.m2 - 23)})
                    AND (last_issue_date IS NULL OR last_issue_date < last_receipt_date) AND NOT nez_protected AND {ctx.where()}
                    ORDER BY value DESC LIMIT {n}""")
        return d, [col("material_name", "МТР"), col("company_name", "Общество"), col("last_receipt_date", "Поступление", "date"),
                   col("value", "Стоимость", "money"), col("days_no_issue", "Дней без потребления", "int")], "material_id"
    if rid == "r12":
        cr = ctx.cmp_range() or (max(1, ctx.m1 - ctx.n_months), ctx.m1 - 1)
        a = engine.aggregate(ctx, ["material"], parts=("snap", "mov"))
        p = engine.aggregate(ctx, ["material"], cr[0], cr[1], parts=("mov",))[["material", "consumption"]]
        a = a.merge(p, on="material", suffixes=("", "_prev"))
        a = a[(a.stock_delta > 0) & (a.consumption < a.consumption_prev)]
        return top(a, "stock_delta", n), [col("material_label", "Номенклатура"), col("stock_delta", "Прирост остатка", "money"),
                                          col("consumption_prev", "Потребление ранее", "money"), col("consumption", "Потребление сейчас", "money")], "material"
    if rid == "r13":
        from .v16 import redistribution_candidates
        c = redistribution_candidates(ctx)
        return top(c, "value", n), [col("material_name", "МТР"), col("source_company", "Источник"), col("target_company", "Получатель"),
                                    col("qty", "Кол-во", "num"), col("value", "Стоимость", "money")], "material_id"
    if rid == "r14":
        d = db.q(f"""SELECT material_id, material_name, company_name, days_no_issue, value FROM snap
                    WHERE m={ctx.m2} AND on_balance AND nez_value = 0 AND NOT nez_protected AND qty > 0 AND days_no_issue BETWEEN {T - 120} AND {T - 1}
                    AND fut_need < qty AND {ctx.where()} ORDER BY value DESC LIMIT {n}""")
        return d, [col("material_name", "МТР"), col("company_name", "Общество"), col("days_no_issue", "Дней без потребления", "int"),
                   col("value", "Стоимость", "money")], "material_id"
    if rid == "r15":
        d = avoidable_purchases(ctx)
        return top(d, "avoidable_value", n), [col("material_name", "МТР"), col("company_name", "Заказчик"), col("po_value", "Открытые заказы", "money"),
                                              col("group_free_value", "Свободный запас группы", "money"), col("avoidable_value", "Можно предотвратить", "money")], "material_id"
    # r16 — положительные практики
    cr = ctx.cmp_range() or (max(1, ctx.m1 - ctx.n_months), ctx.m1 - 1)
    a = engine.aggregate(ctx, ["company", "mclass"], parts=("snap", "mov", "nez"))
    p = engine.aggregate(ctx, ["company", "mclass"], cr[0], cr[1], parts=("snap", "mov"))[["company", "mclass", "turnover_days"]]
    a = a.merge(p, on=["company", "mclass"], suffixes=("", "_prev"))
    a["improve"] = (-a.nez_delta).clip(lower=0) + a.nez_involved
    a["turn_improve"] = a.turnover_days_prev - a.turnover_days
    return top(a, "improve", n), [col("company_label", "Общество"), col("mclass_label", "Класс"), col("nez_delta", "Δ НЭЗ", "money"),
                                  col("nez_involved", "Вовлечено НЭЗ", "money"), col("turn_improve", "Ускорение оборач., дн.", "num")], "company"


def avoidable_purchases(ctx: Ctx) -> pd.DataFrame:
    return db.q(f"""
    WITH po AS (SELECT position_id, material_id, company_id, company_name, material_name, SUM(po_qty) q, SUM(po_value) v FROM v_po
                WHERE currency='RUB' AND order_date <= (SELECT month_end FROM cal WHERE m={ctx.m2}) AND actual_delivery > (SELECT month_end FROM cal WHERE m={ctx.m2})
                AND {ctx.where()} GROUP BY 1,2,3,4,5),
    sur AS (SELECT material_id, company_id, SUM(GREATEST(free_qty - fut_need_12, 0)) sq, AVG(price) p FROM snap WHERE m={ctx.m2} AND on_balance AND NOT nez_protected GROUP BY 1,2)
    SELECT po.material_id, ANY_VALUE(po.material_name) material_name, ANY_VALUE(po.company_name) company_name, SUM(po.v) po_value,
           ANY_VALUE(gs.sq * gs.p) group_free_value, LEAST(SUM(po.v), ANY_VALUE(gs.sq * gs.p)) avoidable_value
    FROM po JOIN (SELECT material_id, SUM(sq) sq, AVG(p) p FROM sur GROUP BY 1) gs USING (material_id)
    WHERE gs.sq > 0 GROUP BY po.material_id, po.company_id HAVING LEAST(SUM(po.v), ANY_VALUE(gs.sq * gs.p)) > 0""")


def v05(ctx: Ctx, opts: dict) -> dict:
    rid = opt(opts, "rating", "r3")
    n = int(opt(opts, "n", "10"))
    df, cols, dk = rating(ctx, rid, n)
    sec = []
    title = dict(RATINGS)[rid]
    drill_dim = {"company": "company", "mclass": "mclass", "service": "service", "direction": "direction", "material": "material", "material_id": "material"}.get(dk)
    val_col = next((c["key"] for c in cols if c["type"] in ("money", "days", "pct", "int") and c["key"] not in ("stock_end",)), cols[1]["key"])
    lab_col = cols[0]["key"]
    sec.append(section("rating", "where", f"ТОП-{n}: {title.split('. ', 1)[1]}", "Конструктор рейтингов: выберите рейтинг и глубину",
                       chart=bar(df[lab_col].astype(str).tolist()[::-1], [dict(name=next(c["label"] for c in cols if c["key"] == val_col),
                                 data=df[val_col].tolist()[::-1])], unit={"money": "rub", "days": "days", "pct": "pct", "int": "num"}[next(c["type"] for c in cols if c["key"] == val_col)],
                                 horizontal=True) if len(df) else None,
                       table=table(df, cols, drill={"dim": drill_dim, "key": dk} if drill_dim else None),
                       controls=[control("rating", "Рейтинг", RATINGS, rid), control("n", "Глубина", [("10", "ТОП-10"), ("20", "ТОП-20"), ("50", "ТОП-50")], str(n))],
                       note="Рейтинг долей сопровождается абсолютными суммами; в рейтинг долей включены общества с запасами > 100 млн ₽." if rid == "r4" else None,
                       span=2))
    pm = opt(opts, "pmetric", "nez_end")
    pd_ = opt(opts, "pdim", "company")
    a = engine.aggregate(ctx, [pd_], parts=("snap", "mov", "nez"))
    p = engine.pareto(a, pm, f"{pd_}_label")
    mlabels = {"stock_end": "Запасы", "nez_end": "НЭЗ", "nez_delta": "Прирост НЭЗ", "stock_delta": "Прирост запасов", "noissue_end": "Запасы без потребления"}
    th = p.get("thresholds", {})
    sec.append(section("pareto", "where", f"Концентрация: {th.get('50', '—')} / {th.get('80', '—')} / {th.get('90', '—')} из {p.get('n_total', 0)} "
                       f"формируют 50% / 80% / 90% показателя «{mlabels[pm]}»", f"Разрез: {DIMENSIONS[pd_][2]}",
                       chart=pareto_chart(p), controls=[control("pmetric", "Показатель", list(mlabels.items()), pm),
                                                        control("pdim", "Разрез", [("company", "Общества"), ("service", "Службы"), ("mclass", "Классы МТР"),
                                                                                   ("direction", "Направления"), ("material", "Номенклатура")], pd_)],
                       drill={"dim": pd_}, span=2))
    tm = engine.aggregate(ctx, ["company", "mclass"], parts=("snap",))
    nodes = [dict(name=c_, value=float(g_.nez_end.sum()), children=[dict(name=r.mclass_label, value=float(r.nez_end)) for r in g_.itertuples() if r.nez_end > 0])
             for c_, g_ in tm.groupby("company_label") if g_.nez_end.sum() > 0]
    sec.append(section("tree", "where", "НЭЗ: общество → класс МТР", "Площадь — стоимость НЭЗ", chart=treemap(nodes)))
    c = engine.aggregate(ctx, ["company"], parts=("snap",))
    pts = [dict(name=r.company_label, x=r.stock_end, y=r.nez_share, size=r.nez_end, group=r.company_label) for r in c.itertuples()]
    sec.append(section("bubble", "why", "Общества: запасы × доля НЭЗ (размер — НЭЗ в рублях)", "Сопоставление абсолютной и относительной проблемы",
                       chart=scatter(pts, "Запасы", "Доля НЭЗ, %", "rub", "pct", "НЭЗ")))
    hm = engine.aggregate(ctx, ["service", "mclass"], parts=("snap",))
    xs = sorted(hm.mclass_label.unique())
    ys = sorted(hm.service_label.unique())
    vals = [[float(hm[(hm.service_label == y) & (hm.mclass_label == x)].nez_end.sum()) for x in xs] for y in ys]
    sec.append(section("heat", "where", "Тепловая карта НЭЗ: служба × класс МТР", None, chart=heatmap(xs, ys, vals), span=2))
    return dict(kpis=[], sections=sec)
