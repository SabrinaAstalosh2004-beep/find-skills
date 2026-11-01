"""Витрины 6–11: направления деятельности, технические службы, бурение/ОНСС/ГРР, капстроительство,
газовая программа, классы МТР и аналоги."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import db, engine
from .. import settings as cfg
from ..filters import DIMENSIONS, Ctx
from .common import (bar, clean, col, control, days, gantt, heatmap, kpi, line, opt, pct, rub, scatter, section, table, treemap)
from .core import DIM_OPTS

HM_METRICS = [("stock_end", "Запасы", "rub"), ("nez_end", "НЭЗ", "rub"), ("nez_share", "Доля НЭЗ, %", "pct"),
              ("stock_delta", "Изменение запасов", "rub"), ("turnover_days", "Оборачиваемость, дн.", "days")]


def _hm(ctx, ydim, xdim, metric):
    a = engine.aggregate(ctx, [ydim, xdim], parts=("snap", "mov"))
    xs = a.groupby(f"{xdim}_label").stock_end.sum().sort_values(ascending=False).index.tolist()
    ys = a.groupby(f"{ydim}_label").stock_end.sum().sort_values(ascending=False).index.tolist()
    idx = a.set_index([f"{ydim}_label", f"{xdim}_label"])[metric]
    vals = [[clean(idx.get((y, x))) for x in xs] for y in ys]
    return xs, ys, vals


def _restrict(ctx: Ctx, key: str, allowed: list[str]) -> Ctx:
    cur = ctx.filters.get(key)
    if key == "direction" and cur:
        from ..filters import expand_directions
        cur = expand_directions(cur)
    vals = [a for a in allowed if not cur or a in cur]
    return ctx.with_filters(**{key: vals or ["__none__"]})


def project_table(ctx: Ctx) -> pd.DataFrame:
    a = ctx.m2
    w = ctx.where("v")
    d = db.q(f"""
    WITH fut AS (SELECT d.position_id, SUM(d.plan_qty) fq FROM demand d WHERE d.m > {a} GROUP BY 1),
    s AS (SELECT position_id, qty, price, value, reserved_value, nez_value FROM snap WHERE m={a}),
    po AS (SELECT position_id, SUM(qty) q, SUM(value) v FROM purchase_orders WHERE order_date <= (SELECT month_end FROM cal WHERE m={a})
           AND actual_delivery > (SELECT month_end FROM cal WHERE m={a}) GROUP BY 1),
    pall AS (SELECT position_id, SUM(value) v FROM purchase_orders WHERE order_date <= (SELECT month_end FROM cal WHERE m={a}) GROUP BY 1),
    mv AS (SELECT position_id, SUM(CASE WHEN mtype='Поступление' THEN value ELSE 0 END) rec,
                  SUM(CASE WHEN mtype='Потребление' THEN value ELSE 0 END) used FROM movements WHERE m <= {a} GROUP BY 1)
    SELECT v.project_id, ANY_VALUE(v.project_name) project_name, ANY_VALUE(v.project_type) project_type, ANY_VALUE(v.project_status) status,
           ANY_VALUE(v.company_id) company_id, ANY_VALUE(v.company_name) company_name, ANY_VALUE(v.program) program, ANY_VALUE(v.direction_name) direction_name,
           SUM(COALESCE(pall.v,0)) purchased, SUM(COALESCE(mv.rec,0)) received, SUM(COALESCE(mv.used,0)) used,
           SUM(COALESCE(s.value,0)) stock, SUM(COALESCE(s.reserved_value,0)) reserved, SUM(COALESCE(s.nez_value,0)) nez,
           SUM(COALESCE(po.v,0)) open_po, SUM(COALESCE(fut.fq,0) * COALESCE(s.price,0)) future_need,
           SUM(GREATEST(COALESCE(s.qty,0) + COALESCE(po.q,0) - COALESCE(fut.fq,0), 0) * COALESCE(s.price,0)) leftover_forecast
    FROM v_pos v LEFT JOIN s USING (position_id) LEFT JOIN po USING (position_id) LEFT JOIN pall USING (position_id)
    LEFT JOIN mv USING (position_id) LEFT JOIN fut USING (position_id)
    WHERE v.project_id IS NOT NULL AND v.on_balance AND {w} GROUP BY v.project_id""")
    if d.empty:
        return d
    p = db.q("SELECT project_id, start_m, end_m, revised_end_m, event_m, delay FROM projects")
    d = d.merge(p, on="project_id", how="left")
    d["progress"] = ((a - d.start_m) / (d.revised_end_m - d.start_m).clip(lower=1) * 100).clip(0, 100)
    d.loc[d.status == "Отменён", "progress"] = np.nan
    d["stage"] = np.select([d.status == "Завершён", d.status == "Отменён", d.status == "Перенесён", a < d.start_m, d.progress < 80],
                           ["Завершён", "Отменён", "Перенесён (приостановлен)", "Подготовка (ПИР)", "Строительство"], "Пусконаладка / завершение")
    d["readiness"] = ((d.used + d.stock) / (d.used + d.future_need).replace(0, np.nan) * 100).clip(upper=300)
    d["start"] = d.start_m.map(db.month_label)
    d["plan_end"] = d.end_m.map(db.month_label)
    d["rev_end"] = d.revised_end_m.map(db.month_label)
    return d


# ======================================================================================
def v06(ctx: Ctx, opts: dict) -> dict:
    g = engine.aggregate(ctx, ["dgroup"]).set_index("dgroup")
    tot = g.stock_end.sum()
    kpis = [kpi(f"g_{k}", f"Запасы {k}", g.stock_end.get(k, 0), sub=f"доля {pct(g.stock_end.get(k, 0) / tot * 100 if tot else None)} · НЭЗ {rub(g.nez_end.get(k, 0))}")
            for k in ["CAPEX", "OPEX", "RevEx", "Коммерческая"] if k in g.index]
    sec = []
    sd = engine.series(ctx, ["dgroup"], max(1, ctx.m2 - 23), ctx.m2, flows=False)
    piv = sd.pivot_table(index="m", columns="dgroup_label", values="stock", aggfunc="sum").fillna(0)
    sec.append(section("dyn", "what", "Динамика запасов по CAPEX / OPEX / RevEx за 24 месяца", None,
                       chart=bar([db.month_label(m) for m in piv.index], [dict(name=c, data=piv[c].tolist()) for c in piv.columns], stacked=True), span=2))
    a = engine.aggregate(ctx, ["direction"])
    dirs = db.q("SELECT direction_id, direction_group FROM directions")
    a = a.merge(dirs, left_on="direction", right_on="direction_id", how="left")
    a["share"] = a.stock_end / a.stock_end.sum() * 100
    a["plan_exec"] = np.where(a.plan_value > 0, a.consumption / a.plan_value * 100, np.nan)
    a["turn_view"] = np.where(a.direction_group == "CAPEX", np.nan, a.turnover_days)
    a["turn_note"] = np.where(a.direction_group == "CAPEX", "н/п — проектный запас (см. покрытие)", np.where(a.consumption > 0, "Рассчитано", "Нет потребления"))
    a = a.sort_values("stock_end", ascending=False)
    sec.append(section("tbl", "where", "Направления формирования запасов", "Оборачиваемость показывается там, где применима; для CAPEX — покрытие проектной потребности (витрина 9)",
                       table=table(a, [col("direction_label", "Направление"), col("direction_group", "Группа"), col("stock_end", "Запасы", "money"),
                                       col("share", "Доля", "pct"), col("stock_delta", "Изменение", "money"), col("nez_end", "НЭЗ", "money"),
                                       col("receipts", "Поступление", "money"), col("consumption", "Потребление", "money"),
                                       col("plan_exec", "Исполнение плана потребности", "pct"), col("turn_view", "Оборач., дн.", "days"),
                                       col("turn_note", "Статус оборачиваемости", "status")], drill={"dim": "direction", "key": "direction"}, total=True), span=2))
    sec.append(section("hier", "where", "Иерархия: группа → направление → общество → служба → класс МТР → номенклатура",
                       "Нажмите на строку для перехода на следующий уровень", kind="hierarchy",
                       extra={"levels": ["dgroup", "direction", "company", "service", "mclass", "material"]}, span=2))
    hm = opt(opts, "hm", "stock_end")
    xs, ys, vals = _hm(ctx, "direction", "company", hm)
    u = dict((m, x) for m, _, x in HM_METRICS)[hm]
    sec.append(section("heat", "where", f"Тепловая карта «Направление × Общество»: {dict((m, l) for m, l, _ in HM_METRICS)[hm]}", None,
                       chart=heatmap(xs, ys, vals, unit=u, diverging=(hm == "stock_delta")),
                       controls=[control("hm", "Показатель", [(m, l) for m, l, _ in HM_METRICS], hm)], span=2))
    cr = ctx.cmp_range()
    if cr:
        ap = engine.aggregate(ctx, ["direction"], parts=("snap",))
        ap = ap[ap.stock_end > 0].sort_values("stock_end")
        s0, s1 = ap.stock_start.sum(), ap.stock_end.sum()
        sec.append(section("struct", "why", "Изменение структуры: доля направления на начало и конец периода", None,
                           chart=bar(ap.direction_label.tolist(), [dict(name="На начало, %", data=(ap.stock_start / s0 * 100).round(1).tolist()),
                                                                   dict(name="На конец, %", data=(ap.stock_end / s1 * 100).round(1).tolist())], unit="pct", horizontal=True)))
    pt = project_table(ctx)
    if len(pt):
        byd = pt.groupby("direction_name").agg(stock=("stock", "sum"), used=("used", "sum"), future=("future_need", "sum"),
                                               leftover=("leftover_forecast", "sum"), progress=("progress", "mean")).reset_index()
        sec.append(section("prog", "why", "Связь запасов с инвестиционными программами: неиспользованные запасы относительно исполнения",
                           "По проектам направлений: использовано, остаток, оставшаяся потребность, прогноз остатка на завершение",
                           chart=bar(byd.direction_name.tolist(), [dict(name="Использовано", data=byd.used.tolist()), dict(name="Остаток на складе", data=byd.stock.tolist()),
                                                                   dict(name="Оставшаяся потребность", data=byd.future.tolist()),
                                                                   dict(name="Прогноз невостребованного остатка", data=byd.leftover.tolist(), color="bad")])))
    prog = engine.aggregate(ctx, ["program", "dgroup"], parts=("snap",))
    sec.append(section("dc", "action", "Контроль двойного счёта: программы × CAPEX/OPEX",
                       f"Газовая программа — признак проекта; запасы учитываются в направлении один раз. Σ по таблице = {rub(prog.stock_end.sum())} = итог периметра {rub(tot)}",
                       table=table(prog, [col("program_label", "Программа"), col("dgroup_label", "Группа"), col("stock_end", "Запасы", "money"),
                                          col("nez_end", "НЭЗ", "money")], total=True)))
    grow = a[(a.stock_delta > 0) & (a.receipts > a.consumption)].sort_values("stock_delta", ascending=False)
    grow["rec"] = np.where(grow.direction_group == "CAPEX", "Сверить график поставок с графиком работ проектов (витрины 8–10)",
                           "Сверить план потребности и параметры пополнения (витрина 13)")
    sec.append(section("act", "action", "Направления, где поступления опережают потребление", None,
                       table=table(grow, [col("direction_label", "Направление"), col("stock_delta", "Прирост", "money"), col("receipts", "Поступление", "money"),
                                          col("consumption", "Потребление", "money"), col("rec", "Рекомендация")], drill={"dim": "direction", "key": "direction"})))
    return dict(kpis=kpis, sections=sec)


# ======================================================================================
def v07(ctx: Ctx, opts: dict) -> dict:
    a = engine.aggregate(ctx, ["service"])
    extra = db.q(f"""
    SELECT COALESCE(service_id,'—') service,
      SUM(CASE WHEN direction_id IN ('D07','D08') THEN value ELSE 0 END) repair_stock,
      SUM(CASE WHEN direction_id IN ('D07','D08') THEN noissue_value ELSE 0 END) repair_unused,
      SUM(CASE WHEN fut_need = 0 AND NOT nez_protected THEN value ELSE 0 END) no_need,
      SUM(CASE WHEN analog_group IS NOT NULL THEN free_value ELSE 0 END) analog_free
    FROM snap WHERE m={ctx.m2} AND on_balance AND {ctx.where()} GROUP BY 1""")
    a = a.merge(extra, on="service", how="left").fillna({"repair_stock": 0, "repair_unused": 0, "no_need": 0, "analog_free": 0})
    a["crit_share"] = a.crit_end / a.stock_end.replace(0, np.nan) * 100
    a = a.sort_values("stock_end", ascending=False)
    kpis = [kpi("svc", "Служб в периметре", len(a), "count"), kpi("crit", "Критический ЗИП", a.crit_end.sum()),
            kpi("repair_unused", "Неиспользуемые ремонтные запасы", a.repair_unused.sum(), hib=False, note="Ремонтные направления (Капремонт, РЭН) без потребления ≥ порога"),
            kpi("no_need", "Без подтверждённой потребности", a.no_need.sum(), hib=False, note="Страховой запас и критичные МТР исключены")]
    sec = []
    sec.append(section("tbl", "what", "Запасы технических служб", "Служба не признаётся неэффективной только из-за более высокой стоимости запасов — учитывайте долю критичных МТР",
                       table=table(a, [col("service_label", "Служба"), col("stock_end", "Запасы", "money"), col("nez_end", "НЭЗ", "money"),
                                       col("crit_end", "Критичный ЗИП", "money"), col("crit_share", "Доля критичных", "pct"),
                                       col("turnover_days", "Оборач., дн.", "days"), col("consumption", "Потребление", "money"),
                                       col("repair_stock", "Для ремонтных программ", "money"), col("repair_unused", "Неисп. ремонтные", "money"),
                                       col("no_need", "Без подтв. потребности", "money"), col("analog_free", "Своб. запас с аналогами", "money")],
                                   drill={"dim": "service", "key": "service"}, total=True), span=2))
    st = a.copy()
    sec.append(section("struct", "where", "Структура запасов служб: эффективная часть, НЭЗ, критичные МТР", None,
                       chart=bar(st.service_label.tolist()[::-1], [dict(name="Критичные МТР", data=st.crit_end.tolist()[::-1]),
                                                                   dict(name="НЭЗ", data=st.nez_end.tolist()[::-1], color="bad"),
                                                                   dict(name="Прочие", data=(st.stock_end - st.crit_end - st.nez_end).clip(lower=0).tolist()[::-1])],
                                 horizontal=True, stacked=True)))
    hm = opt(opts, "hm", "nez_share")
    xs, ys, vals = _hm(ctx, "service", "company", hm)
    u = dict((m, x) for m, _, x in HM_METRICS)[hm]
    sec.append(section("heat", "where", "Служба × общество", None, chart=heatmap(xs, ys, vals, unit=u, diverging=(hm == "stock_delta")),
                       controls=[control("hm", "Показатель", [(m, l) for m, l, _ in HM_METRICS], hm)], span=2))
    pts = [dict(name=r.service_label, x=r.turnover_days if r.turnover_days == r.turnover_days else None, y=r.nez_share, size=r.stock_end,
                group=("Высокая доля критичных (>40%)" if (r.crit_share or 0) > 40 else "Прочие")) for r in a.itertuples() if r.stock_end > 0]
    sec.append(section("matrix", "why", "Сравнительная матрица эффективности служб", "X — оборачиваемость, Y — доля НЭЗ, размер — запасы; цвет — эксплуатационный риск (доля критичных)",
                       chart=scatter(pts, "Оборачиваемость, дн.", "Доля НЭЗ, %", "days", "pct", "Запасы",
                                     groups=["Высокая доля критичных (>40%)", "Прочие"])))
    svc = opt(opts, "svc", "SV01")
    eq = db.q(f"SELECT company_id, SUM(units) units FROM equipment GROUP BY 1")
    sc = engine.aggregate(ctx.with_filters(service=[svc]), ["company"], parts=("snap", "mov"))
    sc = sc.merge(eq, left_on="company", right_on="company_id", how="left")
    sc["per_unit"] = sc.stock_end / sc.units.replace(0, np.nan)
    svcs = db.q("SELECT service_id, service_name FROM services")
    sec.append(section("peer", "why", "Различия между обществами с сопоставимыми активами",
                       "Запасы службы на единицу оборудования (демо-нормализация по реестру оборудования). Сопоставимость активов требует проверки.",
                       chart=bar(sc.company_label.tolist(), [dict(name="Запасы на ед. оборудования", data=sc.per_unit.tolist())]),
                       controls=[control("svc", "Служба", list(zip(svcs.service_id, svcs.service_name)), svc)]))
    un = db.q(f"""SELECT service_name, analog_group, COUNT(DISTINCT material_id) codes, SUM(value) value, SUM(free_value) free_value
                 FROM snap WHERE m={ctx.m2} AND on_balance AND analog_group IS NOT NULL AND qty > 0 AND {ctx.where()}
                 GROUP BY 1,2 HAVING COUNT(DISTINCT material_id) >= 2 ORDER BY value DESC LIMIT 60""")
    sec.append(section("unif", "action", "Возможности унификации и замены аналогами", "Группы аналогов с запасом под несколькими кодами — предложения на техническую проверку",
                       table=table(un, [col("service_name", "Служба"), col("analog_group", "Группа аналогов"), col("codes", "Кодов с остатком", "int"),
                                        col("value", "Запасы", "money"), col("free_value", "Свободный", "money")])))
    return dict(kpis=kpis, sections=sec)


# ======================================================================================
def _project_sections(ctx: Ctx, title_scope: str, pt: pd.DataFrame, sec: list):
    if pt.empty:
        sec.append(section("empty", "what", f"Нет проектов {title_scope} в выбранном периметре", None))
        return
    items = [dict(name=f"{r.project_name} ({r.company_name})", start=int(r.start_m), end=int(r.end_m), rev_end=int(r.revised_end_m),
                  progress=r.progress, status=r.status, event=int(r.event_m) if r.event_m == r.event_m and r.event_m is not None else None)
             for r in pt.sort_values("start_m").itertuples()]
    sec.append(section("timeline", "what", "Временная шкала проектов: плановое и актуальное окончание, статус",
                       "Пунктир — смещение графика; вертикальная линия — дата среза",
                       chart=gantt(items, db.month_label(ctx.m2), labels=[db.month_label(m) for m in range(0, 70)], now_m=ctx.m2), span=2))


def v08(ctx: Ctx, opts: dict) -> dict:
    c = _restrict(ctx, "direction", ["D02", "D03", "D04"])
    k = engine.kpis(c)
    pt = project_table(c)
    stop = pt[pt.status.isin(["Перенесён", "Отменён"])] if len(pt) else pt
    kpis = [kpi("stock", "Запасы бурения, ОНСС, ГРР", k["stock_end"], sub=f"изменение {rub(k['stock_delta'])}"),
            kpi("completed", "Остатки по завершённым проектам", pt[pt.status == "Завершён"].stock.sum() if len(pt) else 0, hib=False),
            kpi("stopped", "Запасы по перенесённым/отменённым", stop.stock.sum() if len(stop) else 0, hib=False),
            kpi("open_po", "Открытые заказы", k["open_po"], sub=f"по перенесённым/отменённым {rub(stop.open_po.sum() if len(stop) else 0)}"),
            kpi("coverage", "Обеспеченность будущих операций", (pt.stock.sum() + pt.open_po.sum()) / pt.future_need.sum() * 100 if len(pt) and pt.future_need.sum() else None, "pct",
                note="(Запас + открытые заказы) / оставшаяся плановая потребность")]
    sec = []
    _project_sections(c, "бурения/ГРР", pt, sec)
    obj = db.q(f"""SELECT project_name, object_name, company_name, project_status, SUM(value) value, SUM(nez_value) nez FROM snap
                  WHERE m={c.m2} AND on_balance AND object_id IS NOT NULL AND {c.where()} GROUP BY 1,2,3,4 HAVING SUM(value) > 0 ORDER BY value DESC""")
    sec.append(section("obj", "where", "Запасы по проектам и скважинам", None,
                       table=table(obj, [col("project_name", "Проект"), col("object_name", "Скважина / объект"), col("company_name", "Общество"),
                                         col("project_status", "Статус", "status"), col("value", "Запасы", "money"), col("nez", "НЭЗ", "money")], total=True)))
    if len(pt):
        sec.append(section("need", "why", "Потребность против наличия по проектам", None,
                           chart=bar(pt.project_name.tolist(), [dict(name="Запас", data=pt.stock.tolist()), dict(name="Открытые заказы", data=pt.open_po.tolist()),
                                                                dict(name="Оставшаяся потребность", data=pt.future_need.tolist())]),
                           table=table(pt, [col("project_name", "Проект"), col("company_name", "Общество"), col("status", "Статус", "status"),
                                            col("stage", "Стадия"), col("stock", "Запас", "money"), col("open_po", "Заказы", "money"),
                                            col("future_need", "Оставш. потребность", "money"), col("leftover_forecast", "Риск невостребованности", "money")], total=True), span=2))
    shifted = db.q(f"""SELECT po_id, company_name, project_name, project_status, material_name, po_value, planned_delivery, need_date,
                      date_diff('day', planned_delivery, need_date) gap_days
                      FROM v_po WHERE order_date <= (SELECT month_end FROM cal WHERE m={c.m2}) AND actual_delivery > (SELECT month_end FROM cal WHERE m={c.m2})
                      AND (project_status IN ('Перенесён','Отменён') OR date_diff('day', planned_delivery, need_date) > 90) AND {c.where()}
                      ORDER BY po_value DESC""")
    sec.append(section("shift", "risk", f"График потребления перенесён — обязательства сохранились: {len(shifted)} заказов на {rub(shifted.po_value.sum())}",
                       "Открытые заказы по перенесённым/отменённым работам или с потребностью позже поставки > 90 дн.",
                       table=table(shifted, [col("po_id", "Заказ"), col("company_name", "Общество"), col("project_name", "Проект"), col("project_status", "Статус", "status"),
                                             col("material_name", "МТР"), col("po_value", "Стоимость", "money"), col("planned_delivery", "Поставка", "date"),
                                             col("need_date", "Потребность", "date"), col("gap_days", "Разрыв, дн.", "int")], total=True), span=2))
    reuse = db.q(f"""
    WITH left_ AS (SELECT material_id, material_name, company_name, project_name, SUM(free_qty) q, SUM(free_value) v FROM snap
                   WHERE m={c.m2} AND on_balance AND project_status IN ('Завершён','Отменён','Перенесён') AND free_qty > 0 AND {c.where()} GROUP BY 1,2,3,4),
    need AS (SELECT v.material_id, SUM(d.plan_qty) nq, string_agg(DISTINCT v.project_name, '; ') projects FROM demand d JOIN v_pos v USING (position_id)
             WHERE d.m BETWEEN {c.m2 + 1} AND {c.m2 + 12} AND v.project_status IN ('В графике') AND {c.access_clause('v')} GROUP BY 1)
    SELECT l.*, n.nq, n.projects FROM left_ l JOIN need n USING (material_id) ORDER BY v DESC""")
    sec.append(section("reuse", "action", f"Возможность использования на других объектах: {rub(reuse.v.sum())}",
                       "Свободные остатки завершённых/остановленных проектов при потребности активных проектов (12 мес.) — до закупки проверить их применение",
                       table=table(reuse, [col("material_name", "МТР"), col("company_name", "Общество"), col("project_name", "Проект-источник"),
                                           col("q", "Свободно", "num"), col("v", "Стоимость", "money"), col("nq", "Потребность др. проектов", "num"),
                                           col("projects", "Проекты-получатели")], total=True), span=2))
    return dict(kpis=kpis, sections=sec)


def v09(ctx: Ctx, opts: dict) -> dict:
    c = _restrict(ctx, "direction", ["D01", "D05", "D06"])
    pt = project_table(c)
    if pt.empty:
        return dict(kpis=[], sections=[section("empty", "what", "Нет инвестиционных проектов в периметре", None)])
    done = pt[pt.status == "Завершён"]
    kpis = [kpi("stock", "Запасы инвестиционных проектов", pt.stock.sum()), kpi("purchased", "Закуплено (накопленно)", pt.purchased.sum()),
            kpi("received", "Получено", pt.received.sum()), kpi("used", "Использовано", pt.used.sum()),
            kpi("open_po", "Открытые обязательства", pt.open_po.sum()), kpi("reserved", "Резервы", pt.reserved.sum()),
            kpi("leftover_done", "Неиспользованные остатки завершённых проектов", done.stock.sum(), hib=False),
            kpi("leftover_fc", "Прогноз остатков на завершение (активные)", pt[pt.status != "Завершён"].leftover_forecast.sum(), hib=False,
                note="Σ max(0, запас + открытые заказы − оставшаяся потребность) × цена")]
    sec = []
    _project_sections(c, "капстроительства", pt, sec)
    sec.append(section("tbl", "where", "Портфель проектов: закуплено / получено / использовано / остаток", None,
                       table=table(pt.sort_values("stock", ascending=False), [
                           col("project_name", "Проект"), col("company_name", "Общество"), col("program", "Программа"), col("stage", "Стадия"),
                           col("status", "Статус", "status"), col("progress", "Прогресс (по сроку)", "pct"), col("purchased", "Закуплено", "money"),
                           col("received", "Получено", "money"), col("used", "Использовано", "money"), col("stock", "Остаток", "money"),
                           col("reserved", "Резерв", "money"), col("open_po", "Обязательства", "money"), col("leftover_forecast", "Прогноз остатка", "money")],
                           drill={"dim": "project", "key": "project_id"}, total=True), span=2))
    pts = [dict(name=r.project_name, x=r.progress if r.progress == r.progress else 0, y=r.readiness, size=max(r.leftover_forecast, 1), group=r.status)
           for r in pt.itertuples()]
    sec.append(section("matrix", "why", "Матрица «Прогресс проекта × Готовность МТР × Стоимость остатка»",
                       "Готовность МТР = (использовано + на складе) / (использовано + оставшаяся потребность); > 100% — избыточное обеспечение",
                       chart=scatter(pts, "Прогресс проекта (по сроку), %", "Готовность МТР, %", "pct", "pct", "Прогноз остатка",
                                     groups=["В графике", "Перенесён", "Отменён", "Изменено техническое решение", "Завершён"], hline=100)))
    mism = db.q(f"""SELECT project_name, company_name, project_status, material_name, SUM(value) value, SUM(fut_need) fut_need FROM snap
                   WHERE m={c.m2} AND on_balance AND project_id IS NOT NULL AND (project_status IN ('Изменено техническое решение','Отменён') OR
                   (project_status='Завершён' AND qty > 0)) AND {c.where()} GROUP BY 1,2,3,4 HAVING SUM(value) > 0 ORDER BY value DESC LIMIT 100""")
    sec.append(section("mism", "risk", f"Запасы, не соответствующие актуальной проектной потребности: {rub(mism.value.sum())}",
                       "Завершённые проекты, изменение технических решений, отмена работ",
                       table=table(mism, [col("project_name", "Проект"), col("project_status", "Статус", "status"), col("material_name", "МТР"),
                                          col("value", "Стоимость", "money")], total=True)))
    chg = pt[pt.revised_end_m != pt.end_m]
    sec.append(section("sched", "risk", f"Изменения графиков строительства: {len(chg)} проектов", None,
                       table=table(chg, [col("project_name", "Проект"), col("plan_end", "План. окончание"), col("rev_end", "Актуальное"), col("stock", "Запасы", "money"),
                                         col("open_po", "Обязательства", "money")])))
    reuse = db.q(f"""
    WITH left_ AS (SELECT material_id, material_name, project_name, company_name, SUM(free_value) v, SUM(free_qty) q FROM snap
                   WHERE m={c.m2} AND on_balance AND project_status IN ('Завершён','Изменено техническое решение','Отменён') AND free_qty>0 AND {c.where()} GROUP BY 1,2,3,4),
    need AS (SELECT v.material_id, string_agg(DISTINCT v.project_name, '; ') projects, SUM(d.plan_qty) nq FROM demand d JOIN v_pos v USING (position_id)
             WHERE d.m > {c.m2} AND v.project_status='В графике' AND {c.access_clause('v')} GROUP BY 1)
    SELECT l.*, n.projects, n.nq FROM left_ l JOIN need n USING (material_id) ORDER BY v DESC""")
    sec.append(section("reuse", "action", f"Возможности использования в других проектах: {rub(reuse.v.sum())}", None,
                       table=table(reuse, [col("material_name", "МТР"), col("project_name", "Проект-источник"), col("company_name", "Общество"),
                                           col("v", "Свободный остаток", "money"), col("projects", "Проекты с потребностью")], total=True), span=2))
    return dict(kpis=kpis, sections=sec)


def v10(ctx: Ctx, opts: dict) -> dict:
    c = ctx.with_filters(program=["Газовая программа"])
    k = engine.kpis(c)
    grp = engine.kpis(ctx.with_filters(program=None))
    pt = project_table(c)
    post = pt[pt.status == "Перенесён"] if len(pt) else pt
    kpis = [kpi("stock", "Запасы газовой программы", k["stock_end"], sub=f"доля в периметре {pct(k['stock_end'] / grp['stock_end'] * 100 if grp['stock_end'] else None)}"),
            kpi("delta", "Изменение за период", k["stock_delta"], hib=False), kpi("nez", "НЭЗ", k["nez_end"], hib=False, sub=f"доля {pct(k['nez_share'])}"),
            kpi("open_po", "Открытые обязательства", k["open_po"]), kpi("post", "Остатки перенесённых проектов", post.stock.sum() if len(post) else 0, hib=False),
            kpi("coverage", "Обеспеченность потребности", (pt.stock.sum() + pt.open_po.sum()) / pt.future_need.sum() * 100 if len(pt) and pt.future_need.sum() else None, "pct")]
    sec = []
    s = engine.series(c, [], max(1, c.m2 - 23), c.m2)
    sec.append(section("dyn", "what", f"Запасы газовой программы: {rub(k['stock_start'])} → {rub(k['stock_end'])}", None,
                       chart=line(s.label.tolist(), [dict(name="Запасы", data=s.stock.tolist(), area=True), dict(name="НЭЗ", data=s.nez.tolist(), color="bad"),
                                                     dict(name="Поступление", data=s.receipts.tolist(), type="bar", muted=True)]), span=2))
    dc = engine.aggregate(c, ["direction"], parts=("snap",))
    sec.append(section("dc", "what", "Включение в CAPEX/OPEX-аналитику без двойного счёта",
                       f"Запасы программы распределены по направлениям: Σ = {rub(dc.stock_end.sum())} (совпадает с итогом программы)",
                       table=table(dc, [col("direction_label", "Направление"), col("stock_end", "Запасы", "money"), col("nez_end", "НЭЗ", "money")], total=True)))
    obj = db.q(f"""SELECT project_name, object_name, company_name, SUM(value) value FROM snap WHERE m={c.m2} AND on_balance AND {c.where()}
                  GROUP BY 1,2,3 HAVING SUM(value) > 0 ORDER BY value DESC""")
    sec.append(section("obj", "where", "Распределение по объектам", None, table=table(obj, [col("project_name", "Проект"), col("object_name", "Объект"),
                                                                                          col("company_name", "Общество"), col("value", "Запасы", "money")], total=True)))
    cl = engine.aggregate(c, ["mclass"], parts=("snap",)).sort_values("stock_end", ascending=False)
    cl["kind"] = np.where(cl.mclass_label.str.contains("Труб"), "Трубная продукция", np.where(cl.mclass_label.str.contains("оборудован|Электро|Компрессор|Насос"),
                                                                                              "Оборудование", "Прочие МТР"))
    kk = cl.groupby("kind").stock_end.sum()
    sec.append(section("cls", "where", "Оборудование и трубная продукция", f"Оборудование {rub(kk.get('Оборудование', 0))} · трубы {rub(kk.get('Трубная продукция', 0))}",
                       chart=bar(cl.mclass_label.tolist(), [dict(name="Запасы", data=cl.stock_end.tolist())], horizontal=True)))
    if len(pt):
        _project_sections(c, "газовой программы", pt, sec)
        stg = pt.groupby("stage").agg(stock=("stock", "sum"), open_po=("open_po", "sum"), need=("future_need", "sum")).reset_index()
        sec.append(section("stage", "why", "Запасы по этапам газовых проектов; потребность и обеспеченность", None,
                           chart=bar(stg.stage.tolist(), [dict(name="Запас", data=stg.stock.tolist()), dict(name="Обязательства", data=stg.open_po.tolist()),
                                                          dict(name="Оставшаяся потребность", data=stg.need.tolist())])))
    far = db.q(f"""
    WITH fn AS (SELECT position_id, MIN(m) fm FROM demand WHERE m > {c.m2} AND plan_qty > 0 GROUP BY 1)
    SELECT s.position_id, company_name, project_name, project_status, material_name, price, value, last_receipt_date,
           CASE WHEN fn.fm IS NULL THEN NULL ELSE date_diff('day', last_receipt_date, (SELECT month_start FROM cal WHERE m = fn.fm)) END days_receipt_to_need
    FROM snap s LEFT JOIN fn USING (position_id)
    WHERE s.m={c.m2} AND s.on_balance AND s.price > 1e6 AND s.qty > 0 AND {c.where('s')}
      AND (fn.fm IS NULL OR date_diff('day', last_receipt_date, (SELECT month_start FROM cal WHERE m = fn.fm)) > 365)
    ORDER BY value DESC""")
    sec.append(section("far", "risk", f"Дорогостоящее оборудование с отдалённым сроком востребования: {rub(far.value.sum())}",
                       "Цена > 1 млн ₽; срок от поступления до ближайшей плановой потребности > 365 дн. или потребность отсутствует",
                       table=table(far, [col("material_name", "МТР"), col("company_name", "Общество"), col("project_name", "Проект"), col("project_status", "Статус", "status"),
                                         col("value", "Стоимость", "money"), col("last_receipt_date", "Поступление", "date"),
                                         col("days_receipt_to_need", "Дней до потребности", "int")], row_key="position_id", total=True), span=2))
    from .v16 import redistribution_candidates
    rc = redistribution_candidates(c)
    sec.append(section("redist", "action", f"Перспективы вовлечения и перераспределения: {rub(rc.value.sum() if len(rc) else 0)}", None,
                       table=table(rc, [col("material_name", "МТР"), col("source_company", "Источник"), col("target_company", "Получатель"),
                                        col("value", "Стоимость", "money"), col("approval", "Согласование")]) if len(rc) else None))
    return dict(kpis=kpis, sections=sec)


# ======================================================================================
def duplicates(ctx: Ctx | None = None) -> pd.DataFrame:
    acc = ctx.access_clause("s") if ctx else "1=1"
    return db.q(f"""
    WITH m AS (SELECT material_id, nsi_code, material_name, manufacturer, model, mclass,
               lower(regexp_replace(trim(material_name), '\\s+', ' ', 'g')) nn FROM materials),
    d AS (SELECT nn, manufacturer, model FROM m GROUP BY 1,2,3 HAVING COUNT(*) > 1),
    st AS (SELECT material_id, SUM(value) v FROM snap s WHERE m=(SELECT max(m) FROM snap) AND on_balance AND {acc} GROUP BY 1)
    SELECT m.nn AS norm_name, m.manufacturer, m.model, m.mclass, string_agg(m.nsi_code, ', ') codes, COUNT(*) n_codes, SUM(COALESCE(st.v,0)) stock
    FROM m JOIN d USING (nn, manufacturer, model) LEFT JOIN st USING (material_id)
    GROUP BY 1,2,3,4 ORDER BY stock DESC""")


def v11(ctx: Ctx, opts: dict) -> dict:
    a = engine.aggregate(ctx, ["mclass"])
    items = db.q(f"""SELECT mclass, COUNT(DISTINCT CASE WHEN m={ctx.m1 - 1} AND qty>0 THEN material_id END) n_start,
                    COUNT(DISTINCT CASE WHEN m={ctx.m2} AND qty>0 THEN material_id END) n_end FROM snap
                    WHERE m IN ({ctx.m1 - 1},{ctx.m2}) AND on_balance AND {ctx.where()} GROUP BY 1""")
    conc = db.q(f"""SELECT mclass, value FROM (SELECT mclass, material_id, SUM(value) value FROM snap WHERE m={ctx.m2} AND on_balance AND {ctx.where()} GROUP BY 1,2)""")
    cc = []
    for cl, g in conc.groupby("mclass"):
        v = g.value.sort_values(ascending=False)
        n = max(1, int(np.ceil(len(v) * 0.1)))
        cc.append((cl, v.head(n).sum() / v.sum() * 100 if v.sum() else None))
    a = a.merge(items, left_on="mclass", right_on="mclass", how="left").merge(pd.DataFrame(cc, columns=["mclass", "top10_share"]), on="mclass", how="left")
    a = a.sort_values("stock_end", ascending=False)
    dup = duplicates(ctx)
    kpis = [kpi("classes", "Классов МТР", len(a), "count"), kpi("items", "Номенклатурных позиций с остатком", int(a.n_end.sum()), "count",
                                                                  prev=int(a.n_start.sum())),
            kpi("dups", "Групп дублей НСИ", len(dup), "count", sub=f"запасы под дублями {rub(dup.stock.sum())}")]
    sec = []
    sec.append(section("tbl", "what", "Запасы по классам МТР", "Концентрация — доля 10% крупнейших позиций в стоимости класса",
                       table=table(a, [col("mclass_label", "Класс"), col("stock_end", "Запасы", "money"), col("stock_delta", "Изменение", "money"),
                                       col("nez_end", "НЭЗ", "money"), col("consumption", "Потребление", "money"), col("turnover_days", "Оборач., дн.", "days"),
                                       col("n_start", "Позиций на начало", "int"), col("n_end", "Позиций на конец", "int"), col("top10_share", "Концентрация", "pct")],
                                   drill={"dim": "mclass", "key": "mclass"}, total=True), span=2))
    s = engine.series(ctx, ["mclass"], max(1, ctx.m2 - 23), ctx.m2, flows=False)
    piv = s.pivot_table(index="m", columns="mclass_label", values="stock", aggfunc="sum").fillna(0)
    top_cls = piv.iloc[-1].sort_values(ascending=False).head(6).index
    sec.append(section("dyn", "what", "Динамика крупнейших классов", None,
                       chart=line([db.month_label(m) for m in piv.index], [dict(name=c_, data=piv[c_].tolist()) for c_ in top_cls])))
    tg = engine.aggregate(ctx, ["mclass", "mgroup"], parts=("snap",))
    nodes = [dict(name=c_, value=float(g.stock_end.sum()), children=[dict(name=r.mgroup_label, value=float(r.stock_end)) for r in g.itertuples() if r.stock_end > 0])
             for c_, g in tg.groupby("mclass_label")]
    sec.append(section("tree", "where", "Стоимость: класс → группа МТР", None, chart=treemap(nodes)))
    mat = db.q(f"""
    WITH f AS (SELECT position_id, COUNT(DISTINCT m) n_months FROM movements WHERE mtype='Потребление' AND m BETWEEN {ctx.m2 - 11} AND {ctx.m2} GROUP BY 1)
    SELECT s.material_id, ANY_VALUE(s.material_name) material_name, ANY_VALUE(s.criticality) criticality, ANY_VALUE(s.analog_group) analog_group,
           ANY_VALUE(s.analog_status) analog_status, SUM(s.value) value, MAX(COALESCE(f.n_months,0)) freq
    FROM snap s LEFT JOIN f USING (position_id) WHERE s.m={ctx.m2} AND s.on_balance AND s.qty > 0 AND {ctx.where('s')}
    GROUP BY 1 ORDER BY value DESC LIMIT 400""")
    pts = [dict(name=r.material_name, x=r.freq, y=r.value, size=r.value, group=r.criticality,
                symbol="diamond" if isinstance(r.analog_group, str) else "circle") for r in mat.itertuples()]
    sec.append(section("matrix", "why", "Матрица «Стоимость × Частота потребления × Критичность × Возможность унификации»",
                       "X — месяцев с потреблением из 12; цвет — критичность; ромб — есть группа аналогов (возможность унификации)",
                       chart=scatter(pts, "Месяцев с потреблением (из 12)", "Стоимость запаса", "num", "rub", "Стоимость",
                                     groups=["A — критичный", "B — важный", "C — стандартный"], ylog=True), span=2))
    sec.append(section("dups", "risk", f"Повторяющиеся позиции с разными кодами НСИ: {len(dup)} групп", "Совпадение нормализованного наименования, производителя и модели",
                       table=table(dup, [col("norm_name", "Наименование (нормализованное)"), col("manufacturer", "Производитель"), col("codes", "Коды НСИ"),
                                         col("n_codes", "Кодов", "int"), col("stock", "Запасы", "money")], total=True)))
    un = db.q(f"""
    WITH g AS (SELECT s.material_id, s.analog_group, ANY_VALUE(s.analog_status) st, SUM(GREATEST(s.free_qty - s.fut_need_12,0) * s.price) surplus,
                      SUM(GREATEST(s.fut_need_12 - s.free_qty,0) * s.price) gap FROM snap s
               WHERE s.m={ctx.m2} AND s.on_balance AND s.analog_group IS NOT NULL AND {ctx.where('s')} GROUP BY 1,2)
    SELECT analog_group, ANY_VALUE(st) analog_status, COUNT(*) codes, SUM(surplus) surplus, SUM(gap) gap, LEAST(SUM(surplus), SUM(gap)) potential
    FROM g GROUP BY 1 HAVING SUM(surplus) > 0 AND SUM(gap) > 0 ORDER BY potential DESC""")
    un["proposal"] = np.where(un.analog_status == "Подтверждён", "Использовать запас аналога вместо закупки",
                              "Предложение на техническую проверку взаимозаменяемости (не подтверждено)")
    sec.append(section("unif", "action", f"Потенциал унификации: {rub(un.potential.sum())}",
                       "Внутри группы аналогов: излишек одних кодов при непокрытой потребности других. Алгоритм только формирует предложения.",
                       table=table(un, [col("analog_group", "Группа аналогов"), col("analog_status", "Статус"), col("codes", "Кодов", "int"),
                                        col("surplus", "Излишек", "money"), col("gap", "Непокрытая потребность", "money"), col("potential", "Потенциал", "money"),
                                        col("proposal", "Предложение")], total=True), span=2))
    return dict(kpis=kpis, sections=sec)


def hierarchy(ctx: Ctx, path: list[tuple[str, str]], level: str) -> dict:
    c = ctx.with_filters(**{d: [v] for d, v in path})
    a = engine.aggregate(c, [level], parts=("snap", "mov", "nez")).sort_values("stock_end", ascending=False)
    tot = a.stock_end.sum()
    a["share"] = a.stock_end / tot * 100 if tot else 0
    return table(a, [col(f"{level}_label", DIMENSIONS[level][2]), col("stock_end", "Запасы", "money"), col("share", "Доля", "pct"),
                     col("stock_delta", "Изменение", "money"), col("nez_end", "НЭЗ", "money"), col("nez_share", "Доля НЭЗ", "pct"),
                     col("consumption", "Потребление", "money"), col("turnover_days", "Оборач., дн.", "days")], drill={"dim": level, "key": level}, total=True)
