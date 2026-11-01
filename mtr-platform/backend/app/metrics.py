"""Единый каталог метрик. Это единственное место, где определены формулы производных показателей.

Статус всех методик — «рабочая методика демо»: формулы согласованы с постановкой задачи,
но не подтверждены корпоративными документами (ОСК-03.06.04 v3.0 в систему не загружен).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

OWNER_TBD = "Требует назначения"
STATUS_DEMO = "Рабочая методика демо — требует подтверждения"


@dataclass
class Metric:
    id: str
    label: str
    group: str
    unit: str  # rub | pct | days | months | qty | count | ratio
    formula: str
    source: str
    period: str
    aggregation: str
    includes: str = "Позиции на балансе (собственные), все склады в периметре фильтра"
    excludes: str = "Консигнационный запас поставщика"
    limitations: str = ""
    owner: str = OWNER_TBD
    status: str = STATUS_DEMO
    higher_is_better: bool | None = None
    sliceable: bool = True


M = [
    # ---- уровень запасов
    Metric("stock_end", "Стоимость запасов МТР", "Уровень запасов", "rub", "Σ(количество × цена) на конец периода",
           "Остатки МТР на отчётные даты (fact_snapshot)", "На дату", "Сумма", higher_is_better=False),
    Metric("stock_start", "Запасы на начало периода", "Уровень запасов", "rub", "Σ стоимости на конец месяца, предшествующего периоду",
           "fact_snapshot", "На дату", "Сумма"),
    Metric("stock_delta", "Изменение запасов", "Уровень запасов", "rub", "Запасы на конец − запасы на начало", "fact_snapshot",
           "За период", "Сумма", higher_is_better=False),
    Metric("stock_delta_pct", "Изменение запасов, %", "Уровень запасов", "pct", "(Конец − Начало) / Начало × 100", "fact_snapshot",
           "За период", "Пересчёт из сумм (не усредняется)", higher_is_better=False),
    Metric("stock_avg", "Средний остаток", "Уровень запасов", "rub",
           "Хронологическое среднее по месячным срезам: (S0/2 + S1 + … + Sn−1 + Sn/2)/n", "fact_snapshot", "За период", "Сумма",
           limitations="Среднедневные остатки недоступны в источнике; используется хронологическое среднее по месячным срезам."),
    Metric("receipts", "Поступление", "Уровень запасов", "rub", "Σ стоимости документов поступления", "fact_movement", "За период", "Сумма"),
    Metric("consumption", "Потребление", "Уровень запасов", "rub", "Σ стоимости отпуска в производство/ремонт/строительство",
           "fact_movement", "За период", "Сумма", higher_is_better=True),
    Metric("returns", "Возвраты", "Уровень запасов", "rub", "Σ возвратов на склад", "fact_movement", "За период", "Сумма"),
    Metric("transfers_net", "Перемещения (сальдо)", "Уровень запасов", "rub", "Приход по перемещениям − расход по перемещениям",
           "fact_movement", "За период", "Сумма", limitations="На уровне группы межобщественные перемещения взаимно исключаются."),
    Metric("adjust", "Корректировки", "Уровень запасов", "rub", "Σ инвентаризационных корректировок", "fact_movement", "За период", "Сумма"),
    Metric("reval", "Переоценка", "Уровень запасов", "rub", "Σ количество на начало месяца × изменение цены", "fact_movement",
           "За период", "Сумма", limitations="Отражает изменение цены, а не физического объёма."),
    Metric("qty_driven_delta", "Изменение запасов за счёт движения количества", "Уровень запасов", "rub",
           "Изменение запасов − переоценка − расхождения учёта", "fact_movement", "За период", "Сумма"),
    # ---- эффективность
    Metric("turnover_days", "Оборачиваемость, дни", "Эффективность", "days",
           "Средний остаток за период / Потребление за период × число дней периода", "fact_snapshot, fact_movement",
           "За период", "Пересчёт из сумм числителя и знаменателя (не среднее по обществам)",
           limitations="При нулевом потреблении не рассчитывается (статус «Нет потребления»). Для проектных запасов и критического ЗИП "
                       "не применяется как норматив — используйте покрытие проектной потребности и уровень обслуживания ЗИП.",
           higher_is_better=False),
    Metric("coverage_months", "Покрытие запасом, мес.", "Эффективность", "months",
           "Запасы на конец / среднемесячное потребление за период", "fact_snapshot, fact_movement", "На дату", "Пересчёт из сумм",
           higher_is_better=False),
    Metric("nez_end", "НЭЗ", "Эффективность", "rub",
           "Σ стоимости части остатка без потребления ≥ N дней, не покрытой подтверждённой потребностью на горизонте H мес.; "
           "страховой запас и критичные МТР исключаются", "fact_snapshot, fact_demand, настройки правил", "На дату", "Сумма",
           limitations="Порог N и горизонт H — настраиваемые рабочие параметры, не утверждённые нормативы.",
           higher_is_better=False),
    Metric("nez_share", "Доля НЭЗ, %", "Эффективность", "pct", "НЭЗ / Стоимость запасов × 100", "fact_snapshot", "На дату",
           "Пересчёт из сумм", higher_is_better=False),
    Metric("nez_delta", "Прирост НЭЗ", "Эффективность", "rub", "НЭЗ на конец − НЭЗ на начало", "fact_snapshot", "За период", "Сумма",
           higher_is_better=False),
    Metric("noissue_end", "Запасы без потребления", "Эффективность", "rub",
           "Σ стоимости позиций без отпуска ≥ порога дней (включая страховой запас)", "fact_snapshot", "На дату", "Сумма",
           limitations="Отсутствие движения само по себе не означает неэффективность (страховой запас).", higher_is_better=False),
    Metric("free_end", "Свободный запас", "Эффективность", "rub", "Σ (количество − резерв − недоступный) × цена", "fact_snapshot",
           "На дату", "Сумма"),
    Metric("free_share", "Доля свободного запаса, %", "Эффективность", "pct", "Свободный запас / Запасы × 100", "fact_snapshot",
           "На дату", "Пересчёт из сумм"),
    Metric("reserved_end", "Зарезервированный запас", "Эффективность", "rub", "Σ min(резерв, количество) × цена", "fact_snapshot",
           "На дату", "Сумма"),
    Metric("unavail_end", "Недоступный запас", "Обеспеченность", "rub", "Σ количества с блокировкой (брак, ответхранение, в пути) × цена",
           "fact_snapshot", "На дату", "Сумма", higher_is_better=False),
    Metric("crit_end", "Запас критичных МТР", "Обеспеченность", "rub", "Σ стоимости МТР с критичностью A", "fact_snapshot", "На дату", "Сумма"),
    Metric("holding_cost", "Стоимость владения запасом (год)", "Финансы", "rub",
           "Средний остаток × (ставка стоимости капитала + ставка хранения + ставка морального износа)",
           "fact_snapshot, настройки", "Годовая оценка", "Сумма",
           limitations="Ставки — допущения демо. Альтернативная стоимость капитала не является расходом в P&L и не входит в EBITDA.",
           higher_is_better=False),
    # ---- планирование
    Metric("plan_value", "Плановая потребность", "Планирование", "rub", "Σ план (оперативная версия на месяц) × цена", "fact_demand",
           "За период", "Сумма"),
    Metric("plan_bias_pct", "Завышение плана потребности, %", "Планирование", "pct", "(План − Факт потребления) / Факт × 100",
           "fact_demand, fact_movement", "За период", "Пересчёт из сумм",
           limitations="Фактическое потребление ограничено наличием (при дефиците факт занижен).", higher_is_better=False),
    # ---- обеспеченность
    Metric("deficit_value", "Потребность с риском дефицита", "Обеспеченность", "rub",
           "Σ max(0, план на H мес. − свободный остаток − заказы со сроком в горизонте) × цена", "fact_demand, fact_snapshot, fact_po",
           "На дату, горизонт H", "Сумма", limitations="Не учитывает перераспределение и аналоги; вероятность — скоринговая оценка.",
           higher_is_better=False),
    Metric("deficit_crit_value", "Риск дефицита критичных МТР", "Обеспеченность", "rub", "То же для критичности A",
           "fact_demand, fact_snapshot, fact_po", "На дату", "Сумма", higher_is_better=False),
    Metric("open_po", "Открытые заказы", "Закупки", "rub", "Σ стоимости заказов, размещённых до даты и не поставленных",
           "fact_purchase_order", "На дату", "Сумма", excludes="Заказы в валюте без пересчёта (выявляются контролем качества)"),
    Metric("overdue_po", "Просроченные поставки", "Обеспеченность", "rub", "Открытые заказы с плановой датой поставки ранее даты среза",
           "fact_purchase_order", "На дату", "Сумма", higher_is_better=False),
    # ---- вовлечение
    Metric("nez_new", "Вновь сформированные НЭЗ", "Вовлечение", "rub", "Прирост количества НЭЗ по позиции × цена (помесячно)",
           "nez_flow", "За период", "Сумма", higher_is_better=False),
    Metric("nez_involved", "Вовлечение НЭЗ", "Вовлечение", "rub", "Потребление + перемещение + реализация + списание из НЭЗ",
           "nez_flow", "За период", "Сумма", higher_is_better=True),
    Metric("disposal", "Выбытие (реализация и списание)", "Вовлечение", "rub", "Σ балансовой стоимости реализованных и списанных МТР",
           "fact_movement", "За период", "Сумма",
           limitations="Балансовое уменьшение ≠ денежные поступления ≠ финансовый результат."),
    Metric("n_items", "Количество номенклатурных позиций с остатком", "Уровень запасов", "count", "Число уникальных МТР с остатком > 0",
           "fact_snapshot", "На дату", "Уникальный счёт (не суммируется по разрезам)"),
]
REGISTRY = {m.id: m for m in M}


def catalog() -> list[dict]:
    return [asdict(m) for m in M]


def derive(df: pd.DataFrame, days: int, n_months: int) -> pd.DataFrame:
    from . import settings as cfg
    fin = cfg.get()["finance"]
    d = df
    d["stock_delta"] = d.stock_end - d.stock_start
    d["stock_delta_pct"] = np.where(d.stock_start > 0, d.stock_delta / d.stock_start.where(d.stock_start > 0) * 100, np.nan)
    d["transfers_net"] = d.tr_in - d.tr_out
    flows = d.receipts + d.returns + d.tr_in - d.consumption - d.tr_out + d.adjust + d.reval - d.sales - d.writeoff
    d["discrepancy"] = d.stock_end - d.stock_start - flows
    d["qty_driven_delta"] = d.stock_delta - d.reval - d.discrepancy
    d["turnover_days"] = np.where(d.consumption > 0, d.stock_avg / d.consumption.where(d.consumption > 0) * days, np.nan)
    d["coverage_months"] = np.where(d.consumption > 0, d.stock_end / (d.consumption.where(d.consumption > 0) / n_months), np.nan)
    d["nez_share"] = np.where(d.stock_end > 0, d.nez_end / d.stock_end.where(d.stock_end > 0) * 100, np.nan)
    d["nez_delta"] = d.nez_end - d.nez_start
    d["free_share"] = np.where(d.stock_end > 0, d.free_end / d.stock_end.where(d.stock_end > 0) * 100, np.nan)
    d["holding_cost"] = d.stock_avg * (fin["cost_of_capital"] + fin["storage_rate"] + fin["obsolescence_rate"])
    d["plan_bias_pct"] = np.where(d.consumption > 0, (d.plan_value - d.consumption) / d.consumption.where(d.consumption > 0) * 100, np.nan)
    d["nez_involved"] = d.nez_consumed + d.nez_transferred + d.nez_sold + d.nez_written_off
    d["disposal"] = d.sales + d.writeoff
    return d


def turnover_status(row) -> str:
    if row.get("consumption", 0) <= 0:
        return "Нет потребления"
    return "Рассчитано"
