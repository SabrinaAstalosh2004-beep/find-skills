"""Контроль качества данных (вкладка витрины 20)."""
from __future__ import annotations

import pandas as pd

from . import db
from .filters import Ctx


def _chk(id_, group, name, severity, df: pd.DataFrame, description, cols=None, total=None):
    n = int(len(df))
    return dict(id=id_, group=group, check=name, severity=severity, count=n, status="OK" if n == 0 else ("Ошибка" if severity == "Высокая" else "Предупреждение"),
                description=description, total=total,
                sample=[{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()} for r in df.head(15)[cols or list(df.columns)].to_dict("records")])


def run(ctx: Ctx) -> dict:
    acc = ctx.access_clause("v")
    out = []
    out.append(_chk("pk_pos", "Уникальность ключей", "Уникальность позиций учёта", "Высокая",
                    db.q("SELECT position_id, COUNT(*) n FROM positions GROUP BY 1 HAVING COUNT(*) > 1"), "position_id уникален"))
    out.append(_chk("pk_snap", "Уникальность ключей", "Один остаток на позицию и дату", "Высокая",
                    db.q("SELECT position_id, m, COUNT(*) n FROM snapshot GROUP BY 1,2 HAVING COUNT(*) > 1"), "Пара (позиция, месяц) уникальна"))
    out.append(_chk("pk_nsi", "Уникальность ключей", "Уникальность кодов НСИ", "Высокая",
                    db.q("SELECT nsi_code, COUNT(*) n FROM materials GROUP BY 1 HAVING COUNT(*) > 1"), "Код НСИ уникален"))
    out.append(_chk("pk_po", "Уникальность ключей", "Уникальность номеров заказов", "Высокая",
                    db.q("SELECT po_id, COUNT(*) n FROM purchase_orders GROUP BY 1 HAVING COUNT(*) > 1"), "Номер заказа уникален"))
    a = db.q(f"SELECT SUM(value) v FROM snap WHERE m={ctx.m2} AND on_balance").v.iloc[0]
    b = db.q(f"SELECT SUM(v) v FROM (SELECT direction_id, SUM(value) v FROM snap WHERE m={ctx.m2} AND on_balance GROUP BY 1)").v.iloc[0]
    c = db.q(f"SELECT SUM(v) v FROM (SELECT program, direction_group, SUM(value) v FROM snap WHERE m={ctx.m2} AND on_balance GROUP BY 1,2)").v.iloc[0]
    dd = pd.DataFrame([dict(total=a, by_direction=b, by_program_group=c)])
    bad = dd[(abs(dd.total - dd.by_direction) > 1) | (abs(dd.total - dd.by_program_group) > 1)]
    out.append(_chk("double", "Отсутствие двойного счёта", "Итог = Σ по направлениям = Σ по программам × группам", "Высокая", bad,
                    f"Итог {a:,.0f}; по направлениям {b:,.0f}; по программам {c:,.0f}".replace(",", " ")))
    out.append(_chk("units", "Единицы измерения", "Единица в движении не совпадает с единицей НСИ", "Средняя",
                    db.q(f"""SELECT mv.position_id, mv.date, mv.mtype, mv.unit mov_unit, v.unit nsi_unit, v.material_name FROM movements mv JOIN v_pos v USING (position_id)
                            WHERE mv.unit IS NOT NULL AND mv.unit <> v.unit AND {acc}"""), "Документы движения с иной единицей измерения требуют пересчёта"))
    out.append(_chk("cur", "Корректность валют", "Заказы в валюте без пересчёта в рубли", "Средняя",
                    db.q(f"SELECT po_id, company_name, material_name, currency, po_value FROM v_po v WHERE currency <> 'RUB' AND {acc}"),
                    "Исключены из стоимостных показателей заказов до пересчёта по курсу"))
    rec = db.q(f"""
    WITH mv AS (SELECT position_id, m, SUM(CASE WHEN mtype IN ('Потребление','Перемещение (расход)','Реализация','Списание') THEN -qty
                                               WHEN mtype='Переоценка' THEN 0 ELSE qty END) dq FROM movements GROUP BY 1,2),
    s AS (SELECT position_id, m, qty, LAG(qty) OVER (PARTITION BY position_id ORDER BY m) pq FROM snapshot)
    SELECT s.position_id, v.company_name, v.material_name, s.m, s.pq qty_open, COALESCE(mv.dq,0) movements, s.qty qty_close,
           s.qty - s.pq - COALESCE(mv.dq,0) diff
    FROM s LEFT JOIN mv USING (position_id, m) JOIN v_pos v USING (position_id)
    WHERE s.pq IS NOT NULL AND abs(s.qty - s.pq - COALESCE(mv.dq,0)) > 0.001 AND {acc}""")
    rec["month"] = rec.m.map(db.month_label)
    out.append(_chk("recon", "Сверка остатков с движениями", "Остаток на конец ≠ остаток на начало + движения", "Высокая", rec,
                    "Возможна ручная правка остатка без документа или неполная выгрузка движений",
                    ["position_id", "company_name", "material_name", "month", "qty_open", "movements", "qty_close", "diff"]))
    ret = db.q(f"""SELECT mv.position_id, v.material_name, mv.date, mv.qty FROM movements mv JOIN v_pos v USING (position_id)
                  WHERE mv.mtype='Возврат' AND {acc} AND NOT EXISTS (SELECT 1 FROM movements c WHERE c.position_id = mv.position_id AND c.mtype='Потребление'
                  AND c.m BETWEEN mv.m - 12 AND mv.m)""")
    out.append(_chk("returns", "Проверка возвратов", "Возврат без предшествующего отпуска (12 мес.)", "Средняя", ret, "Возврат должен соответствовать ранее отпущенным МТР"))
    tr = db.q("""SELECT m, SUM(CASE WHEN mtype='Перемещение (расход)' THEN value ELSE 0 END) out_v, SUM(CASE WHEN mtype='Перемещение (приход)' THEN value ELSE 0 END) in_v
                 FROM movements WHERE subtype='Межобщественное' GROUP BY 1 HAVING abs(out_v - in_v) > 1""")
    out.append(_chk("ic", "Межобщественные перемещения", "Расход у отправителя ≠ приход у получателя", "Высокая", tr, "Перемещения внутри группы должны взаимно исключаться"))
    out.append(_chk("reserve", "Проверка резервирования", "Резерв превышает остаток", "Средняя",
                    db.q(f"SELECT position_id, company_name, material_name, qty, reserved_qty FROM snap v WHERE m={ctx.m2} AND reserved_qty > qty + 0.001 AND {acc}"),
                    "В расчётах резерв ограничивается остатком"))
    rv = db.q(f"""WITH s AS (SELECT position_id, m, value, LAG(value) OVER (PARTITION BY position_id ORDER BY m) pv FROM snapshot)
                 SELECT mv.position_id, v.material_name, mv.m, mv.value reval, s.pv open_value FROM movements mv JOIN s USING (position_id, m) JOIN v_pos v USING (position_id)
                 WHERE mv.mtype='Переоценка' AND s.pv > 1e5 AND abs(mv.value) > 0.06 * s.pv AND {acc}""")
    out.append(_chk("reval", "Обработка переоценок", "Переоценка > 6% стоимости за месяц", "Низкая", rv, "Требует подтверждения изменения цены"))
    st = db.q(f"""SELECT po_id, company_name, material_name, planned_delivery, po_value FROM v_po v WHERE order_date <= (SELECT month_end FROM cal WHERE m={ctx.m2})
                 AND actual_delivery > (SELECT month_end FROM cal WHERE m={ctx.m2}) AND planned_delivery < (SELECT month_end FROM cal WHERE m={ctx.m2 - 4}) AND {acc}""")
    out.append(_chk("po_stale", "Проверка открытых заказов", "Открытые заказы с просрочкой > 120 дн. без обновления статуса", "Средняя", st,
                    "Требуется актуализация статуса или закрытие заказа"))
    out.append(_chk("mand", "Обязательные аналитики", "Не заполнена техническая служба", "Средняя",
                    db.q(f"SELECT position_id, company_name, material_name, direction_name FROM v_pos v WHERE service_id IS NULL AND {acc}"),
                    "Позиции без службы попадают в «(не указана)»"))
    out.append(_chk("neg", "Обязательные аналитики", "Отрицательные остатки", "Высокая",
                    db.q(f"SELECT position_id, m, qty FROM snapshot WHERE qty < 0"), "Отрицательный остаток недопустим"))
    from .vitrines.directions import duplicates
    du = duplicates(ctx)
    out.append(_chk("dups", "НСИ", "Дублирующиеся коды НСИ (одна позиция — разные коды)", "Средняя", du,
                    "Совпадение нормализованного наименования, производителя и модели", ["norm_name", "manufacturer", "codes", "n_codes", "stock"]))
    inj = db.q("SELECT issue, COUNT(*) n FROM dq_injected GROUP BY 1")
    sources = sources_status()
    return dict(checks=out, summary=dict(errors=sum(1 for c in out if c["status"] == "Ошибка"), warnings=sum(1 for c in out if c["status"] == "Предупреждение"),
                                         ok=sum(1 for c in out if c["status"] == "OK")),
                sources=sources, injected=inj.to_dict("records"),
                note="В демонстрационный набор намеренно внесены нарушения (таблица dq_injected) для проверки работы контролей.")


def sources_status() -> list[dict]:
    meta = db.meta()
    rows = []
    spec = [("snapshot", "Остатки МТР на отчётные даты", "m"), ("movements", "Движения МТР", "m"), ("materials", "НСИ МТР", None),
            ("companies", "Организационная структура", None), ("directions", "Направления деятельности", None), ("services", "Технические службы", None),
            ("demand", "Потребности и производственные программы", "m"), ("purchase_orders", "Заявки и заказы", None),
            ("projects", "Инвестиционные проекты", None), ("equipment", "Оборудование и надёжность (ТОиР)", None),
            ("repair_fund", "Ремонтный фонд", None), ("disposal", "Выбытие НВИ/НЛИ/НР/ВР", None), ("actions", "Мероприятия и результаты", None)]
    for t, name, mcol in spec:
        try:
            n = int(db.q(f"SELECT COUNT(*) n FROM {t}", cache=False).n.iloc[0])
            per = None
            if mcol:
                r = db.q(f"SELECT MIN({mcol}) a, MAX({mcol}) b FROM {t}").iloc[0]
                per = f"{db.month_label(int(r.a))} – {db.month_label(min(int(r.b), meta['last_closed_m']))}"
            rows.append(dict(table=t, name=name, rows=n, period=per, source=meta["source"], loaded_at=meta["loaded_at"],
                             completeness="100% (демо)" if n else "Нет данных", status="Загружено" if n else "Отсутствует"))
        except Exception:
            rows.append(dict(table=t, name=name, rows=0, period=None, source="—", loaded_at=None, completeness="Нет данных", status="Отсутствует"))
    return rows
