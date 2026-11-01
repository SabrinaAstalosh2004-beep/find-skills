"""Подключение DuckDB, загрузка набора данных и построение аналитических представлений.

Модель данных — «звезда»: позиции учёта (positions) связывают все таблицы фактов
(snapshot, movements, demand, purchase_orders, shortages, disposal, repair_fund) со справочниками.
Любой фильтр применяется к денормализованному представлению v_pos и, через него, ко всем фактам.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import threading

import duckdb
import pandas as pd

from . import settings as cfg
from .generator import N_MONTHS, days_in_month, month_end, month_start

DATA_DIR = cfg.DATA_DIR
DEMO_DIR = DATA_DIR / "demo"

TABLES = ["companies", "sites", "warehouses", "directions", "services", "suppliers", "materials", "positions",
          "projects", "objects", "snapshot", "opening", "movements", "demand", "purchase_orders", "shortages",
          "disposal", "repair_fund", "equipment", "activity", "finance", "dq_injected"]

MONTHS_RU = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]

_lock = threading.RLock()
_con: duckdb.DuckDBPyConnection | None = None
_meta: dict = {}


def month_label(m: int) -> str:
    s = month_start(m)
    return f"{MONTHS_RU[s.month - 1]} {s.year}"


def ensure_demo_data() -> None:
    if not (DEMO_DIR / "snapshot.parquet").exists():
        from .generator import generate, save
        save(generate(), DEMO_DIR)


def con() -> duckdb.DuckDBPyConnection:
    global _con
    with _lock:
        if _con is None:
            init()
        return _con


def cursor() -> duckdb.DuckDBPyConnection:
    """Курсор для конкурентных запросов (DuckDB-соединение не потокобезопасно)."""
    return con().cursor()


_cache: dict[str, pd.DataFrame] = {}


def q(sql: str, params: list | None = None, cache: bool = True) -> pd.DataFrame:
    """Выполнить запрос. Результаты кэшируются до перестроения представлений (смены правил/данных)."""
    key = sql + repr(params)
    if cache and key in _cache:
        return _cache[key].copy()
    c = cursor()
    try:
        df = c.execute(sql, params or []).df()
    finally:
        c.close()
    if cache:
        if len(_cache) > 3000:
            _cache.clear()
        _cache[key] = df
    return df.copy()


def clear_cache() -> None:
    _cache.clear()


def init(source_dir: pathlib.Path | None = None) -> None:
    global _con, _meta
    with _lock:
        src = source_dir or DEMO_DIR
        if src == DEMO_DIR:
            ensure_demo_data()
        c = duckdb.connect(":memory:")
        for t in TABLES:
            f = src / f"{t}.parquet"
            if f.exists():
                c.execute(f"CREATE TABLE {t} AS SELECT * FROM read_parquet('{f.as_posix()}')")
        # календарь
        cal = pd.DataFrame([dict(m=m, month_start=month_start(m), month_end=month_end(m), days=days_in_month(m),
                                 label=month_label(m), year=month_start(m).year,
                                 quarter=f"{month_start(m).year}-Q{(month_start(m).month - 1) // 3 + 1}")
                            for m in range(N_MONTHS + 30)])
        c.register("cal_df", cal)
        c.execute("CREATE TABLE cal AS SELECT * FROM cal_df")
        c.unregister("cal_df")
        _ensure_actions_table(c)
        _con = c
        _meta = dict(source="ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ (синтетический набор, seed фиксирован)", is_demo=src == DEMO_DIR,
                     loaded_at=dt.datetime.now().isoformat(timespec="seconds"), source_dir=str(src))
        build_views()


def meta() -> dict:
    con()
    c = cursor()
    try:
        last = c.execute("SELECT max(m) FROM snapshot").fetchone()[0]
    finally:
        c.close()
    return {**_meta, "last_closed_m": int(last), "last_closed_label": month_label(int(last)),
            "last_closed_date": month_end(int(last)).isoformat(), "first_m": 0}


def build_views() -> None:
    """(Пере)строит представления с учётом текущих настраиваемых правил отнесения."""
    s = cfg.get()
    nez = s["nez"]
    H = int(nez["need_horizon_months"])
    if H not in (3, 6, 12, 24):
        H = 12
    T = int(nez["no_issue_days"])
    pol = ",".join("'" + p.replace("'", "''") + "'" for p in nez["protected_policies"]) or "''"
    crit = ",".join("'" + p.replace("'", "''") + "'" for p in nez["protected_criticality"]) or "''"
    b = sorted(int(x) for x in s["age_buckets_days"])
    nocons = int(s["no_consumption_days"])

    def bucket(col: str) -> str:
        parts = []
        prev = 0
        for i, x in enumerate(b):
            parts.append(f"WHEN {col} < {x} THEN '{chr(65 + i)}. {prev}–{x} дн.'")
            prev = x
        parts.append(f"ELSE '{chr(65 + len(b))}. > {b[-1]} дн.'")
        return "CASE " + " ".join(parts) + " END"

    c = _con
    clear_cache()
    with _lock:
        c.execute("""
        CREATE OR REPLACE VIEW v_pos AS
        SELECT p.position_id, p.company_id, co.company_name, co.segment, co.ownership_type, co.region,
               w.site_id, si.site_name, si.branch, si.business_unit, p.warehouse_id, w.warehouse_name, w.cfo,
               p.direction_id, d.direction_name, d.direction_group, d.parent_id AS direction_parent,
               COALESCE(pr.program, 'Вне программ') AS program,
               p.service_id, COALESCE(sv.service_name, '(не указана)') AS service_name,
               p.material_id, mt.nsi_code, mt.material_name, mt.mclass, mt.mgroup, mt.msubgroup, mt.manufacturer,
               mt.model, mt.unit, mt.criticality, mt.repairable, mt.lead_days, mt.supplier_id, mt.proc_model,
               mt.analog_group, mt.analog_status, mt.equipment_model,
               p.project_id, pr.name AS project_name, pr.status AS project_status, pr.ptype AS project_type,
               p.object_id, ob.object_name,
               p.demand_type AS demand_type_raw,
               CASE WHEN p.demand_type IN ('regular') THEN 'Регулярный'
                    WHEN p.demand_type IN ('intermittent','zip_deficit','zip_surplus') THEN 'Нерегулярный'
                    WHEN p.demand_type = 'project' THEN 'Проектный' ELSE 'Без потребности' END AS demand_type,
               p.replenishment_policy, p.balance_ownership,
               p.balance_ownership = 'Собственный' AS on_balance
        FROM positions p
        JOIN companies co USING (company_id)
        JOIN warehouses w USING (warehouse_id)
        JOIN sites si ON si.site_id = w.site_id
        JOIN directions d USING (direction_id)
        LEFT JOIN services sv USING (service_id)
        JOIN materials mt USING (material_id)
        LEFT JOIN projects pr USING (project_id)
        LEFT JOIN objects ob USING (object_id)
        """)
        c.execute(f"""
        CREATE OR REPLACE VIEW v_snap_all AS
        SELECT s.m, s.qty, s.value, s.price, LEAST(s.reserved_qty, s.qty) AS reserved_qty_c, s.reserved_qty,
               s.unavailable_qty, s.last_receipt_date, s.last_issue_date,
               s.fut_need_{H} AS fut_need, s.fut_need_3, s.fut_need_6, s.fut_need_12,
               s.flag_nvi, s.flag_nli, s.flag_nr, s.flag_vr,
               cal.month_end,
               date_diff('day', COALESCE(s.last_issue_date, s.last_receipt_date, DATE '2019-01-01'), cal.month_end) AS days_no_issue,
               date_diff('day', COALESCE(s.last_receipt_date, DATE '2019-01-01'), cal.month_end) AS age_days,
               (v.replenishment_policy IN ({pol}) OR v.criticality IN ({crit})) AS nez_protected,
               v.*
        FROM snapshot s JOIN v_pos v USING (position_id) JOIN cal USING (m)
        """)
        c.execute(f"""
        CREATE OR REPLACE TABLE snap AS
        SELECT *,
               GREATEST(qty - reserved_qty_c - unavailable_qty, 0) AS free_qty,
               GREATEST(qty - reserved_qty_c - unavailable_qty, 0) * price AS free_value,
               reserved_qty_c * price AS reserved_value,
               unavailable_qty * price AS unavailable_value,
               CASE WHEN qty > 0 AND days_no_issue >= {T} AND NOT nez_protected
                    THEN GREATEST(qty - fut_need, 0) ELSE 0 END AS nez_qty,
               CASE WHEN qty > 0 AND days_no_issue >= {T} AND NOT nez_protected
                    THEN GREATEST(qty - fut_need, 0) * price ELSE 0 END AS nez_value,
               CASE WHEN qty > 0 AND days_no_issue >= {nocons} THEN value ELSE 0 END AS noissue_value,
               CASE WHEN qty > 0 AND days_no_issue >= {T} AND NOT nez_protected AND fut_need > 0
                    THEN LEAST(qty, fut_need) * price ELSE 0 END AS slow_with_need_value,
               {bucket('age_days')} AS age_bucket,
               {bucket('days_no_issue')} AS noissue_bucket,
               (flag_nvi OR flag_nli OR flag_nr OR flag_vr) AS special_flag
        FROM v_snap_all
        """)
        c.execute("""
        CREATE OR REPLACE VIEW v_mov AS
        SELECT mv.m, mv.date, mv.mtype, mv.subtype, mv.qty, mv.value, mv.po_id, v.*
        FROM movements mv JOIN v_pos v USING (position_id)
        """)
        c.execute("""
        CREATE OR REPLACE VIEW v_dem AS
        SELECT d.m, d.plan_init_qty, d.plan_qty, v.*
        FROM demand d JOIN v_pos v USING (position_id)
        """)
        c.execute("""
        CREATE OR REPLACE VIEW v_po AS
        SELECT po.po_id, po.req_date, po.order_date, po.qty AS po_qty, po.price AS po_price, po.value AS po_value,
               po.planned_delivery, po.actual_delivery, po.need_date, po.currency, po.supplier_id AS po_supplier_id,
               po.proc_model AS po_proc_model, sp.supplier_name, sp.base_reliability, v.* EXCLUDE (supplier_id, proc_model),
               v.supplier_id, v.proc_model
        FROM purchase_orders po JOIN v_pos v USING (position_id) LEFT JOIN suppliers sp ON sp.supplier_id = po.supplier_id
        """)
        _build_nez_flow(c)


def _build_nez_flow(c) -> None:
    """Помесячное разложение изменения НЭЗ на источники (точно сверяется с остатком НЭЗ)."""
    s = c.execute("SELECT position_id, m, qty, price, nez_qty FROM snap ORDER BY position_id, m").df()
    mv = c.execute("""SELECT position_id, m,
        SUM(CASE WHEN mtype='Потребление' THEN qty ELSE 0 END) c,
        SUM(CASE WHEN mtype='Перемещение (расход)' THEN qty ELSE 0 END) tout,
        SUM(CASE WHEN mtype='Реализация' THEN qty ELSE 0 END) sale,
        SUM(CASE WHEN mtype='Списание' THEN qty ELSE 0 END) wo
        FROM movements GROUP BY 1,2""").df()
    s = s.merge(mv, on=["position_id", "m"], how="left").fillna({"c": 0, "tout": 0, "sale": 0, "wo": 0})
    g = s.groupby("position_id", sort=False)
    s["nez_prev"] = g["nez_qty"].shift(1).fillna(0.0)
    s["price_prev"] = g["price"].shift(1)
    s["price_prev"] = s["price_prev"].fillna(s["price"])
    r = s["nez_prev"].to_numpy().copy()
    out = {}
    for k in ("c", "tout", "sale", "wo"):
        take = pd.Series(r).clip(upper=s[k].to_numpy()).clip(lower=0).to_numpy()
        out[k] = take
        r = r - take
    nez = s["nez_qty"].to_numpy()
    reclass = (r - nez).clip(min=0)
    new = (nez - r).clip(min=0)
    p = s["price"].to_numpy()
    flow = pd.DataFrame({
        "position_id": s["position_id"], "m": s["m"],
        "nez_open": s["nez_prev"] * s["price_prev"], "nez_close": nez * p,
        "nez_reval": s["nez_prev"] * (s["price"] - s["price_prev"]),
        "nez_consumed": out["c"] * p, "nez_transferred": out["tout"] * p, "nez_sold": out["sale"] * p,
        "nez_written_off": out["wo"] * p, "nez_reclass_out": reclass * p, "nez_new": new * p,
    })
    c.register("nez_flow_df", flow)
    c.execute("CREATE OR REPLACE TABLE nez_flow_raw AS SELECT * FROM nez_flow_df")
    c.unregister("nez_flow_df")
    c.execute("CREATE OR REPLACE VIEW v_nezf AS SELECT f.* EXCLUDE (position_id), v.* FROM nez_flow_raw f JOIN v_pos v USING (position_id)")


ACTION_COLUMNS = ["action_id", "issue_key", "created_at", "source", "company_id", "direction_id", "service_id", "mclass",
                  "material_id", "title", "deviation", "cause", "cause_status", "evidence", "measure", "owner",
                  "deadline", "forecast_effect", "actual_effect", "status", "acceptance", "priority", "value_at_risk",
                  "criticality", "repeat_count", "updated_at", "comment"]


ACTION_TYPES = {"forecast_effect": "DOUBLE", "actual_effect": "DOUBLE", "value_at_risk": "DOUBLE", "priority": "INTEGER", "repeat_count": "INTEGER"}


def _ensure_actions_table(c) -> None:
    """Таблица мероприятий с явной схемой (пустые колонки не должны получать тип NULL)."""
    cols = ", ".join(f"{k} {ACTION_TYPES.get(k, 'VARCHAR')}" for k in ACTION_COLUMNS)
    c.execute(f"CREATE TABLE actions ({cols})")
    f = DATA_DIR / "actions.parquet"
    if f.exists():
        src = f"read_parquet('{f.as_posix()}')"
    else:
        from .actions import seed_actions
        c.register("a_df", seed_actions())
        src = "a_df"
    sel = ", ".join(f"CAST({k} AS {ACTION_TYPES.get(k, 'VARCHAR')})" for k in ACTION_COLUMNS)
    c.execute(f"INSERT INTO actions SELECT {sel} FROM {src}")
    if src == "a_df":
        c.unregister("a_df")


def persist_actions() -> None:
    with _lock:
        df = _con.execute("SELECT * FROM actions").df()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(DATA_DIR / "actions.parquet", index=False)
