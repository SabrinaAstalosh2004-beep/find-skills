"""Адаптеры источников данных.

Реальные интерфейсы корпоративных систем (1С:Шерпа, SAP / АСУЗ МТР, «Резерв», ЕФИ/НСИ, ТОиР, УИП, источники
плановой потребности, КХД) в проект не предоставлены. Поэтому:
* реализованы рабочие файловые адаптеры (CSV, Excel, Parquet) и SQL-адаптер (через DuckDB: SQLite/Postgres/MySQL
  при наличии соответствующего расширения DuckDB);
* для корпоративных систем — настраиваемые адаптеры-заглушки со статусом «Интерфейс не предоставлен»: они описывают
  ожидаемые наборы данных и принимают выгрузки в каноническом формате через файловый адаптер.
Готовые API не придумываются.
"""
from __future__ import annotations

import io
import json
import pathlib
import shutil

import duckdb
import pandas as pd

from . import db
from . import settings as cfg

STAGING = cfg.DATA_DIR / "staging"
LOADED = cfg.DATA_DIR / "loaded"
SOURCES_FILE = cfg.DATA_DIR / "sources.json"

REQUIRED = ["companies", "sites", "warehouses", "directions", "services", "suppliers", "materials", "positions", "projects",
            "objects", "snapshot", "opening", "movements", "demand", "purchase_orders", "shortages", "disposal", "repair_fund",
            "equipment", "activity", "finance"]
OPTIONAL = {"dq_injected"}

CORPORATE = [
    ("sherpa", "1С:Шерпа", "Остатки, движения, резервы, заявки", ["snapshot", "movements", "purchase_orders"]),
    ("sap", "SAP / АСУЗ МТР", "Заказы, поставщики, сроки поставки, остатки", ["purchase_orders", "suppliers", "snapshot"]),
    ("reserve", "«Резерв»", "Резервирование под потребность и проекты", ["snapshot"]),
    ("efi_nsi", "ЕФИ и справочники НСИ", "НСИ МТР, организационная структура, направления", ["materials", "companies", "directions", "services"]),
    ("toir", "Системы ТОиР", "Оборудование, отказы, ремонтный фонд", ["equipment", "repair_fund"]),
    ("uip", "Системы управления инвестиционными проектами", "Проекты, объекты, графики", ["projects", "objects"]),
    ("demand", "Источники плановой потребности", "Плановая потребность и программы", ["demand"]),
    ("dwh", "Витрины корпоративного хранилища данных", "Любые наборы в каноническом формате", REQUIRED),
]


def canonical_schema() -> dict[str, list[dict]]:
    out = {}
    src = db.DEMO_DIR
    for t in REQUIRED + sorted(OPTIONAL):
        f = src / f"{t}.parquet"
        if f.exists():
            sch = duckdb.sql(f"DESCRIBE SELECT * FROM read_parquet('{f.as_posix()}')").df()
            out[t] = [dict(column=r.column_name, type=r.column_type) for r in sch.itertuples()]
    return out


def list_sources() -> dict:
    conf = json.loads(SOURCES_FILE.read_text("utf-8")) if SOURCES_FILE.exists() else {}
    staged = sorted(p.stem for p in STAGING.glob("*.parquet")) if STAGING.exists() else []
    adapters = [dict(id="file", name="Файлы (CSV / Excel / Parquet)", status="Работает", kind="file",
                     description="Загрузка таблиц в каноническом формате; проверка состава колонок"),
                dict(id="sql", name="SQL (через DuckDB)", status="Работает", kind="sql",
                     description="Строка подключения + SQL-запрос на каждую каноническую таблицу")]
    for i, n, d, tables in CORPORATE:
        c = conf.get(i, {})
        adapters.append(dict(id=i, name=n, kind="corporate", description=d, tables=tables, config=c,
                             status="Настроено: выгрузки через файловый адаптер" if c else "Интерфейс не предоставлен — требуется спецификация"))
    return dict(adapters=adapters, staged=staged, missing=[t for t in REQUIRED if t not in staged], active=db.meta()["source_dir"],
                is_demo=db.meta()["is_demo"])


def save_config(adapter_id: str, conf: dict) -> dict:
    allc = json.loads(SOURCES_FILE.read_text("utf-8")) if SOURCES_FILE.exists() else {}
    allc[adapter_id] = conf
    cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    SOURCES_FILE.write_text(json.dumps(allc, ensure_ascii=False, indent=2), "utf-8")
    return list_sources()


def read_upload(table: str, filename: str, content: bytes) -> pd.DataFrame:
    name = filename.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(content), sep=None, engine="python", encoding="utf-8-sig")
    elif name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(content))
    elif name.endswith(".parquet"):
        df = pd.read_parquet(io.BytesIO(content))
    else:
        raise ValueError("Поддерживаются CSV, Excel (.xlsx) и Parquet")
    return df


def validate(table: str, df: pd.DataFrame) -> list[str]:
    sch = canonical_schema().get(table)
    if sch is None:
        return [f"Неизвестная таблица {table}"]
    need = [c["column"] for c in sch]
    miss = [c for c in need if c not in df.columns]
    return [f"Отсутствуют колонки: {', '.join(miss)}"] if miss else []


def stage(table: str, df: pd.DataFrame) -> None:
    STAGING.mkdir(parents=True, exist_ok=True)
    df.to_parquet(STAGING / f"{table}.parquet", index=False)


def load_sql(conn: str, queries: dict[str, str]) -> dict:
    """SQL-адаптер: выполняет запросы через DuckDB (ATTACH строки подключения) и сохраняет результат в staging."""
    c = duckdb.connect()
    errors = {}
    if conn:
        c.execute(f"ATTACH '{conn}' AS src (READ_ONLY)")
    for t, sql in queries.items():
        try:
            df = c.execute(sql).df()
            e = validate(t, df)
            if e:
                errors[t] = e
            else:
                stage(t, df)
        except Exception as ex:
            errors[t] = [str(ex)]
    return errors


def activate() -> dict:
    missing = [t for t in REQUIRED if not (STAGING / f"{t}.parquet").exists()]
    if missing:
        return dict(ok=False, error="Не загружены обязательные наборы: " + ", ".join(missing))
    if LOADED.exists():
        shutil.rmtree(LOADED)
    shutil.copytree(STAGING, LOADED)
    if not (LOADED / "dq_injected.parquet").exists():
        pd.DataFrame(columns=["issue", "ref"]).astype(str).to_parquet(LOADED / "dq_injected.parquet", index=False)
    db.init(LOADED)
    return dict(ok=True)


def reset_demo() -> dict:
    db.init(db.DEMO_DIR)
    return dict(ok=True)
