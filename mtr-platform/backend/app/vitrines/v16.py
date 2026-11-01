"""Витрины 16–18: перераспределение и хабы, ремонт и повторное использование, НВИ/НЛИ/НР/ВР и выбытие."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .. import db, engine
from .. import settings as cfg
from ..filters import Ctx
from .common import bar, col, control, kpi, line, opt, pct, rub, sankey, scatter, section, table


def redistribution_candidates(ctx: Ctx, only_deficit: bool = False) -> pd.DataFrame:
    """Сопоставление свободного запаса без собственной потребности с непокрытой потребностью других позиций.

    Источник: свободный остаток сверх подтверждённой потребности 12 мес.; страховой запас и критичные МТР
    в источники не включаются. Получатель: непокрытая потребность (дефицит на горизонте или потребность 6 мес.
    за вычетом свободного остатка и открытых заказов). Учитываются совпадения по номенклатуре и
    подтверждённые аналоги (аналоги — с пометкой «требуется техническое подтверждение»).
    """
    r = cfg.get()["redistribution"]
    acc = ctx.access_clause("s")
    src = db.q(f"""SELECT s.position_id, s.company_id, s.company_name, s.ownership_type, s.region, s.warehouse_name, s.material_id,
                  s.material_name, s.nsi_code, s.mclass, s.unit, s.analog_group, s.analog_status, s.price,
                  GREATEST(s.free_qty - s.fut_need_12, 0) AS surplus
                  FROM snap s WHERE s.m={ctx.m2} AND s.on_balance AND NOT s.nez_protected AND s.free_qty - s.fut_need_12 >= 1 AND {acc}""")
    if only_deficit:
        d = engine.deficit_positions(ctx.with_filters(), asof=ctx.m2)
        tgt = d[["position_id", "company_id", "company_name", "ownership_type", "region", "warehouse_name", "material_id", "material_name",
                 "mclass", "unit", "analog_group", "criticality", "shortage_qty"]].rename(columns={"shortage_qty": "gap"}) if len(d) else pd.DataFrame()
    else:
        tgt = db.q(f"""
        WITH po AS (SELECT position_id, SUM(qty) q FROM purchase_orders WHERE order_date <= (SELECT month_end FROM cal WHERE m={ctx.m2})
                    AND actual_delivery > (SELECT month_end FROM cal WHERE m={ctx.m2}) GROUP BY 1)
        SELECT s.position_id, s.company_id, s.company_name, s.ownership_type, s.region, s.warehouse_name, s.material_id, s.material_name,
               s.mclass, s.unit, s.analog_group, s.criticality, GREATEST(s.fut_need_6 - s.free_qty - COALESCE(po.q, 0), 0) gap
        FROM (SELECT *, fut_need_3 * 2 AS fut_need_6 FROM snap WHERE m={ctx.m2} AND on_balance) s LEFT JOIN po USING (position_id)
        WHERE s.fut_need_6 - s.free_qty - COALESCE(po.q, 0) >= 1 AND {acc}""")
    if src.empty or tgt.empty:
        return pd.DataFrame(columns=["material_id", "material_name", "value", "source_company", "target_company"])
    tgt = tgt.sort_values(["criticality", "gap"], ascending=[True, False])
    src = src.sort_values("surplus", ascending=False)
    left = src.set_index("position_id")["surplus"].to_dict()
    by_mat = {k: g for k, g in src.groupby("material_id")}
    by_ag = {k: g for k, g in src[src.analog_status == "Подтверждён"].groupby("analog_group")}
    rows = []
    for t in tgt.itertuples():
        need = float(t.gap)
        cands = []
        if t.material_id in by_mat:
            cands += [(s_, "Совпадение по номенклатуре") for s_ in by_mat[t.material_id].itertuples()]
        if isinstance(t.analog_group, str) and t.analog_group in by_ag:
            cands += [(s_, "Подтверждённый аналог — требуется техническое подтверждение") for s_ in by_ag[t.analog_group].itertuples()
                      if s_.material_id != t.material_id]
        for s_, match in cands:
            if need < 0.5:
                break
            if s_.position_id == t.position_id or left.get(s_.position_id, 0) < 0.5:
                continue
            qn = float(min(need, left[s_.position_id]))
            if s_.unit == "шт":
                qn = math.floor(qn)
                if qn < 1:
                    continue
            value = qn * float(s_.price)
            if value < r["min_value_rub"]:
                continue
            same_co = s_.company_id == t.company_id
            same_reg = s_.region == t.region
            tp = 0.015 if same_co else (r["transport_cost_pct"] / 2 if same_reg else r["transport_cost_pct"])
            days_ = 5 if same_co else (10 if same_reg else 25)
            if same_co:
                appr = "Внутреннее перемещение (распоряжение УМТО общества)"
            elif "СП" in (s_.ownership_type, t.ownership_type):
                appr = "Решение органов управления СП + договор между обществами"
            else:
                appr = "Договор купли-продажи между обществами группы"
            left[s_.position_id] -= qn
            need -= qn
            rows.append(dict(source_position=s_.position_id, target_position=t.position_id, material_id=t.material_id,
                             material_name=t.material_name, source_material=s_.material_name, mclass=t.mclass, unit=t.unit,
                             source_company_id=s_.company_id, source_company=s_.company_name, source_wh=s_.warehouse_name,
                             target_company_id=t.company_id, target_company=t.company_name, target_wh=t.warehouse_name,
                             qty=qn, value=value, need_confirmed=float(t.gap), match=match,
                             scope="Межскладское (внутри общества)" if same_co else "Межобщественное",
                             transport_cost=value * tp, transit_days=days_ + r["approval_days"] * (0 if same_co else 1),
                             approval=appr, critical=t.criticality == "A — критичный",
                             group_effect=value - value * tp,
                             intragroup_turnover=0.0 if same_co else value))
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    if ctx.filters:
        scope = db.q(f"SELECT position_id FROM v_pos WHERE {ctx.where()}").position_id
        sc = set(scope)
        out = out[out.source_position.isin(sc) | out.target_position.isin(sc)]
    acts = db.q("SELECT issue_key, comment FROM actions WHERE source = 'Витрина 16: перераспределение' ORDER BY created_at", cache=False)
    st = dict(zip(acts.issue_key, acts.comment))
    out["decision_key"] = out.source_position + ">" + out.target_position
    out["decision"] = out.decision_key.map(st).fillna("Не рассмотрено")
    return out


def v16(ctx: Ctx, opts: dict) -> dict:
    c = redistribution_candidates(ctx)
    surplus = db.q(f"""SELECT SUM(GREATEST(free_qty - fut_need_12, 0) * price) v FROM snap WHERE m={ctx.m2} AND on_balance AND NOT nez_protected AND {ctx.where()}""").v.iloc[0] or 0
    inter = c[c.scope == "Межобщественное"] if len(c) else c
    kpis = [kpi("surplus", "Свободный запас сверх потребности 12 мес.", surplus, note="Страховой запас и критичные МТР исключены"),
            kpi("matched", "Сопоставлено с подтверждённой потребностью", c.value.sum() if len(c) else 0),
            kpi("effect", "Оценка эффекта группы", c.group_effect.sum() if len(c) else 0, hib=True,
                note="Предотвращённая внешняя закупка − транспорт. Сама передача между обществами экономией группы не является."),
            kpi("intragroup", "Внутригрупповой оборот (не экономия)", inter.value.sum() if len(inter) else 0),
            kpi("pairs", "Вариантов перемещения", len(c), "count", sub=f"межобщественных {len(inter)}")]
    sec = []
    if len(c):
        cc = c.sort_values(["critical", "value"], ascending=[False, False])
        sec.append(section("matrix", "action", "Матрица перераспределения: источник → получатель → МТР → решение",
                           "Решение фиксируется в реестре мероприятий (витрина 20). Перемещение не учитывается как экономия до подтверждения отказа от закупки.",
                           table=table(cc, [col("source_company", "Общество-источник"), col("target_company", "Общество-получатель"),
                                            col("material_name", "МТР"), col("match", "Совпадение"), col("qty", "Кол-во", "num"), col("unit", "Ед."),
                                            col("value", "Стоимость", "money"), col("need_confirmed", "Подтв. потребность", "num"),
                                            col("transit_days", "Срок, дн. (с согласованием)", "int"), col("transport_cost", "Транспорт", "money"),
                                            col("approval", "Согласование"), col("group_effect", "Эффект группы", "money"),
                                            col("decision", "Решение", "decision")], row_key="decision_key", limit=400, total=True),
                           kind="redistribution", span=2))
        f = inter.groupby(["source_company", "target_company"]).value.sum().reset_index()
        nodes = sorted(set("Источник: " + f.source_company) | set("Получатель: " + f.target_company))
        links = [dict(source="Источник: " + r.source_company, target="Получатель: " + r.target_company, value=float(r.value)) for r in f.itertuples()]
        sec.append(section("sankey", "where", "Потоки межобщественного перераспределения", "Стоимость предлагаемых перемещений",
                           chart=sankey(nodes, links) if links else None))
    reg = db.q(f"""
    SELECT region, SUM(GREATEST(free_qty - fut_need_12, 0) * price) surplus, SUM(GREATEST(fut_need_3 - free_qty, 0) * price) gap3,
           COUNT(DISTINCT warehouse_id) whs, COUNT(DISTINCT company_id) cos
    FROM snap WHERE m={ctx.m2} AND on_balance AND NOT nez_protected AND {ctx.where()} GROUP BY 1 ORDER BY surplus DESC""")
    sec.append(section("hubs", "where", "Потенциал региональных хабов: свободный запас и непокрытая потребность",
                       "Регион с несколькими складами и обществами — кандидат на хаб (требуется логистическое ТЭО)",
                       chart=bar(reg.region.tolist(), [dict(name="Свободный запас сверх потребности", data=reg.surplus.tolist()),
                                                       dict(name="Непокрытая потребность 3 мес.", data=reg.gap3.tolist())]),
                       table=table(reg, [col("region", "Регион"), col("whs", "Складов", "int"), col("cos", "Обществ", "int"),
                                         col("surplus", "Свободный запас", "money"), col("gap3", "Непокрытая потребность", "money")])))
    zl = cfg.get()["zip"]["service_level"]
    pool = db.q(f"""SELECT material_id, ANY_VALUE(material_name) material_name, COUNT(DISTINCT company_id) n, SUM(qty) qty, AVG(price) price,
                   SUM(qty * price) value FROM snap WHERE m={ctx.m2} AND on_balance AND replenishment_policy='Страховой запас' AND qty>0 AND {ctx.where()}
                   GROUP BY 1 HAVING COUNT(DISTINCT company_id) >= 2 ORDER BY value DESC""")
    if len(pool):
        pool["pooled_qty"] = np.ceil(pool.qty / np.sqrt(pool.n))
        pool["potential"] = (pool.qty - pool.pooled_qty) * pool.price
        sec.append(section("pool", "risk", f"Централизованный резерв критичного ЗИП: потенциал до {rub(pool.potential.sum())} (гипотеза)",
                           f"Оценка по закону квадратного корня для объединения страховых запасов (уровень сервиса {pct(zl * 100, 0)}). "
                           "Применимо только при допустимом сроке доставки до объекта; требует технического согласования.",
                           table=table(pool, [col("material_name", "МТР"), col("n", "Обществ", "int"), col("qty", "Кол-во сейчас", "num"),
                                              col("pooled_qty", "При объединении", "num"), col("value", "Стоимость", "money"),
                                              col("potential", "Потенциал", "money")], total=True)))
    sec.append(section("note", "why", "Методика и ограничения", None,
                       note="Источники — свободный остаток сверх подтверждённой потребности 12 мес. (без страхового запаса и критичных МТР). "
                            "Получатели — потребность 6 мес., не покрытая свободным остатком и открытыми заказами. Аналоги используются только "
                            "подтверждённые и требуют технического подтверждения. Транспортные ставки и сроки — параметры демо (настройки)."))
    return dict(kpis=kpis, sections=sec)


# ======================================================================================
def repair_options(ctx: Ctx, risk_factor: float = 0.5) -> pd.DataFrame:
    d = db.q(f"""SELECT r.*, v.company_name, v.material_name, v.mclass, v.nsi_code, v.criticality
                FROM repair_fund r JOIN v_pos v USING (position_id) WHERE {ctx.where('v')}""")
    if d.empty:
        return d
    d["cost_new"] = d.new_price + d.logistics_cost
    d["cost_repair"] = np.where(d.condition == "Неремонтопригоден", np.nan,
                                d.repair_cost + d.diagnostic_cost + 2 * d.logistics_cost + d.new_price * (1 - d.mtbf_ratio_after_repair) * risk_factor)
    d["cost_exchange"] = np.where(d.exchange_fee.notna(), d.exchange_fee + d.diagnostic_cost + d.logistics_cost +
                                  d.new_price * (1 - d.mtbf_ratio_after_repair) * risk_factor * 0.5, np.nan)
    d["cost_reuse"] = np.where(d.units_ready > 0, d.logistics_cost + d.diagnostic_cost + d.new_price * (1 - d.mtbf_ratio_after_repair) * risk_factor, np.nan)
    d["lead_new"], d["lead_repair"], d["lead_exchange"], d["lead_reuse"] = d.new_lead_days, d.repair_days, 30, 7
    opts_ = {"Новая закупка": "cost_new", "Ремонт": "cost_repair", "Обмен": "cost_exchange", "Повторное использование": "cost_reuse"}
    best, best_cost = [], []
    for r in d.itertuples():
        costs = {k: getattr(r, v) for k, v in opts_.items() if getattr(r, v) == getattr(r, v)}
        k = min(costs, key=costs.get)
        best.append(k)
        best_cost.append(costs[k])
    d["best"] = best
    d["best_cost"] = best_cost
    d["saving_unit"] = d.cost_new - d.best_cost
    d["annual_effect"] = d.saving_unit * d.annual_need_units
    d["needs_approval"] = np.where(d.tech_restriction != "Нет", "Да: " + d.tech_restriction, "Нет")
    return d


def v17(ctx: Ctx, opts: dict) -> dict:
    rf = float(opt(opts, "risk", "0.5"))
    d = repair_options(ctx, rf)
    if d.empty:
        return dict(kpis=[], sections=[section("empty", "what", "Нет данных ремонтного фонда в выбранном периметре", None)])
    alt = d[d.best != "Новая закупка"]
    kpis = [kpi("items", "Позиций в оборотном фонде", len(d), "count"), kpi("need_rep", "Узлов требуют ремонта", int(d.units_need_repair.sum()), "count"),
            kpi("ready", "Восстановленных узлов в наличии", int(d.units_ready.sum()), "count"),
            kpi("effect", "Потенциальный годовой эффект альтернатив", alt.annual_effect.sum(), hib=True,
                note="При годовой потребности по данным ремонтного фонда; до технического согласования"),
            kpi("rep_ratio", "Ремонт к цене нового (медиана)", float((d.repair_cost / d.new_price).median() * 100), "pct")]
    sec = []
    t12 = d.sort_values("annual_effect", ascending=False).head(12)
    sec.append(section("cmp", "what", "Сравнение вариантов на единицу: новая закупка / ремонт / обмен / повторное использование",
                       "Полная стоимость: цена/ремонт + диагностика + логистика + стоимость риска снижения надёжности",
                       chart=bar(t12.material_name.tolist(), [dict(name="Новая закупка", data=t12.cost_new.tolist()), dict(name="Ремонт", data=t12.cost_repair.tolist()),
                                                              dict(name="Обмен", data=t12.cost_exchange.tolist()), dict(name="Повторное использование", data=t12.cost_reuse.tolist())]),
                       controls=[control("risk", "Коэфф. стоимости риска отказа", [("0.25", "0,25"), ("0.5", "0,5 (база)"), ("1.0", "1,0")], str(rf))],
                       span=2))
    sec.append(section("tbl", "action", "Расчёт по позициям оборотного фонда", "Рекомендация — минимальная полная стоимость; при ограничениях требуется техническое заключение",
                       table=table(d.sort_values("annual_effect", ascending=False), [
                           col("company_name", "Общество"), col("material_name", "Узел/МТР"), col("condition", "Состояние"),
                           col("cost_new", "Новый", "money"), col("lead_new", "Срок, дн.", "int"), col("cost_repair", "Ремонт", "money"),
                           col("lead_repair", "Срок, дн.", "int"), col("cost_exchange", "Обмен", "money"), col("cost_reuse", "Повт. исп.", "money"),
                           col("warranty_repair_months", "Гарантия ремонта, мес.", "int"), col("best", "Рекомендация"),
                           col("annual_effect", "Годовой эффект", "money"), col("needs_approval", "Тех. согласование")], total=True), span=2))
    pts = [dict(name=r.material_name, x=r.repair_days, y=r.repair_cost / r.new_price * 100, size=r.new_price, group=r.best) for r in d.itertuples()
           if r.condition != "Неремонтопригоден"]
    sec.append(section("sc", "why", "Стоимость ремонта (% от нового) × срок ремонта", "Цвет — рекомендованный вариант",
                       chart=scatter(pts, "Срок ремонта, дн.", "Ремонт, % от цены нового", "days", "pct", "Цена нового",
                                     groups=["Новая закупка", "Ремонт", "Обмен", "Повторное использование"])))
    lim = d[d.tech_restriction != "Нет"]
    sec.append(section("lim", "risk", f"Технические ограничения: {len(lim)} позиций", "Решение принимает техническая служба",
                       table=table(lim, [col("material_name", "Узел"), col("company_name", "Общество"), col("tech_restriction", "Ограничение"),
                                         col("mtbf_ratio_after_repair", "Наработка после ремонта (доля от нового)", "num")])))
    return dict(kpis=kpis, sections=sec)


# ======================================================================================
FLAGS = [("flag_nvi", "НВИ"), ("flag_nli", "НЛИ"), ("flag_nr", "НР"), ("flag_vr", "ВР")]


def v18(ctx: Ctx, opts: dict) -> dict:
    w = ctx.where()
    fin = cfg.get()["finance"]
    cur = db.q(f"""SELECT {', '.join(f"SUM(CASE WHEN {f} THEN value ELSE 0 END) {f}" for f, _ in FLAGS)},
                 SUM(CASE WHEN special_flag THEN value ELSE 0 END) any_flag FROM snap WHERE m={ctx.m2} AND on_balance AND {w}""").iloc[0]
    ser = db.q(f"""SELECT m, {', '.join(f"SUM(CASE WHEN {f} THEN value ELSE 0 END) {f}" for f, _ in FLAGS)} FROM snap
                 WHERE on_balance AND m BETWEEN {max(1, ctx.m2 - 23)} AND {ctx.m2} AND {w} GROUP BY 1 ORDER BY 1""")
    dc = db.q(f"""SELECT d.*, v.company_name, v.material_name, v.mclass, v.ownership_type FROM disposal d JOIN v_pos v USING (position_id) WHERE {ctx.where('v')}""")
    closed = dc[dc.stage == "Закрыто"]
    closed_p = closed[closed.done_month.between(ctx.m1, ctx.m2)] if len(closed) else closed
    kpis = [kpi(f, f"Категория {lbl}", cur[f], hib=False, note="Расшифровка и правила отнесения — по корпоративной методологии (в демо — признак источника)")
            for f, lbl in FLAGS]
    kpis += [kpi("any", "Особого управления (без двойного счёта)", cur.any_flag, note="Позиция может иметь несколько признаков одновременно"),
             kpi("cases", "Дел в процессе выбытия", int((dc.stage != "Закрыто").sum()), "count"),
             kpi("cash", "Денежные поступления за период", closed_p.cash_proceeds.sum() if len(closed_p) else 0, hib=True)]
    sec = []
    sec.append(section("dyn", "what", "Динамика стоимости по категориям (признаки независимы)", "Запасы с признаком на конец месяца",
                       chart=line([db.month_label(m) for m in ser.m], [dict(name=l, data=ser[f].tolist()) for f, l in FLAGS]), span=2))
    byc = db.q(f"""SELECT company_name, {', '.join(f"SUM(CASE WHEN {f} THEN value ELSE 0 END) {f}" for f, _ in FLAGS)},
                  SUM(CASE WHEN special_flag THEN value ELSE 0 END) any_flag FROM snap WHERE m={ctx.m2} AND on_balance AND {w}
                  GROUP BY 1 HAVING SUM(CASE WHEN special_flag THEN value ELSE 0 END) > 0 ORDER BY any_flag DESC""")
    sec.append(section("byc", "where", "Категории по обществам", None,
                       table=table(byc, [col("company_name", "Общество")] + [col(f, l, "money") for f, l in FLAGS] +
                                   [col("any_flag", "Итого без двойного счёта", "money")], total=True)))
    stages = ["Выявлено", "Техническая оценка", "Согласование", "Подготовка к реализации", "Реализация/выбытие", "Закрыто"]
    if len(dc):
        fun = dc.groupby("stage").agg(n=("case_id", "count"), v=("book_value", "sum")).reindex(stages).fillna(0).reset_index()
        sec.append(section("funnel", "why", "Стадии процесса выбытия", "Количество дел и балансовая стоимость по текущей стадии",
                           chart=bar(fun.stage.tolist(), [dict(name="Балансовая стоимость", data=fun.v.tolist())]),
                           table=table(fun, [col("stage", "Стадия"), col("n", "Дел", "int"), col("v", "Балансовая стоимость", "money")])))
        dur = pd.DataFrame(dict(stage=["Техническая оценка", "Согласование", "Подготовка к реализации", "Исполнение"],
                                days=[dc.stage_days_assessment.mean(), dc.stage_days_approval.mean(), dc.stage_days_preparation.mean(), dc.stage_days_execution.mean()]))
        byco = dc.groupby("company_name").apply(lambda g: (g.stage_days_assessment + g.stage_days_approval + g.stage_days_preparation + g.stage_days_execution).mean(),
                                                include_groups=False).sort_values()
        sec.append(section("dur", "why", "Длительность стадий", "Средняя длительность, дней; сравнение обществ по полному циклу",
                           chart=bar(byco.index.tolist(), [dict(name="Полный цикл, дн.", data=byco.round(0).tolist())], unit="days", horizontal=True),
                           table=table(dur.round(0), [col("stage", "Стадия"), col("days", "Средняя длительность, дн.", "int")])))
        iss = dc[dc.approval_issue.notna()]
        sec.append(section("issues", "risk", f"Проблемы согласований и исполнения: {len(iss)} дел", None,
                           table=table(iss, [col("case_id", "Дело"), col("company_name", "Общество"), col("material_name", "МТР"), col("stage", "Стадия"),
                                             col("book_value", "Балансовая стоимость", "money"), col("approval_issue", "Проблема")])))
        routes = closed_p.groupby("route").agg(book=("book_value", "sum"), cash=("cash_proceeds", "sum"), costs=("disposal_costs", "sum")).reset_index() \
            if len(closed_p) else pd.DataFrame(columns=["route", "book", "cash", "costs"])
        routes["acc_result"] = routes.cash - routes.book - routes.costs
        routes["holding_saving"] = routes.book * (fin["storage_rate"] + fin["obsolescence_rate"])
        sec.append(section("fin", "action", "Финансовые результаты выбытия за период — показатели не смешиваются",
                           "Балансовое уменьшение ≠ денежные поступления ≠ бухгалтерский результат ≠ снижение расходов на содержание",
                           table=table(routes, [col("route", "Маршрут"), col("book", "Балансовое уменьшение", "money"), col("cash", "Денежные поступления", "money"),
                                                col("costs", "Расходы на выбытие", "money"), col("acc_result", "Бухгалтерский результат", "money"),
                                                col("holding_saving", "Снижение расходов на содержание (год, оценка)", "money")], total=True),
                           note="Бухгалтерский результат = поступления − балансовая стоимость − расходы. Снижение расходов на содержание — оценка по ставкам хранения и морального износа (допущение демо).",
                           span=2))
    return dict(kpis=kpis, sections=sec)
