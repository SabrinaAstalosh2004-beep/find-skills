"""Реестр управленческих проблем и мероприятий (витрина 20).

* Ответственный назначается только по матрице полномочий (демо-матрица ролей, без ФИО).
  Если тип проблемы в матрице отсутствует — «Требует назначения».
* Срок никогда не придумывается: пусто => «Требует назначения», пока пользователь не утвердит срок.
"""
from __future__ import annotations

import datetime as dt
import hashlib

import numpy as np
import pandas as pd

TBD = "Требует назначения"

# Демо-матрица полномочий: тип проблемы -> роль ответственного
AUTHORITY = {
    "nez_growth": "Начальник УМТО общества",
    "stock_up_cons_down": "Начальник УМТО общества",
    "purchase_with_coverage": "Руководитель закупок общества",
    "open_po_postponed": "Руководитель проекта (служба капстроя) + закупки",
    "project_postponed": "Руководитель проекта (служба капстроя)",
    "deficit_critical": "Главный инженер общества",
    "redistribution": "Директор по МТО группы (координация)",
    "plan_bias": "Руководитель службы — инициатора потребности",
    "dq": "Владелец НСИ / ответственный за данные общества",
    "supplier_delay": "Руководитель закупок общества",
    "pre_completion_purchase": "Руководитель проекта (служба капстроя)",
}
JV_NOTE = " (решение — органы управления СП)"

STATUSES = ["Новое", "Требует назначения", "В работе", "Выполнено, ожидает подтверждения эффекта",
            "Выполнено, эффект подтверждён", "Просрочено", "Отклонено"]


def owner_for(issue_type: str, ownership_type: str | None = None) -> str:
    o = AUTHORITY.get(issue_type)
    if not o:
        return TBD
    return o + (JV_NOTE if ownership_type == "СП" else "")


def issue_key(*parts) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


def seed_actions() -> pd.DataFrame:
    """Исторические мероприятия (ДЕМО) для демонстрации контроля исполнения и фактического эффекта."""
    rng = np.random.default_rng(7)
    today = dt.date(2026, 11, 1)
    templates = [
        ("nez_growth", "C05", "D12", "Запорная арматура", "Реализация НЛИ через торги", "Балансовая стоимость НЛИ снижена; поступления по договорам"),
        ("redistribution", "C01", "D08", "ЗИП насосного оборудования", "Перераспределение ЗИП в АО «Тета-Добыча»", "Закрыт дефицит, отказ от новой закупки"),
        ("purchase_with_coverage", "C08", "D09", "Химические реагенты", "Отмена заявок при покрытии > 12 мес.", "Заявки аннулированы"),
        ("plan_bias", "C04", "D14", "Приборы КИПиА", "Корректировка плана потребности КИПиА", "Точность плана в пределах ±15%"),
        ("project_postponed", "C02", "D01", "Трубная продукция", "Пересмотр графика поставок по УКПГ-2", "График поставок синхронизирован с графиком СМР"),
        ("dq", "C09", "D08", "Компоненты АСУТП", "Устранение дублей НСИ по АСУТП", "Дубли объединены, остатки перенесены"),
        ("deficit_critical", "C08", "D08", "ЗИП насосного оборудования", "Срочное обеспечение уплотнений ЦНС", "Позиция обеспечена до ремонтной кампании"),
        ("stock_up_cons_down", "C08", "D09", "Насосное оборудование", "Анализ закупок при падении добычи", "Сокращение поступлений до уровня потребления"),
        ("supplier_delay", "C02", "D10", "Электрооборудование", "Претензионная работа с поставщиком S07", "Поставки по графику"),
        ("unknown_type", "C10", "D17", "СИЗ и средства ПБ", "Оптимизация запаса СИЗ", "Покрытие ≤ 6 мес."),
    ]
    rows = []
    for k in range(26):
        t = templates[k % len(templates)]
        created = today - dt.timedelta(days=int(rng.integers(20, 400)))
        st = rng.choice(["Выполнено, эффект подтверждён", "В работе", "Выполнено, ожидает подтверждения эффекта", "Просрочено", "Требует назначения"],
                        p=[0.35, 0.25, 0.12, 0.18, 0.10])
        owner = owner_for(t[0], "СП" if t[1] in ("C06", "C07") else "ДО")
        deadline = created + dt.timedelta(days=int(rng.integers(30, 180))) if owner != TBD and st != "Требует назначения" else None
        if st == "Просрочено" and deadline and deadline > today:
            deadline = today - dt.timedelta(days=int(rng.integers(5, 60)))
        if st == "Требует назначения":
            owner = TBD
        f_eff = float(round(rng.uniform(3, 60) * 1e6, -4))
        a_eff = float(round(f_eff * rng.uniform(0.5, 1.1), -4)) if st == "Выполнено, эффект подтверждён" else None
        rows.append(dict(
            action_id=f"A{k + 1:04d}", issue_key=issue_key("seed", t[0], t[1], t[3]), created_at=created.isoformat(),
            source="История мероприятий (ДЕМО)", company_id=t[1], direction_id=t[2], service_id=None, mclass=t[3],
            material_id=None, title=t[4], deviation=f"{t[3]}: отклонение по {t[0]}",
            cause="Гипотеза, требует проверки" if k % 3 else "Подтверждена актом проверки (демо)",
            cause_status="Гипотеза" if k % 3 else "Подтверждена", evidence="См. витрину-источник", measure=t[4], owner=owner,
            deadline=deadline.isoformat() if deadline else None, forecast_effect=f_eff, actual_effect=a_eff, status=str(st),
            acceptance=t[5], priority=int(rng.integers(1, 4)), value_at_risk=float(round(f_eff * rng.uniform(1.2, 3), -4)),
            criticality=str(rng.choice(["Высокая", "Средняя", "Низкая"])), repeat_count=int(1 + (k % 10 == 7) + (t[0] == "plan_bias")),
            updated_at=created.isoformat(), comment=None,
        ))
    return pd.DataFrame(rows)


def effective_status(row: dict, today: dt.date) -> str:
    st = row.get("status")
    if st in ("В работе", "Новое") and row.get("deadline"):
        try:
            if dt.date.fromisoformat(str(row["deadline"])[:10]) < today:
                return "Просрочено"
        except ValueError:
            pass
    if (not row.get("owner") or row.get("owner") == TBD) and st not in ("Выполнено, эффект подтверждён", "Отклонено"):
        return "Требует назначения"
    return st
