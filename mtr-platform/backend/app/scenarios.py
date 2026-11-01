"""Витрина 19: экономика управления запасами и сценарное моделирование.

Принципы:
* все эффекты считаются относительно базового сценария «сохранение текущей модели» на горизонте 12 мес.;
* рычаги разделяют общие пулы запасов и применяются последовательно — один рубль запаса не может быть
  высвобожден дважды (исключение двойного счёта);
* высвобождение оборотного капитала, денежный поток, предотвращённые закупки, снижение операционных расходов
  и влияние на EBITDA показываются раздельно; итог по денежному потоку не суммируется с высвобождением капитала;
* для каждого рычага указаны исходные данные, формула, допущения и ограничения; неопределённость — Монте-Карло
  по степени достижения (треугольное распределение), seed фиксирован.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import db, engine
from . import settings as cfg
from .filters import Ctx

PARAMS = [
    # key, label, default, min, max, step, unit, group
    ("horizon", "Горизонт оценки, мес.", 12, 6, 24, 6, "мес.", "Общие"),
    ("cover_months", "Целевое покрытие регулярных МТР, мес.", 6, 3, 12, 1, "мес.", "Сокращение избыточного покрытия"),
    ("cover_share", "Достижимость сокращения избытка", 50, 0, 100, 5, "%", "Сокращение избыточного покрытия"),
    ("nez_share", "Доля вовлечения запасов с потребностью в других обществах", 40, 0, 100, 5, "%", "Ускорение потребления существующих запасов"),
    ("redist_share", "Доля исполненных перемещений из матрицы", 50, 0, 100, 5, "%", "Перераспределение"),
    ("redist_admin", "Затраты на оформление одного перемещения, тыс. ₽", 25, 0, 200, 5, "тыс. ₽", "Перераспределение"),
    ("po_share", "Доля отменённых/перенесённых заказов-кандидатов", 40, 0, 100, 5, "%", "Отказ от ненужных закупок"),
    ("po_penalty", "Штрафы/неустойки при отмене", 5, 0, 30, 1, "%", "Отказ от ненужных закупок"),
    ("vmi_share", "Доля регулярных МТР, переводимых на VMI/консигнацию", 0, 0, 50, 5, "%", "Изменение закупочной модели"),
    ("vmi_premium", "Надбавка к цене при VMI/консигнации", 3, 0, 15, 0.5, "%", "Изменение закупочной модели"),
    ("unif_share", "Реализация потенциала унификации (только подтверждённые аналоги)", 30, 0, 100, 5, "%", "Унификация МТР"),
    ("repair_share", "Доля замен ремонтом/обменом из расчёта витрины 17", 50, 0, 100, 5, "%", "Ремонт вместо покупки"),
    ("pool_share", "Реализация объединения страхового запаса ЗИП", 0, 0, 100, 5, "%", "Изменение структуры резервирования"),
    ("hub_enable", "Создание региональных хабов (0 — нет, 1 — да)", 0, 0, 1, 1, "", "Создание хабов"),
    ("hub_capex", "Затраты на создание хабов, млн ₽", 60, 0, 500, 10, "млн ₽", "Создание хабов"),
    ("hub_opex", "Операционные расходы хабов, млн ₽/год", 25, 0, 200, 5, "млн ₽", "Создание хабов"),
    ("forecast_bias_cut", "Снижение завышения плана потребности", 30, 0, 100, 5, "%", "Корректировка прогнозов"),
    ("forecast_stock_conv", "Доля завышения плана, переходящая в запас", 50, 10, 100, 5, "%", "Корректировка прогнозов"),
]


def defaults() -> dict:
    return {p[0]: p[2] for p in PARAMS}


def params_meta() -> list[dict]:
    return [dict(key=k, label=l, default=d, min=a, max=b, step=s, unit=u, group=g) for k, l, d, a, b, s, u, g in PARAMS]


def base_pools(ctx: Ctx, p: dict) -> dict:
    from .vitrines.core import avoidable_purchases
    from .vitrines.v16 import redistribution_candidates, repair_options
    N = float(p["cover_months"])
    a = ctx.m2
    reg = db.q(f"""
    WITH c AS (SELECT position_id, SUM(value) cons12 FROM movements WHERE mtype='Потребление' AND m BETWEEN {a - 11} AND {a} GROUP BY 1)
    SELECT SUM(s.value) reg_stock, SUM(GREATEST(s.value - COALESCE(c.cons12,0)/12*{N}, 0)) excess, SUM(COALESCE(c.cons12,0)) cons12
    FROM snap s LEFT JOIN c USING (position_id) WHERE s.m={a} AND s.on_balance AND s.demand_type='Регулярный' AND s.criticality <> 'A — критичный' AND {ctx.where('s')}""").iloc[0]
    surplus = db.q(f"""SELECT SUM(GREATEST(free_qty - fut_need_12, 0) * price) v FROM snap WHERE m={a} AND on_balance AND NOT nez_protected AND {ctx.where()}""").v.iloc[0] or 0
    from .vitrines.core import _nez_involvement
    inv = _nez_involvement(ctx)
    nez_demand = float(inv.involvable_value.sum()) if len(inv) else 0.0
    rc = redistribution_candidates(ctx)
    av = avoidable_purchases(ctx)
    cand = db.q(f"""
    WITH op AS (SELECT po_id, position_id, project_status, po_value FROM v_po WHERE currency='RUB' AND order_date <= (SELECT month_end FROM cal WHERE m={a})
                AND actual_delivery > (SELECT month_end FROM cal WHERE m={a}) AND {ctx.where()}),
    s AS (SELECT position_id, free_qty, fut_need_12 FROM snap WHERE m={a})
    SELECT SUM(po_value) v FROM op JOIN s USING (position_id) WHERE op.project_status IN ('Перенесён','Отменён') OR s.free_qty >= s.fut_need_12""").v.iloc[0] or 0
    rep = repair_options(ctx)
    rep_eff = float(rep[rep.best != "Новая закупка"].annual_effect.sum()) if len(rep) else 0.0
    un = db.q(f"""
    WITH g AS (SELECT s.analog_group, ANY_VALUE(s.analog_status) st, SUM(GREATEST(s.free_qty - s.fut_need_12,0) * s.price) surplus,
                      SUM(GREATEST(s.fut_need_12 - s.free_qty,0) * s.price) gap FROM snap s
               WHERE s.m={a} AND s.on_balance AND s.analog_group IS NOT NULL AND {ctx.where('s')} GROUP BY s.material_id, s.analog_group)
    SELECT SUM(p) v FROM (SELECT analog_group, LEAST(SUM(surplus), SUM(gap)) p FROM g WHERE st='Подтверждён' GROUP BY 1)""").v.iloc[0] or 0
    pool = db.q(f"""SELECT material_id, COUNT(DISTINCT company_id) n, SUM(qty) qty, AVG(price) price FROM snap
                   WHERE m={a} AND on_balance AND replenishment_policy='Страховой запас' AND qty>0 AND {ctx.where()} GROUP BY 1 HAVING COUNT(DISTINCT company_id) >= 2""")
    pool_pot = float(((pool.qty - np.ceil(pool.qty / np.sqrt(pool.n))) * pool.price).sum()) if len(pool) else 0.0
    k = engine.kpis(ctx)
    hub = db.q(f"""SELECT region, COUNT(DISTINCT warehouse_id) n, SUM(value) v FROM snap WHERE m={a} AND on_balance AND demand_type='Регулярный' AND {ctx.where()} GROUP BY 1""")
    hub_pot = float((hub.v * 0.3 * (1 - 1 / np.sqrt(hub.n.clip(lower=1)))).sum()) if len(hub) else 0.0
    s12 = engine.series(ctx, [], max(0, a - 12), a)
    trend = (s12.stock.iloc[-1] - s12.stock.iloc[0]) / max(1, len(s12) - 1)
    actual = db.q(f"""SELECT SUM(actual_effect) v FROM actions a JOIN companies c USING (company_id)
                     WHERE status='Выполнено, эффект подтверждён' AND {ctx.access_clause('c')}""", cache=False).v.iloc[0] or 0
    return dict(stock=k["stock_end"], trend=float(trend), reg_stock=float(reg.reg_stock or 0), excess=float(reg.excess or 0),
                cons12=float(reg.cons12 or 0), surplus=float(surplus), nez_demand=nez_demand,
                redist_value=float(rc.value.sum()) if len(rc) else 0.0, redist_transport=float(rc.transport_cost.sum()) if len(rc) else 0.0,
                redist_n=int(len(rc)), po_cand=float(cand), avoidable=float(av.avoidable_value.sum()) if len(av) else 0.0, repair=rep_eff,
                unif=float(un), pool=pool_pot, hub=hub_pot, plan_excess=max(0.0, float(k["plan_value"] - k["consumption"])) * 12 / max(1, ctx.n_months),
                actual_effect=float(actual), holding_rate=sum(cfg.get()["finance"][x] for x in ("cost_of_capital", "storage_rate", "obsolescence_rate")),
                opex_rate=cfg.get()["finance"]["storage_rate"] + cfg.get()["finance"]["obsolescence_rate"])


def compute(ctx: Ctx, p: dict | None = None, mc: bool = True) -> dict:
    p = {**defaults(), **(p or {})}
    for key in p:
        try:
            p[key] = float(p[key])
        except (TypeError, ValueError):
            p[key] = float(defaults().get(key, 0))
    b = base_pools(ctx, p)
    levers = _levers(b, p, {k: 1.0 for k in p})
    tot = _totals(levers)
    H = p["horizon"]
    base_stock = b["stock"] + b["trend"] * H
    res = dict(params=p, pools={k: v for k, v in b.items()}, levers=levers, totals=tot,
               base=dict(stock_now=b["stock"], trend_month=b["trend"], stock_horizon=base_stock,
                         formula=f"Запасы через {H:.0f} мес. = текущие запасы + среднемесячное изменение за 12 мес. × {H:.0f}"),
               scenario_stock=base_stock - tot["wc_release"], actual_effect=b["actual_effect"])
    if mc:
        rng = np.random.default_rng(42)
        draws_cf, draws_wc = [], []
        for _ in range(1000):
            mult = {k: rng.triangular(0.5, 1.0, 1.2) for k in p}
            lv = _levers(b, p, mult)
            t = _totals(lv)
            draws_cf.append(t["cash_flow"])
            draws_wc.append(t["wc_release"])
        res["uncertainty"] = dict(cash_flow=dict(p10=float(np.percentile(draws_cf, 10)), p50=float(np.percentile(draws_cf, 50)), p90=float(np.percentile(draws_cf, 90))),
                                  wc_release=dict(p10=float(np.percentile(draws_wc, 10)), p50=float(np.percentile(draws_wc, 50)), p90=float(np.percentile(draws_wc, 90))),
                                  method="Монте-Карло, 1000 итераций: достижимость каждого рычага ~ Треуг(0,5; 1,0; 1,2) × заданное значение; seed=42")
    variants = []
    for name, m in (("Консервативный", 0.5), ("Базовый (заданные параметры)", 1.0), ("Амбициозный", 1.5)):
        lv = _levers(b, p, {k: m for k in p})
        t = _totals(lv)
        variants.append(dict(name=name, **t, scenario_stock=base_stock - t["wc_release"]))
    res["variants"] = variants
    return res


def _levers(b: dict, p: dict, mult: dict) -> list[dict]:
    H = p["horizon"]
    hf = H / 12.0
    sh = lambda key: min(1.0, max(0.0, p[key] / 100.0 * mult.get(key, 1.0)))
    pool_regular = b["excess"]
    pool_surplus = b["surplus"]
    pool_reg_stock = b["reg_stock"]
    L = []

    def add(name, group, wc, avoided, cash, opex, impl, ebitda, risk, formula, inputs, assumptions, limits):
        L.append(dict(name=name, group=group, wc_release=wc, avoided_purchases=avoided, cash_flow=cash, opex_reduction=opex,
                      implementation_cost=impl, ebitda=ebitda, risk=risk, formula=formula, inputs=inputs, assumptions=assumptions, limitations=limits))

    add("Сохранение текущей модели", "Базовый сценарий", 0, 0, 0, 0, 0, 0, "Продолжение роста запасов по тренду",
        "Базовая линия для сравнения", f"Тренд {b['trend'] / 1e6:,.1f} млн ₽/мес.", "Структура поступлений и потребления сохраняется", "Не учитывает изменение программ")
    rel = min(pool_regular, b["excess"] * sh("cover_share"))
    pool_regular -= rel
    pool_reg_stock -= rel
    add("Сокращение избыточного покрытия", "Сокращение избыточного покрытия", rel, rel, rel, rel * b["opex_rate"] * hf, 0, rel * b["opex_rate"] * hf,
        "Низкий при сохранении страхового запаса; критичные МТР исключены",
        "min(пул избытка; Σ max(0, остаток − потребление₁₂/12 × N) × доля)", f"Избыток {b['excess'] / 1e6:,.1f} млн ₽ при N={p['cover_months']:.0f} мес.",
        "Высвобождение достигается сокращением пополнения (предотвращённые закупки = высвобождение)", "Регулярные некритичные позиции; сезонность не учтена")
    v = min(pool_surplus, b["nez_demand"] * sh("nez_share"))
    pool_surplus -= v
    add("Ускорение потребления существующих запасов", "Ускорение потребления существующих запасов", v, v, v, v * b["opex_rate"] * hf, 0, v * b["opex_rate"] * hf,
        "Средний: требуется подтверждение технического состояния",
        "min(пул излишка; НЭЗ с потребностью в других обществах × доля)", f"НЭЗ с потребностью {b['nez_demand'] / 1e6:,.1f} млн ₽",
        "Потребление существующего запаса замещает внешнюю закупку", "Внутригрупповая передача сама по себе экономией не является")
    rv = min(pool_surplus, b["redist_value"] * sh("redist_share"))
    pool_surplus -= rv
    tr = (b["redist_transport"] * rv / b["redist_value"]) if b["redist_value"] else 0
    adm = b["redist_n"] * sh("redist_share") * p["redist_admin"] * 1e3
    add("Перераспределение", "Перераспределение", rv, rv, rv - tr - adm, rv * b["opex_rate"] * hf - tr, adm, rv * b["opex_rate"] * hf - tr - adm,
        "Средний: сроки доставки и согласования (СП — органы управления)",
        "min(остаток пула излишка; матрица перераспределения × доля) − транспорт − оформление", f"Матрица {b['redist_value'] / 1e6:,.1f} млн ₽, {b['redist_n']} вариантов",
        "Эффект группы = предотвращённая внешняя закупка; пересечение с предыдущим рычагом исключено пулом", "Транспортные ставки — параметры демо")
    po = b["po_cand"] * sh("po_share")
    pen = po * p["po_penalty"] / 100
    add("Отказ от ненужных закупок", "Отказ от ненужных закупок", po, po, po - pen, po * b["opex_rate"] * hf, pen, po * b["opex_rate"] * hf - pen,
        "Низкий/средний: проверка условий договоров", "Открытые заказы-кандидаты × доля − неустойки",
        f"Кандидаты {b['po_cand'] / 1e6:,.1f} млн ₽", "Высвобождение — относительно базового прироста запасов", "Штрафы — параметр")
    vm = min(pool_reg_stock, b["reg_stock"] * sh("vmi_share") * 0.6)
    pool_reg_stock -= vm
    prem = b["cons12"] * sh("vmi_share") * p["vmi_premium"] / 100 * hf
    add("Изменение закупочной модели (VMI/консигнация)", "Изменение закупочной модели", vm, 0, vm - prem, vm * b["opex_rate"] * hf - prem, 0, vm * b["opex_rate"] * hf - prem,
        "Средний: зависимость от поставщика; сопоставимость условий требует проверки",
        "Регулярный запас × доля × 0,6 (переходит за баланс) − надбавка к цене × потребление", f"Регулярный запас {b['reg_stock'] / 1e6:,.1f} млн ₽",
        "60% запаса переводимых позиций переходит в собственность поставщика", "Не означает, что модель лучше спотовых закупок")
    un = min(pool_regular + pool_surplus, b["unif"] * sh("unif_share"))
    pool_regular = max(0.0, pool_regular - un)
    impl_u = 50e3 * (b["unif"] > 0) * 20 * sh("unif_share")
    add("Унификация МТР", "Унификация МТР", un, un, un - impl_u, un * b["opex_rate"] * hf, impl_u, un * b["opex_rate"] * hf - impl_u,
        "Средний: только подтверждённые аналоги; кандидаты — после технической проверки",
        "Потенциал подтверждённых групп аналогов × доля", f"Потенциал {b['unif'] / 1e6:,.1f} млн ₽", "Затраты на НСИ — 50 тыс. ₽ × 20 групп (допущение)", "Не учитывает сертификацию")
    rp = b["repair"] * sh("repair_share") * hf
    add("Ремонт вместо покупки", "Ремонт вместо покупки", 0, rp, rp, 0, 0, 0, "Средний: снижение наработки после ремонта учтено в стоимости",
        "Σ (стоимость нового − лучшая альтернатива) × годовая потребность × доля", f"Годовой эффект {b['repair'] / 1e6:,.1f} млн ₽",
        "Затраты на ремонт капитализируются/списываются по учётной политике — влияние на EBITDA не оценивается", "Требуется тех. согласование")
    pl = b["pool"] * sh("pool_share")
    add("Изменение структуры резервирования (пул ЗИП)", "Изменение структуры резервирования", pl, pl, pl, pl * b["opex_rate"] * hf, 0, pl * b["opex_rate"] * hf,
        "ВЫСОКИЙ: риск увеличения времени восстановления оборудования", "Закон квадратного корня для объединённого страхового запаса × доля",
        f"Потенциал {b['pool'] / 1e6:,.1f} млн ₽", "Допустимый срок доставки до объекта", "Только после технического согласования; приоритет — надёжность")
    if p["hub_enable"] >= 1:
        hb = min(pool_reg_stock, b["hub"])
        pool_reg_stock -= hb
        capex, opex_h = p["hub_capex"] * 1e6, p["hub_opex"] * 1e6 * hf
        add("Создание хабов", "Создание хабов", hb, hb, hb - capex - opex_h, hb * b["opex_rate"] * hf - opex_h, capex + opex_h, hb * b["opex_rate"] * hf - opex_h,
            "Средний: логистические сроки; требуется ТЭО", "Σ по регионам: регулярный запас × 30% × (1 − 1/√складов) − затраты",
            f"Потенциал {b['hub'] / 1e6:,.1f} млн ₽", "Доля страховой составляющей 30% (допущение)", "Грубая оценка до ТЭО")
    fc = min(pool_regular, b["plan_excess"] * sh("forecast_bias_cut") * p["forecast_stock_conv"] / 100 * hf)
    pool_regular -= fc
    add("Корректировка прогнозов потребности", "Корректировка прогнозов", fc, fc, fc - 10e6 * sh("forecast_bias_cut"), fc * b["opex_rate"] * hf,
        10e6 * sh("forecast_bias_cut"), fc * b["opex_rate"] * hf - 10e6 * sh("forecast_bias_cut"), "Низкий",
        "(План − Факт) годовой × снижение завышения × доля перехода в запас", f"Завышение плана {b['plan_excess'] / 1e6:,.1f} млн ₽/год",
        "Затраты на процесс/систему — 10 млн ₽ при 100% (допущение)", "Ограничено остатком пула избыточного покрытия")
    return L


def _totals(L: list[dict]) -> dict:
    keys = ["wc_release", "avoided_purchases", "cash_flow", "opex_reduction", "implementation_cost", "ebitda"]
    t = {k: float(sum(x[k] for x in L)) for k in keys}
    t["forecast_effect"] = t["cash_flow"] + t["opex_reduction"]
    return t
