"""Централизованная модель сквозных фильтров, периода и ролевого доступа.

Один объект Ctx формируется из параметров запроса и используется всеми витринами,
конструктором срезов, детализацией, экспортом и аналитическим помощником.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field

from fastapi import HTTPException, Request

from . import db
from . import settings as cfg

# параметр запроса -> колонка в v_pos
FILTER_COLUMNS = {
    "company": "company_id", "segment": "segment", "ownership": "ownership_type", "site": "site_id",
    "warehouse": "warehouse_id", "direction": "direction_id", "dgroup": "direction_group", "program": "program",
    "service": "service_id", "mclass": "mclass", "mgroup": "mgroup", "material": "material_id",
    "project": "project_id", "criticality": "criticality", "demand_type": "demand_type",
    "policy": "replenishment_policy", "supplier": "supplier_id", "proc_model": "proc_model",
}

# допустимые аналитические разрезы: ключ -> (колонка id, колонка подписи, название)
DIMENSIONS = {
    "company": ("company_id", "company_name", "Общество"),
    "segment": ("segment", "segment", "Бизнес-сегмент"),
    "ownership": ("ownership_type", "ownership_type", "Тип общества (ДО/СП)"),
    "site": ("site_id", "site_name", "Месторождение / площадка"),
    "branch": ("branch", "branch", "Филиал"),
    "warehouse": ("warehouse_id", "warehouse_name", "Склад"),
    "cfo": ("cfo", "cfo", "ЦФО"),
    "dgroup": ("direction_group", "direction_group", "CAPEX / OPEX / RevEx"),
    "direction": ("direction_id", "direction_name", "Направление"),
    "program": ("program", "program", "Программа"),
    "service": ("service_id", "service_name", "Техническая служба"),
    "mclass": ("mclass", "mclass", "Класс МТР"),
    "mgroup": ("mgroup", "mgroup", "Группа МТР"),
    "material": ("material_id", "material_name", "Номенклатура"),
    "criticality": ("criticality", "criticality", "Критичность"),
    "demand_type": ("demand_type", "demand_type", "Тип спроса"),
    "policy": ("replenishment_policy", "replenishment_policy", "Политика пополнения"),
    "project": ("project_id", "project_name", "Проект"),
    "supplier": ("supplier_id", "supplier_id", "Поставщик"),
    "proc_model": ("proc_model", "proc_model", "Закупочная модель"),
    "age_bucket": ("age_bucket", "age_bucket", "Возраст запаса (с даты поступления)"),
    "noissue_bucket": ("noissue_bucket", "noissue_bucket", "Период без потребления"),
}
SNAPSHOT_ONLY_DIMS = {"age_bucket", "noissue_bucket"}


@dataclass
class Ctx:
    filters: dict[str, list[str]] = field(default_factory=dict)
    asof: int = 36
    window: int = 12
    m1: int = 25
    compare: str = "prev"  # prev | yoy | none
    grain: str = "month"
    role: str = "board"

    # ---------------- период ----------------
    @property
    def m2(self) -> int:
        return self.asof

    @property
    def n_months(self) -> int:
        return self.m2 - self.m1 + 1

    def cmp_range(self) -> tuple[int, int] | None:
        if self.compare == "none":
            return None
        if self.compare == "yoy":
            a, b = self.m1 - 12, self.m2 - 12
        else:
            a, b = self.m1 - self.n_months, self.m1 - 1
        if b < 1:
            return None
        return max(1, a), b

    def days(self, a: int | None = None, b: int | None = None) -> int:
        a = self.m1 if a is None else a
        b = self.m2 if b is None else b
        from .generator import days_in_month
        return sum(days_in_month(m) for m in range(a, b + 1))

    def period_label(self, a: int | None = None, b: int | None = None) -> str:
        a = self.m1 if a is None else a
        b = self.m2 if b is None else b
        return f"{db.month_label(a)} – {db.month_label(b)}"

    # ---------------- фильтры ----------------
    def where(self, alias: str = "", skip: set[str] | None = None) -> str:
        """SQL-условие для любого представления, содержащего колонки v_pos."""
        p = f"{alias}." if alias else ""
        cl = ["1=1"]
        for k, vals in self.filters.items():
            if skip and k in skip:
                continue
            col = FILTER_COLUMNS[k]
            if k == "direction":
                vals = expand_directions(vals)
            vs = ",".join("'" + str(v).replace("'", "''") + "'" for v in vals)
            cl.append(f"{p}{col} IN ({vs})")
        cl.append(self.access_clause(alias))
        return " AND ".join(cl)

    def access_clause(self, alias: str = "") -> str:
        p = f"{alias}." if alias else ""
        r = cfg.ROLES.get(self.role, cfg.ROLES["analyst"])
        cl = []
        if r["companies"]:
            cl.append(f"{p}company_id IN ({','.join(repr(c) for c in r['companies'])})")
        if not r["jv"]:
            cl.append(f"{p}ownership_type <> 'СП'")
        return " AND ".join(cl) if cl else "1=1"

    def describe(self) -> list[str]:
        out = []
        for k, vals in self.filters.items():
            out.append(f"{k}: {', '.join(vals)}")
        return out

    def with_filters(self, **extra) -> "Ctx":
        f = {k: list(v) for k, v in self.filters.items()}
        for k, v in extra.items():
            if v is None:
                f.pop(k, None)
            else:
                f[k] = v if isinstance(v, list) else [v]
        return Ctx(filters=f, asof=self.asof, window=self.window, m1=self.m1, compare=self.compare, grain=self.grain,
                   role=self.role)

    def to_dict(self) -> dict:
        cr = self.cmp_range()
        return dict(filters=self.filters, asof=self.asof, asof_label=db.month_label(self.asof), window=self.window,
                    m1=self.m1, m2=self.m2, period=self.period_label(), compare=self.compare,
                    compare_period=self.period_label(*cr) if cr else None, role=self.role,
                    role_label=cfg.ROLES.get(self.role, {}).get("label"))


def expand_directions(vals: list[str]) -> list[str]:
    """Выбор группы (CAPEX/OPEX/...) раскрывается до листовых направлений."""
    d = db.q("SELECT direction_id, parent_id FROM directions")
    out = set()
    for v in vals:
        out.add(v)
        out.update(d[d.parent_id == v].direction_id.tolist())
    return sorted(out)


def ctx_from_request(request: Request) -> Ctx:
    qp = request.query_params
    last = db.meta()["last_closed_m"]
    asof = int(qp.get("asof", last))
    asof = max(1, min(last, asof))
    window = qp.get("window", "12")
    if window == "custom" and qp.get("start"):
        m1 = max(1, min(asof, int(qp.get("start"))))
        w = asof - m1 + 1
    else:
        w = max(1, min(int(window), asof))
        m1 = asof - w + 1
    filters = {}
    for k in FILTER_COLUMNS:
        v = qp.get(k)
        if v:
            filters[k] = [x for x in v.split(",") if x]
    role = request.headers.get("x-role") or qp.get("role") or "board"
    if role not in cfg.ROLES:
        raise HTTPException(403, "Неизвестная роль")
    # пользователь общества не может расширить доступ фильтром
    r = cfg.ROLES[role]
    if r["companies"] and "company" in filters:
        filters["company"] = [c for c in filters["company"] if c in r["companies"]] or r["companies"]
    return Ctx(filters=filters, asof=asof, window=w, m1=m1, compare=qp.get("compare", "prev"),
               grain=qp.get("grain", "month"), role=role)
