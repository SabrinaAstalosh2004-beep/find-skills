"""Настраиваемые параметры методики, целевые значения и роли доступа.

Все пороги и цели здесь — РАБОЧИЕ ПАРАМЕТРЫ ДЕМОНСТРАЦИИ. Они не являются утверждёнными
корпоративными нормативами (в т.ч. по ОСК-03.06.04 v3.0, текст которого в систему не загружен)
и должны быть заменены значениями из утверждённой методологии.
"""
from __future__ import annotations

import copy
import json
import pathlib
import threading

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULTS: dict = {
    "methodology_status": "Рабочие параметры демо — требуют подтверждения корпоративной методологией",
    "nez": {
        "no_issue_days": 365,
        "need_horizon_months": 12,
        "protected_policies": ["Страховой запас"],
        "protected_criticality": ["A — критичный"],
        "note": "НЭЗ = часть остатка без потребления ≥ N дней, не покрытая подтверждённой потребностью на горизонте H мес.; "
                "страховой запас и критичные МТР исключаются. Правило настраиваемое и не является утверждённой нормой.",
    },
    "no_consumption_days": 365,
    "age_buckets_days": [90, 180, 365, 730, 1095],
    "targets": {
        "nez_share_pct": 10.0,
        "turnover_days": 200.0,
        "stock_growth_pct_year": 5.0,
        "free_share_pct": 35.0,
        "deficit_value_mln": 50.0,
        "note": "Демо-цели. Утверждённые цели не загружены.",
    },
    "finance": {
        "cost_of_capital": 0.13,
        "storage_rate": 0.04,
        "obsolescence_rate": 0.03,
        "note": "Ставки для оценки стоимости владения запасом — допущения демо.",
    },
    "zip": {"service_level": 0.95},
    "coverage_excess_months": 12,
    "deficit_horizon_months": 3,
    "redistribution": {"transport_cost_pct": 0.04, "min_value_rub": 30000, "approval_days": 20},
}

ROLES = {
    "board": {"label": "Председатель правления (вся группа, включая СП)", "companies": None, "jv": True},
    "ceo": {"label": "Генеральный директор (вся группа, включая СП)", "companies": None, "jv": True},
    "mto": {"label": "Директор по МТО (вся группа, включая СП)", "companies": None, "jv": True},
    "analyst": {"label": "Аналитик группы (без доступа к данным СП)", "companies": None, "jv": False},
    "c01": {"label": "Руководитель УМТО АО «Альфа-Нефть»", "companies": ["C01"], "jv": False},
    "c06": {"label": "Представитель СП «Зета-Нефтегаз»", "companies": ["C06"], "jv": True},
}

_lock = threading.Lock()
_current: dict | None = None


def get() -> dict:
    global _current
    with _lock:
        if _current is None:
            _current = copy.deepcopy(DEFAULTS)
            if SETTINGS_FILE.exists():
                try:
                    _merge(_current, json.loads(SETTINGS_FILE.read_text("utf-8")))
                except Exception:
                    pass
        return copy.deepcopy(_current)


def update(patch: dict) -> dict:
    global _current
    cur = get()
    _merge(cur, patch)
    with _lock:
        _current = cur
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(cur, ensure_ascii=False, indent=2), "utf-8")
    return copy.deepcopy(cur)


def reset() -> dict:
    global _current
    with _lock:
        _current = copy.deepcopy(DEFAULTS)
        if SETTINGS_FILE.exists():
            SETTINGS_FILE.unlink()
    return get()


def _merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v
