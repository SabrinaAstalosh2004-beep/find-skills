"""Интеллектуальный механизм поиска аномалий и закономерностей поверх единой модели.

Для каждой находки формируется цепочка:
Наблюдение → Количественное подтверждение → Возможная причина (со статусом) → Проверки → Действие → Ожидаемый результат.

Правила достоверности:
* причина помечается «Подтверждено данными» только когда она следует из учётных данных
  (например, статус проекта «Отменён» в системе управления проектами);
* статистическая связь помечается как «Зависимость (не доказанная причина)»;
* остальное — «Гипотеза, требует проверки»;
* эффект рассчитывается только при достаточности данных, иначе — «не рассчитан».
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import db, engine
from . import settings as cfg
from .actions import owner_for, issue_key
from .filters import Ctx
from .vitrines.common import pct, rub

_cache: dict[str, list] = {}

CONFIRMED = "Подтверждено данными"
DEPENDENCY = "Зависимость (не доказанная причина)"
HYPOTHESIS = "Гипотеза, требует проверки"


def _ins(type_, kind, title, observation, evidence, cause, cause_status, checks, action, value, vitrines,
         effect=None, effect_note=None, severity=2, company_id=None, company_name=None, ownership=None, mclass=None,
         direction_id=None, service_id=None, rows=None, method=None, extra=None):
    return dict(id=issue_key(type_, company_id, mclass, direction_id, service_id, title[:40]), type=type_, kind=kind,
                title=title, observation=observation, evidence=evidence, cause=cause, cause_status=cause_status,
                checks=checks, action=action, effect=effect,
                effect_note=effect_note or ("Оценка по данным витрины" if effect is not None else "Не рассчитан: недостаточно данных для достоверной оценки"),
                value_at_risk=float(value or 0), severity=severity, company_id=company_id, company_name=company_name,
                mclass=mclass, direction_id=direction_id, service_id=service_id, vitrines=vitrines,
                owner=owner_for(type_, ownership), decision_needed=bool(severity >= 3 or ownership == "СП"),
                rows=rows or [], method=method, ownership=ownership, **(extra or {}))


def ev(label, value, unit="rub"):
    return dict(label=label, value=float(value) if value is not None and not (isinstance(value, float) and np.isnan(value)) else None, unit=unit)


def compute(ctx: Ctx) -> list[dict]:
    key = json.dumps(ctx.to_dict(), sort_keys=True, default=str) + json.dumps(cfg.get(), sort_keys=True)
    if key in _cache:
        return _cache[key]
    out: list[dict] = []
    for f in (stock_up_cons_down, nez_growth, purchases_with_coverage, turnover_worsening, postponed_projects,
              pre_completion_purchases, plan_bias, structure_shift, open_commitments, deficit_vs_free, supplier_delay,
              nez_concentration, recurring_accumulation, tech_change_excess):
        try:
            out.extend(f(ctx))
        except Exception as e:  # находка не должна ронять витрину
            out.append(_ins("engine_error", "Служебное", f"Детектор {f.__name__} не выполнен", str(e), [], "—", "—", [], "—", 0, [20], severity=1))
    sev_w = {3: 1.6, 2: 1.0, 1: 0.6}
    for i in out:
        i["priority_score"] = round(np.log10(max(i["value_at_risk"], 1)) * sev_w.get(i["severity"], 1), 2)
    out.sort(key=lambda x: -x["priority_score"])
    if len(_cache) > 50:
        _cache.clear()
    _cache[key] = out
    return out


def _cmp(ctx: Ctx):
    cr = ctx.cmp_range()
    if cr is None:
        a = max(1, ctx.m1 - ctx.n_months)
        cr = (a, ctx.m1 - 1) if ctx.m1 > 1 else None
    return cr


# ------------------------------------------------------------------------------------------
def stock_up_cons_down(ctx: Ctx) -> list[dict]:
    cr = _cmp(ctx)
    if not cr:
        return []
    cur = engine.aggregate(ctx, ["company", "mclass"], parts=("snap", "mov", "po"))
    prev = engine.aggregate(ctx, ["company", "mclass"], cr[0], cr[1], parts=("mov",))[["company", "mclass", "consumption"]]
    d = cur.merge(prev, on=["company", "mclass"], suffixes=("", "_prev"))
    d = d[(d.stock_delta > 30e6) & (d.consumption < d.consumption_prev * 0.9) & (d.consumption_prev > 0)]
    act = db.q(f"SELECT company_id, m, activity_index FROM activity")
    res = []
    comp = db.q("SELECT company_id, ownership_type FROM companies").set_index("company_id")["ownership_type"].to_dict()
    for r in d.sort_values("stock_delta", ascending=False).head(6).itertuples():
        a_now = act[(act.company_id == r.company) & act.m.between(ctx.m1, ctx.m2)].activity_index.mean()
        a_prev = act[(act.company_id == r.company) & act.m.between(cr[0], cr[1])].activity_index.mean()
        a_chg = (a_now / a_prev - 1) * 100 if a_prev else None
        cons_chg = (r.consumption / r.consumption_prev - 1) * 100
        dep = a_chg is not None and a_chg < -5
        cause = (f"Снижение производственной активности общества ({pct(a_chg, sign=True)}) при сохранении объёма поступлений "
                 f"({rub(r.receipts)} за период)" if dep else
                 f"Поступления ({rub(r.receipts)}) превышают потребление ({rub(r.consumption)}); причина не установлена")
        res.append(_ins(
            "stock_up_cons_down", "Аномалия", f"{r.company_label}: рост запасов «{r.mclass}» при снижении потребления",
            f"Запасы выросли на {rub(r.stock_delta)}, потребление снизилось на {pct(-cons_chg)} к сопоставимому периоду.",
            [ev("Изменение запасов", r.stock_delta), ev("Потребление, текущий период", r.consumption),
             ev("Потребление, период сравнения", r.consumption_prev), ev("Поступление", r.receipts), ev("Открытые заказы", r.open_po),
             ev("Изменение индекса активности, %", a_chg, "pct")],
            cause, DEPENDENCY if dep else HYPOTHESIS,
            ["Сверить планы потребности с актуальной производственной программой", "Проверить открытые заказы и их сроки",
             "Проверить резервы под отменённые/перенесённые работы"],
            "Пересмотреть открытые заказы и плановые заявки по классу; вовлечь избыточный запас в потребность других обществ",
            r.stock_delta, [1, 2, 3, 5, 15], effect=min(r.open_po, max(0.0, r.receipts - r.consumption)) or None,
            effect_note="Потенциал: не более открытых заказов и превышения поступлений над потреблением (верхняя граница, до проверки)",
            severity=3 if r.stock_delta > 150e6 else 2, company_id=r.company, company_name=r.company_label,
            ownership=comp.get(r.company), mclass=r.mclass, method="Сравнение периодов; поиск расхождения динамики запасов и потребления"))
    return res


def nez_growth(ctx: Ctx) -> list[dict]:
    d = engine.aggregate(ctx, ["company"], parts=("snap", "nez"))
    d = d[(d.nez_delta > 50e6) & (d.nez_delta > 0.1 * d.nez_start)]
    res = []
    comp = db.q("SELECT company_id, ownership_type FROM companies").set_index("company_id")["ownership_type"].to_dict()
    for r in d.sort_values("nez_delta", ascending=False).head(5).itertuples():
        src = db.q(f"""SELECT COALESCE(project_status, 'Без проекта') st, SUM(nez_new) v FROM v_nezf
                      WHERE on_balance AND m BETWEEN {ctx.m1} AND {ctx.m2} AND company_id='{r.company}' AND {ctx.where()}
                      GROUP BY 1 ORDER BY 2 DESC""")
        tot = src.v.sum() or 1
        proj = src[src.st.isin(["Перенесён", "Отменён", "Изменено техническое решение", "Завершён"])]
        share = proj.v.sum() / tot * 100
        if share > 40:
            cause = "Формирование НЭЗ связано с проектами со статусом: " + ", ".join(
                f"{s} — {rub(v)}" for s, v in zip(proj.st, proj.v))
            cs = CONFIRMED
        else:
            cause = "Источник не установлен: основная часть НЭЗ сформирована вне проектов с изменённым статусом"
            cs = HYPOTHESIS
        res.append(_ins(
            "nez_growth", "Аномалия", f"{r.company_label}: прирост НЭЗ {rub(r.nez_delta)}",
            f"НЭЗ выросли с {rub(r.nez_start)} до {rub(r.nez_end)} (доля {pct(r.nez_share)}).",
            [ev("НЭЗ на начало", r.nez_start), ev("НЭЗ на конец", r.nez_end), ev("Вновь сформировано", r.nez_new),
             ev("Вовлечено", r.nez_involved), ev("Доля НЭЗ на проектах с изменённым статусом, %", share, "pct")],
            cause, cs, ["Подтвердить отсутствие потребности у служб-владельцев", "Проверить возможность перераспределения и аналоги",
                        "Для критичных/страховых позиций — техническое заключение"],
            "Сформировать план вовлечения: перераспределение → реализация → списание (по корпоративному регламенту)",
            r.nez_delta, [1, 4, 5], severity=3 if r.nez_delta > 200e6 else 2, company_id=r.company, company_name=r.company_label,
            ownership=comp.get(r.company), method="Помесячное разложение движения НЭЗ (nez_flow)"))
    return res


def purchases_with_coverage(ctx: Ctx) -> list[dict]:
    H = int(cfg.get()["coverage_excess_months"])
    d = db.q(f"""
    WITH s0 AS (SELECT position_id, qty q0, fut_need_12 n12 FROM snap WHERE m = {ctx.m1 - 1}),
    rc AS (SELECT position_id, SUM(value) rv, SUM(qty) rq FROM movements WHERE mtype='Поступление' AND m BETWEEN {ctx.m1} AND {ctx.m2} GROUP BY 1)
    SELECT v.company_id, v.company_name, v.ownership_type, v.mclass, COUNT(*) n, SUM(rc.rv) rv
    FROM rc JOIN s0 USING (position_id) JOIN v_pos v USING (position_id)
    WHERE v.on_balance AND v.demand_type IN ('Регулярный') AND s0.q0 >= s0.n12 * {H} / 12.0 AND s0.n12 > 0 AND {ctx.where('v')}
    GROUP BY 1,2,3,4 HAVING SUM(rc.rv) > 15e6 ORDER BY rv DESC LIMIT 6""")
    res = []
    for r in d.itertuples():
        res.append(_ins(
            "purchase_with_coverage", "Аномалия", f"{r.company_name}: поступления «{r.mclass}» при покрытии ≥ {H} мес.",
            f"{r.n} позиций получили поступления на {rub(r.rv)}, хотя остаток на начало периода покрывал плановую потребность на {H}+ мес.",
            [ev("Поступления при наличии покрытия", r.rv), ev("Количество позиций", r.n, "count")],
            "Заказы размещались без учёта имеющегося остатка или по завышенному плану", HYPOTHESIS,
            ["Проверить, учитывался ли остаток при формировании заявки", "Сверить план потребности с фактом"],
            "Ввести контроль покрытия при согласовании заявок; отменить/перенести открытые заказы с избыточным покрытием",
            r.rv, [1, 5, 15], severity=2, company_id=r.company_id, company_name=r.company_name, ownership=r.ownership_type,
            mclass=r.mclass, method="Покрытие на начало периода по плановой потребности 12 мес."))
    return res


def turnover_worsening(ctx: Ctx) -> list[dict]:
    cr = _cmp(ctx)
    if not cr:
        return []
    cur = engine.aggregate(ctx, ["company"], parts=("snap", "mov"))
    prev = engine.aggregate(ctx, ["company"], cr[0], cr[1], parts=("snap", "mov"))[["company", "turnover_days", "receipts"]]
    d = cur.merge(prev, on="company", suffixes=("", "_prev"))
    d = d[(d.turnover_days - d.turnover_days_prev > 20) & (d.turnover_days > d.turnover_days_prev * 1.15)]
    res = []
    comp = db.q("SELECT company_id, ownership_type FROM companies").set_index("company_id")["ownership_type"].to_dict()
    for r in d.itertuples():
        rec_up = r.receipts > r.receipts_prev * 1.05
        res.append(_ins(
            "stock_up_cons_down", "Аномалия", f"{r.company_label}: замедление оборачиваемости до {r.turnover_days:.0f} дн.",
            f"Оборачиваемость ухудшилась на {r.turnover_days - r.turnover_days_prev:.0f} дн. ({r.turnover_days_prev:.0f} → {r.turnover_days:.0f})"
            + ("; поступления выросли." if rec_up else "."),
            [ev("Оборачиваемость, текущий период", r.turnover_days, "days"), ev("Оборачиваемость, период сравнения", r.turnover_days_prev, "days"),
             ev("Поступления, текущий", r.receipts), ev("Поступления, сравнение", r.receipts_prev)],
            "Средний остаток растёт быстрее потребления" + ("; одновременно растут закупки" if rec_up else ""), DEPENDENCY,
            ["Разложить изменение оборачиваемости по факторам (витрина 3)", "Проверить структуру поступлений"],
            "Определить классы МТР, формирующие замедление, и пересмотреть параметры пополнения", r.stock_avg * 0.05, [1, 3],
            severity=2, company_id=r.company, company_name=r.company_label, ownership=comp.get(r.company),
            extra={"receipts_up": bool(rec_up)}, method="Сравнение оборачиваемости по суммам"))
    return res


def postponed_projects(ctx: Ctx) -> list[dict]:
    d = db.q(f"""
    WITH s AS (SELECT project_id, SUM(value) stock FROM snap WHERE m={ctx.m2} AND on_balance AND {ctx.where()} GROUP BY 1),
    po AS (SELECT project_id, SUM(po_value) open_po, COUNT(*) n_po FROM v_po
           WHERE order_date <= (SELECT month_end FROM cal WHERE m={ctx.m2}) AND actual_delivery > (SELECT month_end FROM cal WHERE m={ctx.m2})
           AND {ctx.where()} GROUP BY 1)
    SELECT p.project_id, p.name, p.status, p.company_id, c.company_name, c.ownership_type, p.program, p.direction_id, p.event_m,
           COALESCE(s.stock,0) stock, COALESCE(po.open_po,0) open_po, COALESCE(po.n_po,0) n_po
    FROM projects p JOIN companies c USING (company_id) LEFT JOIN s USING (project_id) LEFT JOIN po USING (project_id)
    WHERE p.status IN ('Перенесён','Отменён') AND p.event_m <= {ctx.m2}""")
    res = []
    for r in d.itertuples():
        if r.stock + r.open_po < 5e6:
            continue
        res.append(_ins(
            "open_po_postponed" if r.open_po > 0 else "project_postponed", "Закономерность",
            f"{r.name} ({r.company_name}): статус «{r.status}», запасы и обязательства сохраняются",
            f"Проект {r.status.lower()} в {db.month_label(int(r.event_m))}; на складе {rub(r.stock)}, открытые заказы {rub(r.open_po)} ({r.n_po} шт.).",
            [ev("Запасы по проекту", r.stock), ev("Открытые заказы", r.open_po), ev("Число открытых заказов", r.n_po, "count")],
            f"Статус проекта «{r.status}» по данным системы управления проектами; график потребления изменён, обязательства по поставкам не скорректированы",
            CONFIRMED, ["Проверить возможность отмены/переноса заказов и штрафные санкции", "Определить потребность других проектов"],
            "Синхронизировать график поставок с актуальным графиком работ; рассмотреть передачу МТР на другие объекты",
            r.stock + r.open_po, [1, 8, 9, 10, 15], effect=r.open_po or None,
            effect_note="Верхняя граница предотвращённых поступлений — при отмене открытых заказов (до учёта штрафов)",
            severity=3, company_id=r.company_id, company_name=r.company_name, ownership=r.ownership_type,
            direction_id=r.direction_id, extra={"project_id": r.project_id, "program": r.program},
            method="Сопоставление статуса проекта, остатков и открытых заказов"))
    return res


def pre_completion_purchases(ctx: Ctx) -> list[dict]:
    """Доля поступлений за 3 мес. до завершения сравнивается с долей этого окна в длительности проекта."""
    d = db.q(f"""
    SELECT p.project_id, p.name, p.company_id, c.company_name, c.ownership_type, p.revised_end_m, p.start_m,
      SUM(CASE WHEN mv.m BETWEEN p.revised_end_m - 4 AND p.revised_end_m THEN mv.value ELSE 0 END) late_rec,
      SUM(mv.value) all_rec
    FROM movements mv JOIN positions ps USING (position_id) JOIN projects p ON p.project_id = ps.project_id
    JOIN companies c ON c.company_id = p.company_id
    WHERE mv.mtype='Поступление' AND mv.m <= {ctx.m2} AND p.revised_end_m <= {ctx.m2 + 2} AND p.revised_end_m >= {ctx.m1} AND {ctx.access_clause('c')}
    GROUP BY 1,2,3,4,5,6,7""")
    if d.empty:
        return []
    d["dur"] = (d.revised_end_m - d.start_m + 1).clip(lower=3)
    d["late_share"] = d.late_rec / d.all_rec.where(d.all_rec > 0)
    d["time_share"] = 5 / d.dur
    d["ratio"] = d.late_share / d.time_share
    d = d[(d.ratio > 1.5) & (d.late_rec > 20e6)]
    res = []
    for r in d.itertuples():
        res.append(_ins(
            "pre_completion_purchase", "Аномалия", f"{r.name}: концентрация поступлений за 5 мес. до завершения",
            f"За 5 мес. до планового завершения ({db.month_label(int(r.revised_end_m))}) поступило {rub(r.late_rec)} — {pct(r.late_share * 100)} всех поступлений "
            f"проекта при доле окна в сроке проекта {pct(r.time_share * 100)} (в {r.ratio:.1f} раза выше равномерного).",
            [ev("Поступления за 5 мес. до завершения", r.late_rec), ev("Все поступления проекта", r.all_rec),
             ev("Превышение над равномерным графиком, раз", r.ratio, "ratio")],
            "Нетипичная концентрация закупок на завершающей стадии (возможно — освоение бюджета или изменение объёмов)", HYPOTHESIS,
            ["Сверить с проектной документацией и остатком потребности", "Проверить обоснование заявок"],
            "Провести проверку обоснованности закупок; определить использование остатков после завершения",
            r.late_rec, [1, 9], severity=2, company_id=r.company_id, company_name=r.company_name, ownership=r.ownership_type,
            extra={"project_id": r.project_id}, method="Доля поступлений в окне 5 мес. до завершения против доли окна в сроке проекта"))
    return res


def plan_bias(ctx: Ctx) -> list[dict]:
    d = engine.aggregate(ctx, ["service"], parts=("mov", "plan"))
    d = d[(d.plan_bias_pct > 25) & (d.plan_value - d.consumption > 20e6)]
    res = []
    for r in d.sort_values("plan_bias_pct", ascending=False).itertuples():
        res.append(_ins(
            "plan_bias", "Закономерность", f"{r.service_label}: систематическое завышение плановой потребности на {pct(r.plan_bias_pct)}",
            f"План потребности за период {rub(r.plan_value)} при фактическом потреблении {rub(r.consumption)}.",
            [ev("План", r.plan_value), ev("Факт", r.consumption), ev("Завышение, %", r.plan_bias_pct, "pct")],
            "Устойчивое превышение плана над фактом по службе (проверено за весь период)", DEPENDENCY,
            ["Проверить, не ограничен ли факт дефицитом (витрина 14)", "Сверить нормы расхода и графики ремонтов"],
            "Скорректировать методику планирования службы; ввести контроль точности плана (витрина 13)",
            r.plan_value - r.consumption, [5, 7, 13], severity=2, service_id=r.service,
            method="План-факт по службам; bias = (План − Факт)/Факт"))
    return res


def structure_shift(ctx: Ctx) -> list[dict]:
    d = engine.aggregate(ctx, ["dgroup"], parts=("snap",))
    if d.stock_end.sum() <= 0 or d.stock_start.sum() <= 0:
        return []
    d["sh_end"] = d.stock_end / d.stock_end.sum() * 100
    d["sh_start"] = d.stock_start / d.stock_start.sum() * 100
    d["shift"] = d.sh_end - d.sh_start
    res = []
    for r in d[d["shift"].abs() > 4].itertuples():
        res.append(_ins(
            "structure", "Аномалия", f"Изменение структуры: доля {r.dgroup_label} {pct(r.sh_start)} → {pct(r.sh_end)}",
            f"Доля направления изменилась на {r.shift:+.1f} п.п. за период.",
            [ev("Доля на начало, %", r.sh_start, "pct"), ev("Доля на конец, %", r.sh_end, "pct"), ev("Изменение запасов", r.stock_delta)],
            "Требуется сопоставление с изменением инвестиционной/производственной программы", HYPOTHESIS,
            ["Сопоставить с исполнением программ (витрина 6)"], "Проверить соответствие структуры запасов программам",
            abs(r.stock_delta), [2, 6], severity=1, method="Анализ изменения структуры"))
    return res


def open_commitments(ctx: Ctx) -> list[dict]:
    if ctx.m1 <= 1:
        return []
    now = float(engine.aggregate(ctx, [], parts=("po",)).open_po.iloc[0])
    c0 = Ctx(filters=ctx.filters, asof=ctx.m1 - 1, window=1, m1=ctx.m1 - 1, role=ctx.role)
    then = float(engine.aggregate(c0, [], parts=("po",)).open_po.iloc[0])
    if then <= 0 or now < then * 1.2:
        return []
    return [_ins("purchase_with_coverage", "Закономерность", f"Рост незакрытых закупочных обязательств на {pct((now / then - 1) * 100)}",
                 f"Открытые заказы выросли с {rub(then)} до {rub(now)}; будущие поступления увеличат запасы.",
                 [ev("Открытые заказы на начало", then), ev("Открытые заказы на конец", now)],
                 "Рост обязательств опережает потребность или отражает увеличение сроков поставки", HYPOTHESIS,
                 ["Сопоставить с плановой потребностью на горизонте поставки", "Проверить сроки поставки (витрина 15)"],
                 "Ревизия открытых заказов с низким покрытием потребностью", now - then, [1, 15], severity=2,
                 method="Сравнение портфеля открытых заказов на две даты")]


def deficit_vs_free(ctx: Ctx) -> list[dict]:
    from .vitrines.v16 import redistribution_candidates
    c = redistribution_candidates(ctx, only_deficit=True)
    if c.empty:
        return []
    res = []
    for r in c.sort_values("value", ascending=False).head(5).itertuples():
        res.append(_ins(
            "redistribution", "Закономерность", f"Дефицит «{r.material_name}» в {r.target_company} при свободном запасе в {r.source_company}",
            f"Потребность {r.target_company} не покрыта на {r.qty:g} {r.unit}; у {r.source_company} есть свободный запас без потребности.",
            [ev("Стоимость перераспределения", r.value), ev("Транспортные затраты (оценка)", r.transport_cost),
             ev("Срок доставки, дн.", r.transit_days, "days")],
            "Одновременное наличие дефицита и свободного запаса по одной номенклатуре (подтверждено остатками и планом)", CONFIRMED,
            ["Подтвердить техническое состояние и сроки хранения", r.approval],
            "Перераспределить запас вместо новой закупки", r.value, [1, 14, 16],
            effect=max(0.0, r.group_effect) or None, effect_note="Эффект группы = предотвращённая внешняя закупка − транспорт; внутригрупповая передача экономией не считается",
            severity=3 if r.critical else 2, company_id=r.target_company_id, company_name=r.target_company,
            mclass=r.mclass, method="Сопоставление свободного запаса и непокрытой потребности по номенклатуре"))
    return res


def supplier_delay(ctx: Ctx) -> list[dict]:
    d = db.q(f"""
    SELECT po_supplier_id sid, supplier_name,
      AVG(CASE WHEN order_date >= (SELECT month_start FROM cal WHERE m={ctx.m2 - 8}) THEN date_diff('day', planned_delivery, actual_delivery) END) recent,
      AVG(CASE WHEN order_date < (SELECT month_start FROM cal WHERE m={ctx.m2 - 8}) THEN date_diff('day', planned_delivery, actual_delivery) END) before,
      SUM(CASE WHEN order_date >= (SELECT month_start FROM cal WHERE m={ctx.m2 - 8}) THEN po_value END) val
    FROM v_po WHERE order_date <= (SELECT month_end FROM cal WHERE m={ctx.m2}) AND {ctx.where()}
    GROUP BY 1,2""")
    d = d[(d.recent - d.before > 20)]
    res = []
    for r in d.itertuples():
        res.append(_ins(
            "supplier_delay", "Закономерность", f"Поставщик {r.supplier_name}: рост отклонения сроков поставки",
            f"Среднее отклонение фактической даты поставки от плановой выросло с {r.before:.0f} до {r.recent:.0f} дн.",
            [ev("Отклонение ранее, дн.", r.before, "days"), ev("Отклонение за 9 мес., дн.", r.recent, "days"), ev("Объём заказов за 9 мес.", r.val)],
            "Ухудшение надёжности поставщика (подтверждено датами поставок)", CONFIRMED,
            ["Проверить влияние на обеспеченность критичных позиций (витрина 14)", "Оценить страховой запас на период задержек"],
            "Претензионная работа; поиск альтернативного поставщика; пересмотр плановых сроков в параметрах пополнения",
            r.val, [14, 15], severity=2, method="Анализ сроков поставки по заказам", extra={"supplier_id": r.sid}))
    return res


def nez_concentration(ctx: Ctx) -> list[dict]:
    d = engine.aggregate(ctx, ["mclass"], parts=("snap",))
    p = engine.pareto(d, "nez_end", "mclass_label")
    if not p["categories"]:
        return []
    n80 = p["thresholds"]["80"]
    top_cls = p["categories"][:n80]
    tot = sum(p["values"])
    return [_ins("nez_growth", "Закономерность", f"Концентрация НЭЗ: {n80} из {p['n_total']} классов формируют 80%",
                 "Классы-лидеры: " + ", ".join(top_cls[:5]) + ("…" if len(top_cls) > 5 else ""),
                 [ev("НЭЗ всего", tot), ev("Классов для 80%", n80, "count")],
                 "Структурная концентрация (Парето)", DEPENDENCY, ["Проверить причины по каждому классу-лидеру"],
                 "Сфокусировать программу вовлечения на классах-лидерах", tot * 0.8, [4, 5, 11], severity=1,
                 method="Анализ Парето")]


def recurring_accumulation(ctx: Ctx) -> list[dict]:
    s = engine.series(ctx, [], 1, ctx.m2)
    s["net"] = s.receipts - s.consumption
    cal = db.q("SELECT m, EXTRACT(month FROM month_start) mon, year FROM cal")
    s = s.merge(cal, on="m")
    g = s.groupby(["mon", "year"]).net.sum().reset_index()
    res = []
    names = ["январе", "феврале", "марте", "апреле", "мае", "июне", "июле", "августе", "сентябре", "октябре", "ноябре", "декабре"]
    base = s.net.median()
    sd = s.net.std() or 1
    for mon, gg in g.groupby("mon"):
        if len(gg) >= 2 and (gg.net > base + 0.8 * sd).all():
            res.append(_ins("stock_up_cons_down", "Закономерность", f"Повторяющееся накопление запасов в {names[int(mon) - 1]}",
                            f"В {len(gg)} годах из {len(gg)} превышение поступлений над потреблением в {names[int(mon) - 1]} выше обычного уровня.",
                            [ev(f"{int(y)} г.: поступления − потребление", v) for y, v in zip(gg.year, gg.net)],
                            "Сезонный паттерн закупок (возможно, закрытие бюджетного года)", DEPENDENCY,
                            ["Проверить даты размещения заявок и бюджетные лимиты", "Сопоставить с графиком ремонтных кампаний"],
                            "Пересмотреть календарь закупок; выравнивать заказы по графику потребности",
                            float(gg.net.mean() - base), [2, 15], severity=1, method="Сравнение по календарным месяцам (сезонность)"))
    return res


def tech_change_excess(ctx: Ctx) -> list[dict]:
    d = db.q(f"""SELECT project_id, project_name, company_id, company_name, ownership_type, SUM(value) v FROM snap
                WHERE m={ctx.m2} AND on_balance AND project_status='Изменено техническое решение' AND {ctx.where()} GROUP BY 1,2,3,4,5""")
    return [_ins("project_postponed", "Закономерность", f"{r.project_name}: остатки после изменения технического решения",
                 f"После изменения технического решения на складе {rub(r.v)} МТР, не соответствующих актуальной проектной потребности.",
                 [ev("Остатки", r.v)], "Изменение технического решения (статус проекта в системе)", CONFIRMED,
                 ["Определить применимость в других проектах", "Подтвердить невостребованность проектной службой"],
                 "Передать в другие проекты либо включить в план реализации", r.v, [9], severity=2, company_id=r.company_id,
                 company_name=r.company_name, ownership=r.ownership_type, extra={"project_id": r.project_id},
                 method="Статус проекта × остатки") for r in d.itertuples() if r.v > 5e6]


def for_vitrine(ctx: Ctx, vid: int) -> list[dict]:
    return [i for i in compute(ctx) if vid in i["vitrines"] or vid == 1]
