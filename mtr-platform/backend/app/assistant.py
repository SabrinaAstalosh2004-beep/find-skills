"""AI Executive Analyst — локальный аналитический помощник на проверяемых запросах и правилах.

Языковая модель не подключена. Помощник:
1) распознаёт намерение вопроса по ключевым словам (и упоминания обществ, классов, служб, периода);
2) выполняет соответствующий расчёт через единый расчётный слой (engine / insights / scenarios);
3) формирует ответ из результатов расчёта, разделяя факты, зависимости, гипотезы, прогнозы и рекомендации,
   с указанием источника, периода, ограничений и ссылок на строки данных.
Заранее написанных ответов нет: все числа и формулировки собираются из результатов запросов.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from . import db, engine, insights, scenarios
from .filters import Ctx
from .vitrines.common import pct, rub, days, clean


def _ans(intent, summary, ctx: Ctx, facts=None, deps=None, hyps=None, fc=None, recs=None, tbl=None, sources=None, limits=None, rows=None, vitrine=None):
    return dict(intent=intent, summary=summary, facts=facts or [], dependencies=deps or [], hypotheses=hyps or [], forecasts=fc or [],
                recommendations=recs or [], table=tbl, sources=sources or [], period=ctx.period_label(), asof=db.month_label(ctx.m2),
                limitations=(limits or []) + ["Данные демонстрационные (синтетические)."], rows=rows or [], vitrine=vitrine,
                engine="Локальный аналитический движок (правила + SQL); языковая модель не подключена")


def _tbl(df: pd.DataFrame, cols: list[tuple[str, str, str]]):
    return dict(columns=[dict(key=k, label=l, type=t) for k, l, t in cols],
                rows=[{k: clean(r.get(k)) for k, _, _ in cols} for r in df.to_dict("records")])


def _parse(q: str, ctx: Ctx) -> Ctx:
    s = q.lower()
    m = re.search(r"(\d+)\s*(мес|месяц)", s)
    w = None
    if m:
        w = int(m.group(1))
    elif "за год" in s or "за 12" in s:
        w = 12
    elif "квартал" in s:
        w = 3
    extra = {}
    comps = db.q("SELECT company_id, company_name FROM companies")
    for r in comps.itertuples():
        core = re.sub(r"(АО|ООО|\(СП\)|«|»)", "", r.company_name).strip().lower()
        stem = core.split("-")[0][:5]
        if core and (core in s or (len(stem) >= 4 and stem in s)):
            extra.setdefault("company", []).append(r.company_id)
    for cls in db.q("SELECT DISTINCT mclass FROM materials").mclass:
        if cls.lower()[:10] in s:
            extra.setdefault("mclass", []).append(cls)
    if "газов" in s and "программ" in s:
        extra["program"] = ["Газовая программа"]
    if "capex" in s or "капекс" in s:
        extra["dgroup"] = ["CAPEX"]
    elif "opex" in s or "опекс" in s:
        extra["dgroup"] = ["OPEX"]
    c = ctx.with_filters(**extra) if extra else ctx
    if w:
        w = max(1, min(w, c.asof))
        c = Ctx(filters=c.filters, asof=c.asof, window=w, m1=c.asof - w + 1, compare=c.compare, grain=c.grain, role=c.role)
    return c


INTENTS = [
    ("nez_why", [r"почему", r"нэз|низкоэффект"]),
    ("pareto_growth", [r"80\s*%|80 процент|парето|основн", r"прирост|рост"]),
    ("services_worst", [r"служб", r"худш|динамик|хуже"]),
    ("classes_capital", [r"класс", r"капитал|отвлеч"]),
    ("involve_safe", [r"вовлеч", r"риск|безопас"]),
    ("avoid_purchases", [r"предотвра|избежать|отказ", r"закуп"]),
    ("structure_forecast", [r"через|прогноз|будет|изменит", r"структур|запас"]),
    ("top_decisions", [r"решени|меропри", r"эффект|наибольш|три|3"]),
    ("turnover_purchases", [r"оборачиваем", r"закуп|поступлен"]),
    ("recurring", [r"повторя|системн|регулярно"]),
    ("deficit", [r"дефицит|нехватк|обеспеченн"]),
    ("stock_why", [r"почему", r"запас|остат"]),
]


def answer(question: str, ctx: Ctx) -> dict:
    s = question.lower().strip()
    c = _parse(question, ctx)
    for intent, pats in INTENTS:
        if all(re.search(p, s) for p in pats):
            return globals()[f"_{intent}"](c, question)
    sl = _try_slice(s, c)
    if sl:
        return sl
    return _ans("unknown", "Вопрос не распознан локальным движком. Переформулируйте вопрос, используя поддерживаемые темы.", c,
                recs=["Почему увеличились НЭЗ за последние 6 месяцев?", "Какие общества обеспечили 80% прироста запасов?",
                      "Какие службы имеют худшую динамику?", "Какие классы МТР формируют наибольшее отвлечение капитала?",
                      "Какие запасы можно вовлечь без риска для производства?", "Какие закупки потенциально можно предотвратить?",
                      "Как изменится структура запасов через 6 месяцев?", "Какие три решения дадут наибольший обоснованный эффект?",
                      "Какие общества ухудшили оборачиваемость при росте закупок?", "Какие проблемы системно повторяются?",
                      "Покажи НЭЗ по службам", "Где риск дефицита критичных МТР?"],
                limits=["Без подключённой языковой модели поддерживаются только распознаваемые типы вопросов."])


def _nez_why(c: Ctx, q):
    k = engine.kpis(c)
    src = db.q(f"""SELECT COALESCE(project_status, 'Не проектный запас') st, SUM(nez_new) new_v FROM v_nezf WHERE on_balance AND m BETWEEN {c.m1} AND {c.m2}
                  AND {c.where()} GROUP BY 1 ORDER BY 2 DESC""")
    byc = engine.aggregate(c, ["company"], parts=("snap", "nez")).sort_values("nez_delta", ascending=False).head(5)
    byk = engine.aggregate(c, ["mclass"], parts=("snap", "nez")).sort_values("nez_new", ascending=False).head(5)
    facts = [f"НЭЗ изменились с {rub(k['nez_start'])} до {rub(k['nez_end'])} ({rub(k['nez_delta'])}).",
             f"Вновь сформировано {rub(k['nez_new'])}; вовлечено {rub(k['nez_involved'])}; вышло из категории {rub(k['nez_reclass_out'])}; переоценка {rub(k['nez_reval'])}.",
             "Наибольший прирост: " + "; ".join(f"{r.company_label} {rub(r.nez_delta)}" for r in byc.itertuples()) + "."]
    confirmed = src[src.st.isin(["Перенесён", "Отменён", "Изменено техническое решение", "Завершён"])]
    if len(confirmed):
        facts.append("Формирование НЭЗ на проектах с изменённым статусом (подтверждено статусом проекта): " +
                     "; ".join(f"{r.st} — {rub(r.new_v)}" for r in confirmed.itertuples()) + ".")
    deps = ["Классы МТР с наибольшим формированием НЭЗ: " + "; ".join(f"{r.mclass_label} {rub(r.nez_new)}" for r in byk.itertuples()) + "."]
    hyps = [f"{i['title']}: {i['cause']} [{i['cause_status']}]" for i in insights.compute(c) if i["type"] in ("stock_up_cons_down", "purchase_with_coverage", "plan_bias")][:4]
    rows = db.q(f"""SELECT position_id FROM snap WHERE m={c.m2} AND on_balance AND nez_value > 0 AND {c.where()} ORDER BY nez_value DESC LIMIT 10""").position_id.tolist()
    return _ans("nez_why", f"НЭЗ {('выросли' if k['nez_delta'] > 0 else 'снизились')} на {rub(abs(k['nez_delta']))}: формирование {rub(k['nez_new'])} превысило вовлечение {rub(k['nez_involved'])}.",
                c, facts, deps, hyps, recs=["Сфокусировать вовлечение на обществах и классах-лидерах прироста (витрина 4).",
                                             "Для проектных НЭЗ — синхронизировать графики поставок и передать МТР на активные проекты (витрины 8–10)."],
                tbl=_tbl(byc, [("company_label", "Общество", "text"), ("nez_start", "НЭЗ на начало", "money"), ("nez_end", "НЭЗ на конец", "money"),
                               ("nez_new", "Сформировано", "money"), ("nez_involved", "Вовлечено", "money")]),
                sources=["snapshot (остатки)", "nez_flow (разложение движения НЭЗ)", "projects (статусы)"],
                limits=["Правило НЭЗ настраиваемое и не является утверждённой нормой.", "Причины вне статуса проектов — гипотезы."], rows=rows, vitrine=4)


def _pareto_growth(c: Ctx, q):
    a = engine.aggregate(c, ["company"], parts=("snap",))
    pos = a[a.stock_delta > 0].sort_values("stock_delta", ascending=False)
    tot = pos.stock_delta.sum()
    pos["cum"] = pos.stock_delta.cumsum() / tot * 100 if tot else 0
    n80 = int((pos.cum < 80).sum() + 1) if tot else 0
    top_ = pos.head(n80)
    return _ans("pareto_growth", f"{n80} из {len(pos)} обществ с ростом запасов обеспечили 80% прироста ({rub(top_.stock_delta.sum())} из {rub(tot)}).", c,
                facts=[f"{r.company_label}: +{rub(r.stock_delta)} (накопленно {pct(r.cum)})" for r in top_.itertuples()],
                deps=[f"Общества со снижением запасов: {int((a.stock_delta < 0).sum())}; суммарное снижение {rub(a[a.stock_delta < 0].stock_delta.sum())}."],
                recs=["Детализировать прирост лидеров по классам МТР и направлениям (витрины 2, 5)."],
                tbl=_tbl(pos, [("company_label", "Общество", "text"), ("stock_delta", "Прирост", "money"), ("cum", "Накопленная доля, %", "pct")]),
                sources=["snapshot"], limits=["Анализ Парето рассчитан по положительным приростам."], vitrine=5)


def _services_worst(c: Ctx, q):
    cr = c.cmp_range() or (max(1, c.m1 - c.n_months), c.m1 - 1)
    a = engine.aggregate(c, ["service"])
    p = engine.aggregate(c, ["service"], cr[0], cr[1], parts=("snap", "mov"))[["service", "turnover_days"]]
    a = a.merge(p, on="service", how="left", suffixes=("", "_prev"))
    a["turn_chg"] = a.turnover_days - a.turnover_days_prev
    a["score"] = a.stock_delta.rank(ascending=False) + a.nez_delta.rank(ascending=False) + a.turn_chg.rank(ascending=False)
    w = a.sort_values("score").head(5)
    return _ans("services_worst", "Худшая динамика (комплексный ранг: прирост запасов, прирост НЭЗ, замедление оборачиваемости): " + ", ".join(w.service_label) + ".", c,
                facts=[f"{r.service_label}: Δ запасов {rub(r.stock_delta)}, Δ НЭЗ {rub(r.nez_delta)}, оборачиваемость {days(r.turnover_days_prev)} → {days(r.turnover_days)}" for r in w.itertuples()],
                hyps=["Рост запасов службы может быть обусловлен структурой оборудования и ремонтных программ — служба не признаётся неэффективной только по стоимости запасов."],
                recs=["Сравнить службу с обществами с сопоставимыми активами (витрина 7)."],
                tbl=_tbl(a.sort_values("score"), [("service_label", "Служба", "text"), ("stock_delta", "Δ запасов", "money"), ("nez_delta", "Δ НЭЗ", "money"),
                                                   ("turnover_days", "Оборач.", "days"), ("turn_chg", "Изм. оборач., дн.", "num")]),
                sources=["snapshot", "movements"], limits=["Ранг — равновзвешенная сумма рангов трёх показателей (методика демо)."], vitrine=7)


def _classes_capital(c: Ctx, q):
    a = engine.aggregate(c, ["mclass"]).sort_values("stock_avg", ascending=False)
    tot = a.stock_avg.sum()
    t = a.head(5)
    return _ans("classes_capital", f"Наибольшее отвлечение капитала: {', '.join(t.mclass_label)} — {pct(t.stock_avg.sum() / tot * 100)} среднего остатка.", c,
                facts=[f"{r.mclass_label}: средний остаток {rub(r.stock_avg)}, стоимость владения {rub(r.holding_cost)}/год, оборачиваемость {days(r.turnover_days)}" for r in t.itertuples()],
                recs=["Проверить избыточное покрытие по регулярным позициям этих классов (витрина 3)."],
                tbl=_tbl(a, [("mclass_label", "Класс", "text"), ("stock_avg", "Средний остаток", "money"), ("holding_cost", "Стоимость владения", "money"),
                             ("turnover_days", "Оборач.", "days")]),
                sources=["snapshot", "movements", "настройки (ставки)"], limits=["Ставки стоимости владения — допущения демо."], vitrine=3)


def _involve_safe(c: Ctx, q):
    from .vitrines.core import _nez_involvement
    inv = _nez_involvement(c)
    safe = inv[(inv.route.isin(["Потребность в другом обществе", "В процессе выбытия (НВИ/НЛИ/НР/ВР)"]))]
    rows = safe.sort_values("nez_value", ascending=False).head(15)
    return _ans("involve_safe", f"Без риска для производства можно вовлекать {rub(safe.nez_value.sum())} НЭЗ: позиции некритичные, не являются страховым запасом, "
                f"не покрыты собственной потребностью; из них {rub(inv.involvable_value.sum())} — в пределах непокрытой потребности других обществ.", c,
                facts=[f"Всего НЭЗ {rub(inv.nez_value.sum())}; распределение по путям: " + "; ".join(f"{k} — {rub(v)}" for k, v in inv.groupby('route').nez_value.sum().items())],
                hyps=["Пригодность к использованию требует подтверждения технического состояния и сроков хранения."],
                recs=["Сформировать перемещения в матрице витрины 16; остальное — в план реализации (витрина 18)."],
                tbl=_tbl(rows, [("company_name", "Общество", "text"), ("material_name", "МТР", "text"), ("nez_value", "НЭЗ", "money"), ("route", "Путь", "text")]),
                sources=["snapshot", "demand"], limits=["Критичные МТР и страховой запас исключены из НЭЗ по правилу."], rows=rows.position_id.tolist(), vitrine=4)


def _avoid_purchases(c: Ctx, q):
    from .vitrines.core import avoidable_purchases
    av = avoidable_purchases(c).sort_values("avoidable_value", ascending=False)
    cand = db.q(f"""
    WITH op AS (SELECT po_id, position_id, company_name, material_name, project_status, po_value FROM v_po WHERE currency='RUB'
                AND order_date <= (SELECT month_end FROM cal WHERE m={c.m2}) AND actual_delivery > (SELECT month_end FROM cal WHERE m={c.m2}) AND {c.where()}),
    s AS (SELECT position_id, free_qty, fut_need_12 FROM snap WHERE m={c.m2})
    SELECT op.* FROM op JOIN s USING (position_id) WHERE op.project_status IN ('Перенесён','Отменён') OR s.free_qty >= s.fut_need_12 ORDER BY po_value DESC""")
    return _ans("avoid_purchases", f"Потенциально можно предотвратить до {rub(av.avoidable_value.sum())} закупок за счёт свободного запаса группы; "
                f"кроме того, {len(cand)} открытых заказов на {rub(cand.po_value.sum())} — кандидаты на отмену/перенос.", c,
                facts=[f"{r.material_name} ({r.company_name}): заказы {rub(r.po_value)}, свободный запас группы {rub(r.group_free_value)}" for r in av.head(6).itertuples()],
                hyps=["Отмена заказов возможна только с учётом условий договоров и штрафов."],
                recs=["Проверить кандидатов в витрине 15 и оформить решения в центре мероприятий (витрина 20)."],
                tbl=_tbl(av.head(20), [("material_name", "МТР", "text"), ("company_name", "Заказчик", "text"), ("po_value", "Заказы", "money"),
                                       ("avoidable_value", "Можно предотвратить", "money")]),
                sources=["purchase_orders", "snapshot", "demand"], limits=["Верхняя граница: без учёта логистики и технической применимости."], vitrine=15)


def _structure_forecast(c: Ctx, q):
    h = 6
    m = re.search(r"(\d+)\s*(мес|месяц)", q.lower())
    if m:
        h = int(m.group(1))
    from . import forecast
    rows = []
    for g in ["CAPEX", "OPEX", "RevEx", "Коммерческая"]:
        cg = c.with_filters(dgroup=[g])
        s = engine.series(cg, [], 1, c.m2)
        if s.empty or s.stock.iloc[-1] <= 0:
            continue
        lvl = forecast.next_level(s.consumption.to_numpy(), "ses")
        po = db.q(f"""SELECT SUM(po_value) v FROM v_po WHERE currency='RUB' AND order_date <= (SELECT month_end FROM cal WHERE m={c.m2})
                     AND actual_delivery > (SELECT month_end FROM cal WHERE m={c.m2}) AND planned_delivery <= (SELECT month_end FROM cal WHERE m={c.m2 + h}) AND {cg.where()}""").v.iloc[0] or 0
        now = float(s.stock.iloc[-1])
        fut = max(0.0, now + po - lvl * h)
        rows.append(dict(group=g, now=now, future=fut, po=po, cons=lvl * h))
    d = pd.DataFrame(rows)
    d["share_now"] = d.now / d.now.sum() * 100
    d["share_future"] = d.future / d.future.sum() * 100
    return _ans("structure_forecast", f"Прогноз структуры запасов через {h} мес. при сохранении текущей ситуации: " +
                "; ".join(f"{r.group} {pct(r.share_now)} → {pct(r.share_future)}" for r in d.itertuples()) + ".", c,
                fc=[f"{r.group}: {rub(r.now)} → {rub(r.future)} (поступления по заказам {rub(r.po)}, прогноз потребления {rub(r.cons)})" for r in d.itertuples()],
                tbl=_tbl(d, [("group", "Группа", "text"), ("now", "Сейчас", "money"), ("future", f"Через {h} мес.", "money"), ("share_now", "Доля сейчас", "pct"),
                             ("share_future", "Доля прогноз", "pct")]),
                sources=["snapshot", "movements", "purchase_orders"], limits=["Прогноз: остаток + открытые заказы − прогноз потребления (SES). Новые заказы не учитываются.",
                                                                               "Прогноз не является фактом; интервал неопределённости — в витрине 13."], vitrine=13)


def _top_decisions(c: Ctx, q):
    r = scenarios.compute(c, mc=False)
    lv = [x for x in r["levers"] if x["group"] != "Базовый сценарий"]
    lv = sorted(lv, key=lambda x: -(x["cash_flow"] + x["opex_reduction"]))[:3]
    return _ans("top_decisions", "Три решения с наибольшим обоснованным эффектом (параметры сценария по умолчанию): " +
                "; ".join(f"{x['name']} — {rub(x['cash_flow'] + x['opex_reduction'])}" for x in lv) + ".", c,
                fc=[f"{x['name']}: высвобождение капитала {rub(x['wc_release'])}, денежный поток {rub(x['cash_flow'])}, снижение расходов {rub(x['opex_reduction'])}; "
                    f"формула: {x['formula']}; риск: {x['risk']}" for x in lv],
                recs=["Уточнить параметры в витрине 19 и оформить мероприятия с ответственными (витрина 20)."],
                sources=["scenarios (витрина 19)"], limits=["Эффекты — прогнозные, относительно базового сценария; пулы запасов не пересчитываются дважды."], vitrine=19)


def _turnover_purchases(c: Ctx, q):
    ins = [i for i in insights.turnover_worsening(c) if i.get("receipts_up")]
    return _ans("turnover_purchases", (f"Оборачиваемость ухудшилась при росте закупок у {len(ins)} обществ: " + ", ".join(i["company_name"] for i in ins) + ".")
                if ins else "Обществ с одновременным ухудшением оборачиваемости (> 20 дн. и > 15%) и ростом поступлений не выявлено.", c,
                facts=[i["observation"] for i in ins], deps=[f"{i['company_name']}: {i['cause']}" for i in ins],
                recs=["Разложить изменение оборачиваемости по факторам (витрина 3)."], sources=["snapshot", "movements"],
                limits=["Пороги детектора: +20 дн. и +15% к периоду сравнения (параметры демо)."], vitrine=3)


def _recurring(c: Ctx, q):
    acts = db.q("SELECT title, company_id, repeat_count, status FROM actions WHERE repeat_count > 1 ORDER BY repeat_count DESC", cache=False)
    pat = [i for i in insights.compute(c) if i["kind"] == "Закономерность"]
    return _ans("recurring", f"Выявлено {len(pat)} закономерностей и {len(acts)} повторяющихся проблем в реестре мероприятий.", c,
                facts=[f"Реестр: «{r.title}» ({r.company_id}) — повторов {r.repeat_count}, статус {r.status}" for r in acts.itertuples()],
                deps=[f"{i['title']} [{i['cause_status']}]" for i in pat],
                recs=["Для повторяющихся проблем — устранять системную причину (методика планирования, регламент заявок), а не разовые последствия."],
                sources=["actions", "insights"], vitrine=20)


def _deficit(c: Ctx, q):
    d = engine.deficit_positions(c)
    cr = d[d.criticality == "A — критичный"].sort_values("risk_score", ascending=False)
    return _ans("deficit", f"Потребность с риском дефицита: {rub(d.shortage_value.sum())} по {len(d)} позициям; критичные — {rub(cr.shortage_value.sum())} ({len(cr)}).", c,
                facts=[f"{r.material_name} ({r.company_name}): недостаёт {r.shortage_qty:g}, до потребности {r.days_to_need:.0f} дн., срок поставки {r.lead_days} дн."
                       for r in cr.head(6).itertuples()],
                hyps=["Вероятность — скоринговая оценка; при критичности приоритет — надёжность обеспечения, а не сокращение запасов."],
                recs=["Проверить закрытие дефицита перераспределением (витрины 14, 16)."],
                tbl=_tbl(cr.head(20), [("company_name", "Общество", "text"), ("material_name", "МТР", "text"), ("shortage_value", "Непокрыто", "money"),
                                       ("probability", "Вероятность", "num")]),
                sources=["demand", "snapshot", "purchase_orders"], rows=cr.head(10).position_id.tolist(), vitrine=14)


def _stock_why(c: Ctx, q):
    k = engine.kpis(c)
    cm = engine.aggregate(c, ["company", "mclass"], parts=("snap", "mov")).sort_values("stock_delta", ascending=False).head(5)
    return _ans("stock_why", f"Запасы изменились на {rub(k['stock_delta'])}: движение количества {rub(k['qty_driven_delta'])}, переоценка {rub(k['reval'])}.", c,
                facts=[f"Поступление {rub(k['receipts'])}, потребление {rub(k['consumption'])}, выбытие {rub(k['disposal'])}."] +
                [f"{r.company_label} / {r.mclass_label}: {rub(r.stock_delta)}" for r in cm.itertuples()],
                hyps=[f"{i['title']}: {i['cause']} [{i['cause_status']}]" for i in insights.compute(c) if i["type"] in ("stock_up_cons_down", "open_po_postponed")][:4],
                sources=["snapshot", "movements"], vitrine=2)


SYN_METRIC = {"нэз": "nez_end", "оборачиваем": "turnover_days", "запас": "stock_end", "потреблен": "consumption", "поступлен": "receipts",
              "дефицит": "deficit_value", "свободн": "free_end", "заказ": "open_po"}
SYN_DIM = {"служб": "service", "обществ": "company", "направлен": "direction", "класс": "mclass", "склад": "warehouse", "проект": "project",
           "программ": "program", "сегмент": "segment", "номенклатур": "material"}


def _try_slice(s: str, c: Ctx):
    met = next((v for k, v in SYN_METRIC.items() if k in s), None)
    dim = next((v for k, v in SYN_DIM.items() if k in s), None)
    if not (met and dim):
        return None
    a = engine.aggregate(c, [dim]).sort_values(met, ascending=False)
    from .metrics import REGISTRY
    m = REGISTRY[met]
    t = a.head(10)
    return _ans("slice", f"{m.label} в разрезе «{dim}»: лидеры — " + ", ".join(t[f"{dim}_label"].astype(str).head(3)) + ".", c,
                facts=[f"{getattr(r, dim + '_label')}: {rub(getattr(r, met)) if m.unit == 'rub' else round(getattr(r, met) or 0, 1)}" for r in t.itertuples()],
                tbl=_tbl(t, [(f"{dim}_label", dim, "text"), (met, m.label, "money" if m.unit == "rub" else "num")]),
                sources=[m.source], limits=[m.limitations] if m.limitations else [])
