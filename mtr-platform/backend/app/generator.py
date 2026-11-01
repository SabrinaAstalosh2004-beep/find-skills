"""Генератор воспроизводимого ДЕМОНСТРАЦИОННОГО набора данных по запасам МТР.

ВНИМАНИЕ: все общества, объекты, МТР, поставщики, суммы и события — синтетические.
Они не являются реальными корпоративными показателями.

Принципы:
* фиксированный seed -> одинаковый результат при каждом запуске;
* моделирование ведётся по «позициям учёта» (общество × склад × МТР × направление ×
  служба × объект), каждое движение и каждый остаток привязан к позиции;
* арифметическая согласованность: остаток на начало + движения + переоценка = остаток на конец
  (по количеству и по стоимости). Для проверки контроля качества намеренно внесены
  отдельные, явно помеченные искажения (см. inject_dq_issues).
"""
from __future__ import annotations

import calendar
import datetime as dt
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

SEED = 20261031
N_MONTHS = 37  # m=0 -> 2023-10 (технический месяц входящего остатка) ... m=36 -> 2026-10
FUTURE = 24  # горизонт плановой потребности после последнего закрытого периода
START_YEAR, START_MONTH = 2023, 10


def month_start(m: int) -> dt.date:
    y = START_YEAR + (START_MONTH - 1 + m) // 12
    mo = (START_MONTH - 1 + m) % 12 + 1
    return dt.date(y, mo, 1)


def month_end(m: int) -> dt.date:
    s = month_start(m)
    return dt.date(s.year, s.month, calendar.monthrange(s.year, s.month)[1])


def days_in_month(m: int) -> int:
    s = month_start(m)
    return calendar.monthrange(s.year, s.month)[1]


# --------------------------------------------------------------------------------------
# Справочники (демонстрационные). Реальные коды и соответствия — из корпоративной НСИ.
# --------------------------------------------------------------------------------------
COMPANIES = [
    # id, name, segment, type (ДО/СП), region, profile, overbuy
    ("C01", "АО «Альфа-Нефть»", "Разведка и добыча нефти", "ДО", "Западная Сибирь", "oil", 1.15),
    ("C02", "АО «Бета-Газ»", "Добыча газа", "ДО", "Ямал", "gas", 1.05),
    ("C03", "ООО «Гамма-Бурение»", "Нефтесервис", "ДО", "Западная Сибирь", "drill", 1.10),
    ("C04", "АО «Дельта-Переработка»", "Переработка", "ДО", "Поволжье", "refine", 1.05),
    ("C05", "ООО «Эпсилон-Транспорт»", "Логистика и транспорт", "ДО", "Урал", "transport", 1.00),
    ("C06", "ООО «Зета-Нефтегаз» (СП)", "Разведка и добыча нефти", "СП", "Оренбуржье", "oil", 1.20),
    ("C07", "ООО «Эта-Шельф» (СП)", "Добыча газа", "СП", "Арктика", "gas", 1.10),
    ("C08", "АО «Тета-Добыча»", "Разведка и добыча нефти", "ДО", "Томская область", "oil", 1.10),
    ("C09", "АО «Йота-Газпереработка»", "Переработка", "ДО", "Западная Сибирь", "refine_gas", 1.05),
    ("C10", "ООО «Каппа-Сервис»", "Сервис и прочее", "ДО", "Москва", "service", 1.00),
]

SITE_NAMES = ["Северное", "Южное", "Озёрное", "Лесное", "Речное", "Холмистое", "Степное", "Таёжное",
              "Ключевое", "Каменное", "Песчаное", "Кедровое", "Берёзовое", "Луговое", "Ветреное",
              "Снежное", "Мысовое", "Заречное", "Восточное", "Полярное"]

# Иерархия направлений формирования запаса (демо-соответствие, требует замены справочником)
DIRECTIONS = [
    ("G_CAPEX", "CAPEX", None, "CAPEX"),
    ("G_OPEX", "OPEX", None, "OPEX"),
    ("G_REVEX", "RevEx", None, "RevEx"),
    ("G_COM", "Коммерческая деятельность", None, "Коммерческая"),
    ("D01", "Капитальное строительство", "G_CAPEX", "CAPEX"),
    ("D02", "Бурение", "G_CAPEX", "CAPEX"),
    ("D03", "ОНСС", "G_CAPEX", "CAPEX"),
    ("D04", "Геологоразведка", "G_CAPEX", "CAPEX"),
    ("D05", "Обустройство месторождений", "G_CAPEX", "CAPEX"),
    ("D06", "Реконструкция и модернизация", "G_CAPEX", "CAPEX"),
    ("D07", "Капитальный ремонт", "G_REVEX", "RevEx"),
    ("D08", "Ремонтно-эксплуатационные нужды", "G_OPEX", "OPEX"),
    ("D09", "Добыча нефти", "G_OPEX", "OPEX"),
    ("D10", "Добыча газа", "G_OPEX", "OPEX"),
    ("D11", "Подготовка нефти и газа", "G_OPEX", "OPEX"),
    ("D12", "Транспортировка нефти", "G_OPEX", "OPEX"),
    ("D13", "Транспортировка газа", "G_OPEX", "OPEX"),
    ("D14", "Переработка", "G_OPEX", "OPEX"),
    ("D15", "Логистика нефтепродуктов", "G_OPEX", "OPEX"),
    ("D16", "Сервисные направления", "G_OPEX", "OPEX"),
    ("D17", "Административно-хозяйственные потребности", "G_OPEX", "OPEX"),
    ("D18", "Реализация МТР и услуги третьим лицам", "G_COM", "Коммерческая"),
]

SERVICES = ["Механическая служба", "Энергетическая служба", "КИПиА", "АСУТП", "Служба бурения",
            "Служба эксплуатации оборудования", "Служба ТОиР", "Служба капитального строительства",
            "Служба промышленной безопасности", "Технологическая служба", "Прочие службы"]

PROFILE_DIRECTIONS = {
    "oil": {"capex": ["D01", "D05", "D06", "D02", "D04"], "opex": ["D09", "D11", "D08", "D07"]},
    "gas": {"capex": ["D01", "D05", "D06"], "opex": ["D10", "D11", "D13", "D08", "D07"]},
    "drill": {"capex": ["D02", "D03", "D04"], "opex": ["D16", "D08"]},
    "refine": {"capex": ["D06", "D01"], "opex": ["D14", "D15", "D08", "D07"]},
    "refine_gas": {"capex": ["D01", "D06"], "opex": ["D14", "D08", "D07"]},
    "transport": {"capex": ["D06"], "opex": ["D12", "D15", "D08", "D07", "D17"]},
    "service": {"capex": [], "opex": ["D16", "D17", "D18", "D08"]},
}

# class, groups, price range, lead days, service, repairable p, critical p, unit, demand mix(reg,int,proj), stems, proc models
CLASSES = [
    ("Насосное оборудование", ["Насосы центробежные", "Насосы ЭЦН", "Насосы дозировочные"], (300e3, 6e6), 150,
     "Механическая служба", 0.8, 0.5, "шт", (0.1, 0.6, 0.3), ["Насос ЦНС", "Насос ЭЦН5", "Насос НД"],
     {"Рамочный договор": .5, "Спотовая закупка": .4, "Прейскурант": .1}),
    ("ЗИП насосного оборудования", ["Торцевые уплотнения", "Рабочие колёса", "Валы и муфты"], (20e3, 450e3), 120,
     "Механическая служба", 0.3, 0.6, "шт", (0.2, 0.8, 0.0), ["Уплотнение торцевое", "Колесо рабочее", "Вал насоса"],
     {"Рамочный договор": .6, "Спотовая закупка": .3, "VMI": .1}),
    ("Компрессорное оборудование", ["Компрессоры поршневые", "Компрессоры винтовые"], (2e6, 25e6), 240,
     "Механическая служба", 0.9, 0.7, "шт", (0.0, 0.4, 0.6), ["Компрессор 4ГМ", "Компрессор ВК"],
     {"Спотовая закупка": .7, "Рамочный договор": .3}),
    ("Трубная продукция", ["Трубы НКТ", "Трубы обсадные", "Трубы магистральные"], (60e3, 260e3), 90,
     "Служба капитального строительства", 0.0, 0.1, "т", (0.1, 0.0, 0.9), ["Труба НКТ", "Труба обсадная", "Труба 1020х"],
     {"Рамочный договор": .6, "Спотовая закупка": .4}),
    ("Запорная арматура", ["Задвижки", "Краны шаровые", "Клапаны"], (15e3, 900e3), 100,
     "Механическая служба", 0.4, 0.3, "шт", (0.5, 0.2, 0.3), ["Задвижка ЗКС", "Кран шаровой КШ", "Клапан КПП"],
     {"Прейскурант": .4, "Рамочный договор": .4, "Спотовая закупка": .2}),
    ("Электрооборудование", ["Электродвигатели", "Трансформаторы", "КРУ и щиты"], (80e3, 15e6), 180,
     "Энергетическая служба", 0.7, 0.5, "шт", (0.2, 0.5, 0.3), ["Электродвигатель АИР", "Трансформатор ТМГ", "КРУ-10"],
     {"Рамочный договор": .5, "Спотовая закупка": .5}),
    ("Кабельная продукция", ["Кабель силовой", "Кабель контрольный"], (150e3, 1.8e6), 60,
     "Энергетическая служба", 0.0, 0.1, "км", (0.5, 0.0, 0.5), ["Кабель ВВГнг", "Кабель КВВГ"],
     {"Прейскурант": .5, "Рамочный договор": .3, "Консигнация": .2}),
    ("Приборы КИПиА", ["Датчики давления", "Расходомеры", "Уровнемеры"], (20e3, 600e3), 120,
     "КИПиА", 0.3, 0.4, "шт", (0.7, 0.3, 0.0), ["Датчик давления ДД", "Расходомер РМ", "Уровнемер УР"],
     {"Рамочный договор": .5, "Прейскурант": .3, "VMI": .2}),
    ("Компоненты АСУТП", ["Контроллеры", "Модули ввода-вывода", "Серверное оборудование"], (50e3, 3e6), 160,
     "АСУТП", 0.2, 0.6, "шт", (0.2, 0.7, 0.1), ["Контроллер ПЛК", "Модуль ВВ", "Сервер АСУ"],
     {"Спотовая закупка": .6, "Рамочный договор": .4}),
    ("Буровой инструмент", ["Долота", "Бурильные трубы", "Забойные двигатели"], (100e3, 5e6), 120,
     "Служба бурения", 0.5, 0.4, "шт", (0.2, 0.1, 0.7), ["Долото PDC", "Труба бурильная ТБ", "Двигатель забойный Д"],
     {"Рамочный договор": .6, "Спотовая закупка": .4}),
    ("Химические реагенты", ["Ингибиторы коррозии", "Деэмульгаторы", "Буровые растворы"], (50e3, 320e3), 45,
     "Технологическая служба", 0.0, 0.2, "т", (0.9, 0.0, 0.1), ["Ингибитор ИК", "Деэмульгатор ДЭ", "Раствор БР"],
     {"Рамочный договор": .5, "VMI": .3, "Консигнация": .2}),
    ("Металлопрокат", ["Лист стальной", "Профиль", "Арматура"], (60e3, 150e3), 30,
     "Служба капитального строительства", 0.0, 0.0, "т", (0.3, 0.0, 0.7), ["Лист 09Г2С", "Швеллер", "Арматура А500"],
     {"Прейскурант": .6, "Спотовая закупка": .4}),
    ("Подшипники и РТИ", ["Подшипники", "Уплотнения РТИ"], (2e3, 150e3), 60,
     "Служба ТОиР", 0.0, 0.2, "шт", (0.8, 0.2, 0.0), ["Подшипник 22", "Манжета армированная"],
     {"Прейскурант": .5, "VMI": .3, "Рамочный договор": .2}),
    ("СИЗ и средства ПБ", ["Спецодежда", "Средства пожаротушения", "Газоанализаторы"], (2e3, 200e3), 30,
     "Служба промышленной безопасности", 0.0, 0.3, "шт", (0.9, 0.1, 0.0), ["Костюм ЗМИ", "Огнетушитель ОП", "Газоанализатор ГА"],
     {"Прейскурант": .7, "Рамочный договор": .3}),
    ("Оборудование эксплуатации скважин", ["Фонтанная арматура", "Сепараторы"], (500e3, 12e6), 200,
     "Служба эксплуатации оборудования", 0.5, 0.6, "шт", (0.1, 0.4, 0.5), ["Арматура фонтанная АФК", "Сепаратор НГС"],
     {"Спотовая закупка": .6, "Рамочный договор": .4}),
]
CLASS_INDEX = {c[0]: i for i, c in enumerate(CLASSES)}

PROFILE_CLASS_WEIGHTS = {
    "oil": [8, 9, 3, 8, 7, 7, 4, 7, 4, 3, 7, 4, 6, 4, 7],
    "gas": [5, 6, 7, 9, 8, 7, 5, 6, 5, 0, 5, 5, 5, 4, 3],
    "drill": [3, 3, 1, 9, 3, 3, 2, 3, 2, 14, 7, 4, 4, 4, 3],
    "refine": [8, 8, 6, 3, 9, 8, 5, 9, 7, 0, 6, 5, 7, 5, 0],
    "refine_gas": [7, 7, 7, 5, 8, 8, 5, 8, 6, 0, 5, 5, 6, 5, 0],
    "transport": [9, 8, 3, 6, 9, 8, 4, 6, 4, 0, 2, 3, 6, 5, 0],
    "service": [2, 2, 1, 1, 3, 3, 3, 3, 2, 0, 2, 3, 5, 9, 0],
}

MANUFACTURERS = ["Завод «Прогресс»", "Завод «Северный»", "Машзавод «Урал»", "Завод «Технопром»",
                 "ПО «Энергомаш»", "Завод «Приборист»", "Компания «ИмпортТех»", "Завод «Сталь-Трейд»"]
SUPPLIERS = [(f"S{i:02d}", n) for i, n in enumerate([
    "ООО «Поставщик-1 Снаб»", "ООО «ТехноСнаб»", "АО «НефтеКомплект»", "ООО «ПромИмпорт»", "ООО «Энерго-Ресурс»",
    "АО «Трубный Дом»", "ООО «Сибирь-МТР»", "ООО «Химтрейд»", "ООО «Арматура-Сервис»", "ООО «Приборы и Системы»",
    "ООО «БурТех»", "ООО «СИЗ-Опт»"], start=1)]

CRIT = ["A — критичный", "B — важный", "C — стандартный"]


@dataclass
class Project:
    project_id: str
    company_id: str
    direction_id: str
    name: str
    ptype: str
    program: str
    start_m: int
    end_m: int  # плановое окончание (первоначальное)
    status: str = "В графике"
    revised_end_m: int | None = None
    event_m: int | None = None  # месяц переноса / отмены / изменения тех. решения
    delay: int = 0


def _rng() -> np.random.Generator:
    return np.random.default_rng(SEED)


def build_dimensions(rng: np.random.Generator) -> dict[str, pd.DataFrame]:
    companies = pd.DataFrame(COMPANIES, columns=["company_id", "company_name", "segment", "ownership_type",
                                                 "region", "profile", "overbuy"])
    sites, whs = [], []
    si = 0
    for cid, _, seg, *_ in COMPANIES:
        prof = companies.set_index("company_id").loc[cid, "profile"]
        for k in range(2):
            name = SITE_NAMES[si % len(SITE_NAMES)]
            kind = "месторождение" if prof in ("oil", "gas", "drill") else ("площадка" if prof.startswith("refine") else "производственный участок")
            sid = f"{cid}-S{k + 1}"
            sites.append((sid, cid, f"{name} {kind}", f"Филиал «{name}»", f"БЕ-{cid[1:]}{k + 1}"))
            for w in range(1 + (k == 0)):
                whs.append((f"{sid}-W{w + 1}", sid, cid, f"Склад {name}-{w + 1}", f"ЦФО {cid}-{k + 1}{w + 1}"))
            si += 1
    sites = pd.DataFrame(sites, columns=["site_id", "company_id", "site_name", "branch", "business_unit"])
    whs = pd.DataFrame(whs, columns=["warehouse_id", "site_id", "company_id", "warehouse_name", "cfo"])
    directions = pd.DataFrame(DIRECTIONS, columns=["direction_id", "direction_name", "parent_id", "direction_group"])
    services = pd.DataFrame({"service_id": [f"SV{i + 1:02d}" for i in range(len(SERVICES))], "service_name": SERVICES})
    suppliers = pd.DataFrame(SUPPLIERS, columns=["supplier_id", "supplier_name"])
    suppliers["base_reliability"] = rng.uniform(0.78, 0.97, len(suppliers)).round(3)
    return dict(companies=companies, sites=sites, warehouses=whs, directions=directions, services=services,
                suppliers=suppliers)


def build_materials(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    code = 1000000
    for ci, (cls, groups, (pl, ph), lead, service, rep_p, crit_p, unit, mix, stems, pmodels) in enumerate(CLASSES):
        n = 42
        for i in range(n):
            gi = i % len(groups)
            stem = stems[gi % len(stems)]
            model = f"{int(rng.integers(10, 999))}-{int(rng.integers(1, 99)):02d}"
            price = float(np.exp(rng.uniform(np.log(pl), np.log(ph))))
            dtype = rng.choice(["regular", "intermittent", "project"], p=np.array(mix) / sum(mix))
            crit = rng.random() < crit_p
            critical = CRIT[0] if crit else (CRIT[1] if rng.random() < 0.4 else CRIT[2])
            supplier = f"S{int(rng.integers(1, len(SUPPLIERS) + 1)):02d}"
            pm = rng.choice(list(pmodels.keys()), p=np.array(list(pmodels.values())) / sum(pmodels.values()))
            code += int(rng.integers(1, 40))
            rows.append(dict(
                material_id=f"M{len(rows) + 1:04d}", nsi_code=f"МТР-{code}", material_name=f"{stem} {model}",
                mclass=cls, mgroup=groups[gi], msubgroup=f"{groups[gi]} — типоразмер {int(rng.integers(1, 5))}",
                manufacturer=str(rng.choice(MANUFACTURERS)), model=model, unit=unit, base_price=round(price, 2),
                lead_days=int(max(14, rng.normal(lead, lead * 0.25))), class_service=service, demand_type=str(dtype),
                criticality=critical, repairable=bool(rng.random() < rep_p), supplier_id=supplier,
                proc_model=str(pm), tech_spec=f"Исполнение {rng.choice(['УХЛ1', 'ХЛ1', 'У2', 'Т2'])}, класс {int(rng.integers(1, 6))}",
                equipment_model=(f"{stems[0]}-{int(rng.integers(1, 6))}" if cls.startswith("ЗИП") or cls.startswith("Насос") or cls.startswith("Компрессор") else None),
                analog_group=None, analog_status=None, is_duplicate_seed=False,
            ))
    mat = pd.DataFrame(rows)
    # Аналоги: группы по подгруппе и близкой цене
    ag = 1
    for (cls, sub), g in mat.groupby(["mclass", "msubgroup"]):
        idx = list(g.sort_values("base_price").index)
        for j in range(0, len(idx) - 1, 3):
            chunk = idx[j:j + 2 + int(rng.integers(0, 2))]
            if len(chunk) >= 2 and rng.random() < 0.55:
                mat.loc[chunk, "analog_group"] = f"AG{ag:03d}"
                mat.loc[chunk, "analog_status"] = "Подтверждён" if rng.random() < 0.45 else "Кандидат — на техническую проверку"
                ag += 1
    # Дубли НСИ: та же позиция заведена под другим кодом (иное написание наименования)
    dups = []
    for k, i in enumerate(rng.choice(mat.index, 18, replace=False)):
        r = mat.loc[i].to_dict()
        r["material_id"] = f"M{len(mat) + len(dups) + 1:04d}"
        r["nsi_code"] = f"МТР-{9000000 + k * 7}"
        r["material_name"] = r["material_name"].upper().replace(" ", "  ", 1) if k % 2 else r["material_name"] + " "
        r["is_duplicate_seed"] = True
        dups.append(r)
    mat = pd.concat([mat, pd.DataFrame(dups)], ignore_index=True)
    return mat


def build_projects(rng: np.random.Generator, companies: pd.DataFrame) -> list[Project]:
    projects: list[Project] = []
    names = {"D01": ["Строительство УКПГ", "Строительство ДНС", "Строительство газопровода-отвода", "Строительство ЛЭП 35 кВ",
                     "Строительство резервуарного парка"],
             "D02": ["Эксплуатационное бурение, куст", "Бурение горизонтальных скважин, куст"],
             "D03": ["ОНСС: оснащение скважин, куст"], "D04": ["ГРР: поисково-оценочная скважина"],
             "D05": ["Обустройство куста скважин", "Обустройство участка"],
             "D06": ["Реконструкция установки", "Модернизация насосной станции", "Техперевооружение АСУТП"]}
    k = 1
    for _, c in companies.iterrows():
        for d in PROFILE_DIRECTIONS[c.profile]["capex"]:
            for j in range(1 + int(rng.integers(0, 2)) + (d in ("D01", "D02"))):
                start = int(rng.integers(-4, 32))
                dur = int(rng.integers(8, 22))
                nm = names[d][j % len(names[d])]
                prog = "Газовая программа" if (c.profile == "gas" and d in ("D01", "D05")) or (c.company_id == "C09" and d == "D01") else "Вне программ"
                ptype = {"D01": "Капитальное строительство", "D02": "Бурение", "D03": "ОНСС", "D04": "Геологоразведка",
                         "D05": "Обустройство", "D06": "Реконструкция и модернизация"}[d]
                projects.append(Project(f"P{k:03d}", c.company_id, d, f"{nm} №{int(rng.integers(1, 40))}", ptype, prog,
                                        start, start + dur))
                k += 1
    # Сценарии-аномалии (демо)
    def pick(cid, d, prog=None):
        for p in projects:
            if p.company_id == cid and p.direction_id == d and (prog is None or p.program == prog):
                return p
        return None
    g = pick("C02", "D01", "Газовая программа")
    if g:  # перенос газового проекта: потребление остановлено, обязательства сохранились
        g.name, g.start_m, g.end_m = "Строительство УКПГ-2 (газовая программа)", 12, 34
        g.status, g.event_m, g.delay = "Перенесён", 22, 22
        g.revised_end_m = g.end_m + g.delay
    g2 = pick("C07", "D05", "Газовая программа")
    if g2:
        g2.start_m, g2.end_m, g2.status, g2.event_m, g2.delay = 16, 40, "Перенесён", 27, 15
        g2.revised_end_m = g2.end_m + g2.delay
    d = pick("C03", "D02")
    if d:  # отмена бурения: остатки и открытые заказы
        d.name, d.start_m, d.end_m, d.status, d.event_m = "Бурение горизонтальных скважин, куст 14", 20, 38, "Отменён", 27
    c6 = pick("C06", "D01")
    if c6:  # закупки перед завершением проекта
        c6.name, c6.start_m, c6.end_m = "Строительство резервуарного парка №3", 18, 37
    t = pick("C01", "D06")
    if t:  # изменение технического решения
        t.name, t.start_m, t.end_m, t.status, t.event_m = "Модернизация насосной станции №2", 10, 30, "Изменено техническое решение", 19
    for p in projects:
        if p.revised_end_m is None:
            p.revised_end_m = p.end_m
        if p.status == "В графике" and p.revised_end_m < N_MONTHS - 1:
            p.status = "Завершён"
    return projects


def activity_index(rng, companies) -> pd.DataFrame:
    rows = []
    for _, c in companies.iterrows():
        base = 100.0
        trend = rng.uniform(-0.1, 0.35)
        for m in range(N_MONTHS):
            v = base + trend * m + 4 * math.sin(2 * math.pi * (month_start(m).month - 3) / 12) + rng.normal(0, 1.5)
            if c.company_id == "C08" and m >= 21:
                v *= max(0.68, 1 - 0.022 * (m - 20))  # падение добычи
            rows.append((c.company_id, m, round(v, 2)))
    return pd.DataFrame(rows, columns=["company_id", "m", "activity_index"])


def price_index(rng) -> np.ndarray:
    """Индекс цен по классам МТР (m=-1..N-1). Ступень по трубной продукции в m=30."""
    idx = np.ones((len(CLASSES), N_MONTHS + 1))
    for ci in range(len(CLASSES)):
        infl = rng.uniform(0.004, 0.009)
        for m in range(1, N_MONTHS + 1):
            step = 1 + infl + rng.normal(0, 0.002)
            if CLASSES[ci][0] == "Трубная продукция" and m == 31:  # -> calendar m=30
                step += 0.08
            idx[ci, m] = idx[ci, m - 1] * step
    return idx  # column 0 = m=-1


def generate(seed: int = SEED) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    dims = build_dimensions(rng)
    companies = dims["companies"]
    materials = build_materials(rng)
    projects = build_projects(rng, companies)
    act = activity_index(rng, companies)
    act_map = {(r.company_id, r.m): r.activity_index for r in act.itertuples()}
    pidx = price_index(rng)
    supp_rel = dims["suppliers"].set_index("supplier_id")["base_reliability"].to_dict()

    svc_id = dims["services"].set_index("service_name")["service_id"].to_dict()
    whs_by_c = dims["warehouses"].groupby("company_id")["warehouse_id"].apply(list).to_dict()
    proj_by = {}
    for p in projects:
        proj_by.setdefault((p.company_id, p.direction_id), []).append(p)

    # объекты проектов (скважины, площадки)
    objects = []
    for p in projects:
        n_obj = 3 if p.direction_id in ("D02", "D03", "D04") else 2
        for o in range(n_obj):
            if p.direction_id in ("D02", "D03", "D04"):
                nm = f"Скважина №{int(rng.integers(100, 999))}"
            else:
                nm = ["Площадка основных сооружений", "Внеплощадочные сети", "Узел подключения"][o % 3]
            objects.append((f"{p.project_id}-O{o + 1}", p.project_id, nm))
    objects_df = pd.DataFrame(objects, columns=["object_id", "project_id", "object_name"])
    obj_by_p = objects_df.groupby("project_id")["object_id"].apply(list).to_dict()

    # ---------------- позиции учёта ----------------
    positions = []
    mats_by_class = materials[~materials.is_duplicate_seed].groupby("mclass")["material_id"].apply(list).to_dict()
    mat = materials.set_index("material_id")
    pos_id = 0
    for _, c in companies.iterrows():
        weights = np.array(PROFILE_CLASS_WEIGHTS[c.profile], dtype=float)
        weights /= weights.sum()
        n_pos = 520 if c.profile != "service" else 220
        chosen = set()
        for _ in range(n_pos):
            cls = CLASSES[rng.choice(len(CLASSES), p=weights)][0]
            mid = str(rng.choice(mats_by_class[cls]))
            m_ = mat.loc[mid]
            dtype = m_.demand_type
            capex = PROFILE_DIRECTIONS[c.profile]["capex"]
            opex = PROFILE_DIRECTIONS[c.profile]["opex"]
            if dtype == "project" and capex:
                d = str(rng.choice(capex))
                plist = proj_by.get((c.company_id, d), [])
                proj = plist[int(rng.integers(0, len(plist)))] if plist else None
            else:
                if dtype == "project":
                    dtype = "regular"
                d = str(rng.choice(opex))
                proj = None
            obj = str(rng.choice(obj_by_p[proj.project_id])) if proj else None
            wh = str(rng.choice(whs_by_c[c.company_id]))
            service = m_.class_service if c.profile != "drill" or m_.mclass in ("Буровой инструмент", "Трубная продукция") \
                else ("Служба бурения" if rng.random() < 0.5 else m_.class_service)
            if m_.mclass == "Металлопрокат" and proj is None:
                service = "Служба ТОиР"
            key = (wh, mid, d, obj)
            if key in chosen:
                continue
            chosen.add(key)
            pos_id += 1
            legacy = rng.random() < 0.09
            positions.append(dict(position_id=f"POS{pos_id:05d}", company_id=c.company_id, warehouse_id=wh,
                                  material_id=mid, direction_id=d, service_id=svc_id[service],
                                  project_id=proj.project_id if proj else None, object_id=obj,
                                  demand_type=("legacy" if legacy else dtype)))
    pos = pd.DataFrame(positions)

    # Позиции дублирующих кодов НСИ: часть запаса учтена под дублем
    dup_mats = materials[materials.is_duplicate_seed]
    extra = []
    for _, dm in dup_mats.iterrows():
        orig = pos[(pos.material_id.isin(materials[(materials.material_name.str.strip().str.upper().str.replace("  ", " ") ==
                                                    dm.material_name.strip().upper().replace("  ", " ")) & ~materials.is_duplicate_seed].material_id))]
        cid = str(rng.choice(companies.company_id))
        if len(orig):
            cid = orig.iloc[0].company_id
        pos_id += 1
        extra.append(dict(position_id=f"POS{pos_id:05d}", company_id=cid, warehouse_id=str(rng.choice(whs_by_c[cid])),
                          material_id=dm.material_id, direction_id="D08", service_id=svc_id[dm.class_service],
                          project_id=None, object_id=None, demand_type="legacy"))
    # Сценарий A7: дефицит критичного ЗИП в C08 при свободном запасе в C01
    zip_mid = mats_by_class["ЗИП насосного оборудования"][0]
    materials.loc[materials.material_id == zip_mid, ["criticality", "material_name", "lead_days", "supplier_id"]] = \
        [CRIT[0], "Уплотнение торцевое ЦНС 180-1422", 210, "S07"]
    for cid, dt_ in (("C08", "zip_deficit"), ("C01", "zip_surplus"), ("C06", "zip_surplus")):
        pos_id += 1
        extra.append(dict(position_id=f"POS{pos_id:05d}", company_id=cid, warehouse_id=whs_by_c[cid][0],
                          material_id=zip_mid, direction_id="D08", service_id=svc_id["Механическая служба"],
                          project_id=None, object_id=None, demand_type=dt_))
    pos = pd.concat([pos, pd.DataFrame(extra)], ignore_index=True)
    mat = materials.set_index("material_id")
    proj_map = {p.project_id: p for p in projects}

    # Политика пополнения и собственность
    def policy(r):
        m_ = mat.loc[r.material_id]
        if r.demand_type in ("legacy",):
            return "Не определена"
        if r.demand_type == "project":
            return "Проектная (под потребность)"
        if r.demand_type in ("intermittent", "zip_deficit", "zip_surplus"):
            return "Страховой запас" if m_.criticality == CRIT[0] else "По потребности"
        return "Мин-макс"
    pos["replenishment_policy"] = pos.apply(policy, axis=1)
    pos["balance_ownership"] = "Собственный"
    cons_mask = (pos.company_id.isin(["C04", "C09", "C05"]) & pos.demand_type.eq("regular") &
                 pos.material_id.map(mat["proc_model"]).eq("Консигнация"))
    pos.loc[cons_mask, "balance_ownership"] = "Консигнация (собственность поставщика)"

    # Справочник ремонтопригодности/оборудования
    equipment = []
    eq_models = materials.dropna(subset=["equipment_model"]).equipment_model.unique()
    for _, c in companies.iterrows():
        for e in rng.choice(eq_models, 8, replace=False):
            lam = float(rng.uniform(0.3, 2.5))
            equipment.append((f"EQ-{c.company_id}-{e}", c.company_id, e, f"{e} (агрегатов: {int(rng.integers(2, 12))})",
                              int(rng.integers(2, 12)), round(lam, 2), round(8760 / lam), int(rng.integers(8, 96)),
                              str(rng.choice(CRIT[:2]))))
    equipment = pd.DataFrame(equipment, columns=["equipment_id", "company_id", "equipment_model", "equipment_name",
                                                 "units", "failure_rate_year", "mtbf_hours", "mttr_hours", "criticality"])

    # ---------------- имитация ----------------
    snap_rows, mov_rows, dem_rows, po_rows, short_rows = [], [], [], [], []
    service_bias = {"КИПиА": 1.45, "АСУТП": 1.2, "Энергетическая служба": 1.12}
    svc_name = dims["services"].set_index("service_id")["service_name"].to_dict()
    po_seq = 0
    overbuy = companies.set_index("company_id")["overbuy"].to_dict()

    # План межобщественных перемещений (из избыточного запаса в позицию с потребностью)
    transfers: dict[tuple[str, int], float] = {}
    legacy_pos = pos[pos.demand_type == "legacy"]
    reg_pos = pos[pos.demand_type == "regular"]
    tr_pairs = []
    for _, lp in legacy_pos.sample(frac=1, random_state=seed).iterrows():
        cand = reg_pos[(reg_pos.material_id == lp.material_id) & (reg_pos.company_id != lp.company_id)]
        if len(cand):
            tgt = cand.iloc[0]
            tm = int(rng.integers(8, N_MONTHS - 1))
            tr_pairs.append((lp.position_id, tgt.position_id, tm))
        if len(tr_pairs) >= 40:
            break
    init_q = {}
    disposal_cases = []

    def P(ci, m):
        return pidx[ci, m + 1]

    # источники перемещений обрабатываются первыми, чтобы приход у получателя был известен
    src_ids = {a for a, _, _ in tr_pairs}
    order_idx = sorted(range(len(pos)), key=lambda i: 0 if pos.position_id.iat[i] in src_ids else 1)
    for r in pos.iloc[order_idx].itertuples(index=False):
        m_ = mat.loc[r.material_id]
        ci = CLASS_INDEX[m_.mclass]
        p0 = float(m_.base_price)
        lead_m = max(1, math.ceil(m_.lead_days / 30))
        sv = svc_name[r.service_id]
        bias = service_bias.get(sv, 1.0 + 0.08 * (overbuy[r.company_id] - 1) * 5)
        proj = proj_map.get(r.project_id) if r.project_id else None
        price_scale = 1.0 if p0 < 1e6 else 0.5
        q = 0.0
        # входящий остаток и даты
        if r.demand_type == "regular":
            mu = max(0.2, rng.gamma(2.0, 3.0) * (1e5 / p0) ** 0.35)
            q = float(np.round(mu * bias * (0.5 * (lead_m + 1) + rng.uniform(0.6, 1.6) * overbuy[r.company_id])))
            last_r = month_start(0) - dt.timedelta(days=int(rng.integers(5, 200)))
            last_i = month_start(0) - dt.timedelta(days=int(rng.integers(1, 40)))
        elif r.demand_type in ("intermittent", "zip_deficit", "zip_surplus"):
            mu = 0.0
            q = float(rng.integers(0, 4)) if m_.criticality == CRIT[0] else float(rng.integers(0, 3))
            p_dem = rng.uniform(0.03, 0.18)
            if r.demand_type == "zip_deficit":
                q, p_dem = 1.0, 0.45
            if r.demand_type == "zip_surplus":
                q, p_dem = (9.0 if r.company_id == "C01" else 5.0), 0.0
            last_r = month_start(0) - dt.timedelta(days=int(rng.integers(30, 1400)))
            last_i = month_start(0) - dt.timedelta(days=int(rng.integers(30, 1500)))
        elif r.demand_type == "project":
            mu = 0.0
            last_r = None
            last_i = None
        else:  # legacy
            mu = 0.0
            q = float(max(1, np.round(rng.gamma(1.5, 6.0) * price_scale)))
            last_r = month_start(0) - dt.timedelta(days=int(rng.integers(500, 2600)))
            last_i = last_r + dt.timedelta(days=int(rng.integers(0, 300)))
        init_q[r.position_id] = q
        # проектная потребность
        R = 0.0
        if r.demand_type == "project" and proj:
            R = float(max(2, np.round(rng.gamma(2.0, 8.0) * (2e5 / p0) ** 0.4 * 3)))
        sched_plan = np.zeros(N_MONTHS + FUTURE)
        sched_actual = np.zeros(N_MONTHS + FUTURE)
        receipts_plan = {}
        if R > 0:
            s0, e0 = proj.start_m, max(proj.start_m + 2, proj.end_m)
            span = list(range(s0, e0 + 1))
            for mm in span:
                if 0 <= mm < N_MONTHS + FUTURE:
                    sched_plan[mm] = R / len(span)
            # фактический график
            for mm in span:
                tgt = mm
                if proj.status == "Перенесён" and mm >= proj.event_m:
                    tgt = mm + proj.delay
                if proj.status == "Отменён" and mm >= proj.event_m:
                    continue
                if 0 <= tgt < N_MONTHS + FUTURE:
                    sched_actual[tgt] += R / len(span)
            over = rng.uniform(1.02, 1.11) * (1.45 if proj.status == "Изменено техническое решение" else 1.0)
            # закупка: поставки за lead до потребности, обязательства по графику
            for mm in span:
                order_m = mm - lead_m - 1
                if proj.status in ("Перенесён", "Отменён") and order_m > proj.event_m + 2:
                    continue  # после переноса/отмены новые заказы не размещаются (2 мес. — инерция)
                if proj.status == "Изменено техническое решение" and order_m > proj.event_m:
                    continue
                receipts_plan[order_m] = receipts_plan.get(order_m, 0) + R / len(span) * over
            if proj.company_id == "C06" and proj.direction_id == "D01":
                for mm in (33, 34, 35):  # закупки перед завершением проекта
                    receipts_plan[mm - lead_m] = receipts_plan.get(mm - lead_m, 0) + R * 0.12
            last_r = month_start(max(0, s0 - lead_m)) if s0 - lead_m < 0 else None

        pipeline: list[tuple[int, float, str]] = []
        # заказы, размещённые до начала горизонта данных
        for om in sorted(k for k in receipts_plan if k < 0):
            qty0 = float(np.ceil(receipts_plan[om]))
            arr0 = om + lead_m
            if arr0 < 0:
                q += qty0
                last_r = month_start(0) - dt.timedelta(days=15 * (1 - arr0))
            else:
                po_seq += 1
                pid0 = f"PO{po_seq:06d}"
                pipeline.append((arr0, qty0, pid0))
                po_rows.append(dict(po_id=pid0, position_id=r.position_id, supplier_id=m_.supplier_id, proc_model=m_.proc_model,
                                    req_date=month_start(0) - dt.timedelta(days=60), order_date=month_start(0) - dt.timedelta(days=30 * (-om)),
                                    qty=qty0, price=p0 * P(ci, 0), value=qty0 * p0 * P(ci, 0),
                                    planned_delivery=month_start(arr0) + dt.timedelta(days=14),
                                    actual_delivery=month_start(arr0) + dt.timedelta(days=int(rng.integers(0, 27))),
                                    need_date=month_start(max(0, proj.start_m)), arr_m=arr0))
        init_q[r.position_id] = q
        nvi = nli = nr = vr = False
        flag_m = None
        if r.demand_type == "legacy" and rng.random() < 0.5:
            flags = rng.random(4)
            nvi, nli, nr, vr = bool(flags[0] < .45), bool(flags[1] < .3), bool(flags[2] < .2), bool(flags[3] < .15)
            if not (nvi or nli or nr or vr):
                nvi = True
            flag_m = int(rng.integers(0, 30))
        sell_plan = {}
        if flag_m is not None:
            # процесс выбытия (быстрее в C05 — положительная практика)
            speed = 0.6 if r.company_id == "C05" else 1.0
            stages_m = flag_m + int(rng.integers(3, 9) * speed)
            route = rng.choice(["Реализация", "Утилизация", "Внутреннее применение", "Восстановление", "В процессе"],
                               p=[0.35, 0.15, 0.12, 0.08, 0.30] if r.company_id != "C05" else [0.55, 0.15, 0.15, 0.05, 0.10])
            if route != "В процессе" and stages_m < N_MONTHS:
                sell_plan[stages_m] = route
            disposal_cases.append(dict(position_id=r.position_id, flag_m=flag_m, route=str(route), done_m=stages_m if route != "В процессе" else None))
        plan_mu = mu * bias
        proj_cum = sum(v for k, v in receipts_plan.items() if k < 0)
        proj_ordered = float(np.round(proj_cum))
        for m in range(N_MONTHS + FUTURE):
            if m >= N_MONTHS:
                # будущий план потребности
                if r.demand_type == "regular":
                    dem_rows.append((r.position_id, m, round(plan_mu * act_map[(r.company_id, N_MONTHS - 1)] / 100, 3),
                                     round(plan_mu * act_map[(r.company_id, N_MONTHS - 1)] / 100, 3)))
                elif R > 0:
                    pl = sched_actual[m] * (1.0 if proj.status != "Отменён" else 0)
                    dem_rows.append((r.position_id, m, round(sched_plan[m], 3), round(pl, 3)))
                elif r.demand_type in ("intermittent", "zip_deficit") and m % 6 == 0:
                    dem_rows.append((r.position_id, m, 1.0, 1.0))
                continue
            pr, pp = P(ci, m), P(ci, m - 1)
            price = p0 * pr
            open_q = q
            reval_v = open_q * p0 * (pr - pp)
            ms = month_start(m)
            dim = days_in_month(m)
            # поступления
            rec_q = 0.0
            arriving = [x for x in pipeline if x[0] == m]
            pipeline = [x for x in pipeline if x[0] != m]
            for _, qq, po in arriving:
                rec_q += qq
                mov_rows.append((r.position_id, m, ms + dt.timedelta(days=int(rng.integers(0, dim))), "Поступление", None, qq, qq * price, po))
            if R > 0 and m in receipts_plan:
                pass
            q += rec_q
            if rec_q > 0:
                last_r = ms + dt.timedelta(days=int(rng.integers(0, dim)))
            # перемещения
            for src, tgt, tm in tr_pairs:
                if tm == m and src == r.position_id and q > 1:
                    tq = float(max(1, np.floor(q * 0.4)))
                    transfers[(tgt, tm)] = tq
                    q -= tq
                    mov_rows.append((r.position_id, m, ms + dt.timedelta(days=10), "Перемещение (расход)", "Межобщественное", tq, tq * price, None))
            tin = transfers.get((r.position_id, m))
            if tin:
                q += tin
                mov_rows.append((r.position_id, m, ms + dt.timedelta(days=12), "Перемещение (приход)", "Межобщественное", tin, tin * price, None))
            # спрос и потребление
            a = act_map[(r.company_id, m)] / 100
            if r.demand_type == "regular":
                season = 1.0
                d_ = rng.poisson(mu * a * season)
                plan_q = plan_mu * (act_map[(r.company_id, max(0, m - 3))] / 100 if r.company_id != "C08" else 1.0)
            elif r.demand_type in ("intermittent", "zip_deficit", "zip_surplus"):
                d_ = int(rng.integers(1, 3)) if rng.random() < p_dem else 0
                plan_q = p_dem * 1.5 * bias
            elif R > 0:
                d_ = sched_actual[m] * rng.uniform(0.85, 1.1) if sched_actual[m] > 0 else 0
                d_ = float(np.round(d_, 1))
                plan_q = sched_plan[m] if (proj.event_m is None or m < proj.event_m) else sched_actual[m]
            else:
                d_, plan_q = 0, 0.0
            c_q = float(min(q, d_))
            unmet = float(d_ - c_q)
            if unmet > 0.01:
                short_rows.append((r.position_id, m, unmet, unmet * price))
            if c_q > 0:
                q -= c_q
                last_i = ms + dt.timedelta(days=int(rng.integers(0, dim)))
                mov_rows.append((r.position_id, m, last_i, "Потребление", None, c_q, c_q * price, None))
            dem_rows.append((r.position_id, m, round(plan_mu if r.demand_type == "regular" else plan_q, 3), round(plan_q, 3)))
            # возвраты из эксплуатации/подрядчиков
            if c_q > 2 and rng.random() < 0.06:
                ret = float(max(1, np.floor(c_q * 0.15)))
                q += ret
                mov_rows.append((r.position_id, m, ms + dt.timedelta(days=dim - 2), "Возврат", None, ret, ret * price, None))
            # инвентаризационные корректировки
            if q > 3 and rng.random() < 0.015:
                adj = float(rng.choice([-1, 1]) * max(1, np.floor(q * 0.03)))
                q += adj
                mov_rows.append((r.position_id, m, ms + dt.timedelta(days=dim - 1), "Корректировка", "Инвентаризация", adj, adj * price, None))
            # выбытие
            if m in sell_plan and q > 0:
                route = sell_plan[m]
                typ = {"Реализация": "Реализация", "Утилизация": "Списание", "Внутреннее применение": "Потребление",
                       "Восстановление": None}[route]
                if typ:
                    sq = q if route != "Внутреннее применение" else float(max(1, np.floor(q * 0.6)))
                    q -= sq
                    mov_rows.append((r.position_id, m, ms + dt.timedelta(days=20), typ, "Выбытие НВИ/НЛИ" if typ != "Потребление" else "Вовлечение", sq, sq * price, None))
                    if typ == "Потребление":
                        last_i = ms + dt.timedelta(days=20)
            # перезаказ
            lm = lead_m
            supplier = m_.supplier_id
            if supplier == "S07" and m >= 26:
                lm = int(math.ceil(lead_m * 1.6))
            order = 0.0
            if r.demand_type == "regular":
                pipe = sum(x[1] for x in pipeline)
                s_ = plan_mu * (lead_m + 1)
                S_ = s_ + plan_mu * rng.uniform(2, 3.5) * overbuy[r.company_id]
                if ms.month in (11, 12) and r.company_id in ("C01", "C04", "C08"):
                    S_ *= 1.5  # закупки в конце бюджетного года (повторяющийся паттерн)
                if q + pipe <= s_:
                    order = float(np.ceil(S_ - q - pipe))
            elif r.demand_type in ("intermittent", "zip_deficit"):
                pipe = sum(x[1] for x in pipeline)
                smin = 2 if m_.criticality == CRIT[0] else 0
                if r.demand_type == "zip_deficit":
                    smin = 2
                if q + pipe < max(1, smin) and (smin > 0 or unmet > 0):
                    order = float(max(1, smin + 1 - q - pipe))
            elif R > 0 and m in receipts_plan:
                proj_cum += receipts_plan[m]
                order = float(np.round(proj_cum) - proj_ordered)
                proj_ordered += max(0.0, order)
            if order > 0:
                po_seq += 1
                po_id = f"PO{po_seq:06d}"
                rel = supp_rel.get(supplier, 0.9)
                delay = 0 if rng.random() < rel else int(rng.integers(1, 3))
                if supplier == "S07" and m >= 26:
                    delay += int(rng.integers(1, 3))
                arr = m + lm + delay
                if r.demand_type == "zip_deficit":
                    arr = m + lm + 3
                pipeline.append((arr, order, po_id))
                need_m = (m + lead_m) if R == 0 else next((mm for mm in range(m, N_MONTHS + FUTURE) if sched_actual[mm] > 0), m + lead_m)
                po_rows.append(dict(po_id=po_id, position_id=r.position_id, supplier_id=supplier, proc_model=m_.proc_model,
                                    req_date=ms - dt.timedelta(days=int(rng.integers(10, 45))),
                                    order_date=ms + dt.timedelta(days=int(rng.integers(0, dim))), qty=order, price=price,
                                    value=order * price, planned_delivery=month_start(m + lm) + dt.timedelta(days=14),
                                    actual_delivery=(month_start(arr) + dt.timedelta(days=int(rng.integers(0, 27)))),
                                    need_date=month_start(need_m), arr_m=arr))
            # срез
            if r.demand_type == "project" and proj:
                remaining = max(0.0, sched_actual[m + 1:].sum())
                reserved = min(q, remaining if proj.status != "Отменён" else q * 0.8)
            elif r.demand_type == "regular" and int(r.position_id[3:]) % 3 == 0:
                reserved = min(q, float(np.round(mu * 0.5)))
            else:
                reserved = 0.0
            unavailable = float(np.floor(q * 0.25)) if int(r.position_id[3:]) % 23 == 0 else 0.0
            fut = {}
            for H in (3, 6, 12, 24):
                if r.demand_type == "regular":
                    fut[H] = plan_mu * H
                elif R > 0:
                    known = sched_plan if (proj.event_m is None or m < proj.event_m) else sched_actual
                    fut[H] = float(known[m + 1:m + 1 + H].sum())
                elif r.demand_type in ("intermittent", "zip_deficit"):
                    fut[H] = p_dem * 1.5 * H
                else:
                    fut[H] = 0.0
            flagged = flag_m is not None and m >= flag_m and q > 0
            snap_rows.append((r.position_id, m, q, q * price, price, reserved, unavailable,
                              last_r, last_i, fut[3], fut[6], fut[12], fut[24],
                              bool(flagged and nvi), bool(flagged and nli), bool(flagged and nr), bool(flagged and vr)))
            # переоценка как движение
            if abs(reval_v) > 0.005:
                mov_rows.append((r.position_id, m, month_end(m), "Переоценка", None, 0.0, reval_v, None))

    snapshot = pd.DataFrame(snap_rows, columns=["position_id", "m", "qty", "value", "price", "reserved_qty", "unavailable_qty",
                                                "last_receipt_date", "last_issue_date", "fut_need_3", "fut_need_6", "fut_need_12",
                                                "fut_need_24", "flag_nvi", "flag_nli", "flag_nr", "flag_vr"])
    movements = pd.DataFrame(mov_rows, columns=["position_id", "m", "date", "mtype", "subtype", "qty", "value", "po_id"])
    demand = pd.DataFrame(dem_rows, columns=["position_id", "m", "plan_init_qty", "plan_qty"])
    pos_df = pos
    po = pd.DataFrame(po_rows)
    shortages = pd.DataFrame(short_rows, columns=["position_id", "m", "unmet_qty", "unmet_value"])

    # входящий остаток m=-1 (для сверки m=0)
    opening = pd.DataFrame([(k, v) for k, v in init_q.items()], columns=["position_id", "qty"])
    first_price = snapshot[snapshot.m == 0][["position_id", "price"]]
    opening = opening.merge(first_price, on="position_id")
    ci_map = pos.material_id.map(lambda x: CLASS_INDEX[mat.loc[x, "mclass"]])
    pr_ratio = {pid: pidx[c, 0] / pidx[c, 1] for pid, c in zip(pos.position_id, ci_map)}
    opening["price"] = opening.apply(lambda r_: r_.price * pr_ratio[r_.position_id], axis=1)
    opening["value"] = opening.qty * opening.price

    # Процессы выбытия (НВИ/НЛИ/НР/ВР)
    disp = []
    snap_idx = snapshot.set_index(["position_id", "m"])
    stages = ["Выявлено", "Техническая оценка", "Согласование", "Подготовка к реализации", "Реализация/выбытие", "Закрыто"]
    for k, dc in enumerate(disposal_cases):
        pid = dc["position_id"]
        fm = dc["flag_m"]
        try:
            bv = float(snap_idx.loc[(pid, fm), "value"])
        except KeyError:
            continue
        if bv <= 0:
            continue
        route = dc["route"]
        done = dc["done_m"]
        durations = [int(rng.integers(1, 3)), int(rng.integers(1, 4)), int(rng.integers(1, 6)), int(rng.integers(1, 4))]
        if pos.loc[pos.position_id == pid, "company_id"].iloc[0] == "C05":
            durations = [max(1, d // 2) for d in durations]
        proceeds = bv * rng.uniform(0.08, 0.35) if route == "Реализация" and done is not None else 0.0
        costs = bv * rng.uniform(0.01, 0.05) + (bv * 0.03 if route == "Утилизация" else 0)
        current_stage = "Закрыто" if done is not None else stages[min(4, int(rng.integers(0, 5)))]
        issue = None
        if current_stage in ("Согласование", "Техническая оценка") and rng.random() < 0.5:
            issue = str(rng.choice(["Нет заключения технической службы", "Не согласована цена реализации",
                                    "Ожидается решение органа управления СП", "Нет покупателя на торгах"]))
        disp.append(dict(case_id=f"DC{k + 1:04d}", position_id=pid, flag_month=fm, route=route,
                         stage=current_stage, done_month=done, book_value=round(bv, 2),
                         cash_proceeds=round(proceeds, 2), disposal_costs=round(costs, 2),
                         stage_days_assessment=durations[0] * 30, stage_days_approval=durations[1] * 30,
                         stage_days_preparation=durations[2] * 30, stage_days_execution=durations[3] * 30,
                         approval_issue=issue))
    disposal = pd.DataFrame(disp)

    # Ремонтный фонд
    rep = []
    rep_mats = materials[materials.repairable & ~materials.is_duplicate_seed]
    for k, (_, rm) in enumerate(rep_mats.sample(min(90, len(rep_mats)), random_state=seed).iterrows()):
        cands = pos[pos.material_id == rm.material_id]
        if not len(cands):
            continue
        pr_ = cands.iloc[0]
        new_price = float(rm.base_price) * float(pidx[CLASS_INDEX[rm.mclass], -1])
        rep.append(dict(repair_id=f"RF{k + 1:04d}", position_id=pr_.position_id, units_in_fund=int(rng.integers(1, 8)),
                        units_need_repair=int(rng.integers(0, 6)), units_ready=int(rng.integers(0, 4)),
                        condition=str(rng.choice(["Требует ремонта", "Исправен (восстановлен)", "Неремонтопригоден"], p=[.6, .3, .1])),
                        repair_cost=round(new_price * rng.uniform(0.18, 0.55), 2), repair_days=int(rng.integers(20, 120)),
                        new_price=round(new_price, 2), new_lead_days=int(rm.lead_days),
                        diagnostic_cost=round(new_price * rng.uniform(0.01, 0.04), 2),
                        logistics_cost=round(new_price * rng.uniform(0.01, 0.05), 2),
                        exchange_fee=round(new_price * rng.uniform(0.35, 0.6), 2) if rng.random() < 0.5 else None,
                        warranty_new_months=24, warranty_repair_months=int(rng.choice([6, 12, 12, 18])),
                        mtbf_ratio_after_repair=round(rng.uniform(0.6, 0.95), 2),
                        annual_need_units=round(float(rng.uniform(0.5, 6)), 1),
                        tech_restriction=str(rng.choice(["Нет", "Нет", "Только для неответственных узлов",
                                                         "Требуется заключение завода-изготовителя"]))))
    repair = pd.DataFrame(rep)

    # Финансовая база (демо): оборотные активы общества
    fin = []
    tot_by_cm = snapshot.merge(pos[["position_id", "company_id"]], on="position_id").groupby(["company_id", "m"]).value.sum()
    for (cid, m), v in tot_by_cm.items():
        fin.append((cid, m, float(v) * rng.uniform(3.2, 4.2), float(v) * rng.uniform(9, 14)))
    finance = pd.DataFrame(fin, columns=["company_id", "m", "current_assets", "revenue_ltm"])

    projects_df = pd.DataFrame([p.__dict__ for p in projects])

    data = dict(**dims, materials=materials, positions=pos_df, projects=projects_df, objects=objects_df,
                snapshot=snapshot, opening=opening, movements=movements, demand=demand, purchase_orders=po,
                shortages=shortages, disposal=disposal, repair_fund=repair, equipment=equipment, activity=act,
                finance=finance)
    inject_dq_issues(data, rng)
    return data


def inject_dq_issues(data: dict[str, pd.DataFrame], rng) -> None:
    """Намеренно вносимые нарушения качества данных (для демонстрации вкладки «Качество данных»).
    Каждое искажение записывается в таблицу dq_injected, чтобы тесты могли проверить, что контроль их находит."""
    log = []
    pos = data["positions"]
    # 1) пропуск обязательной аналитики «служба»
    idx = pos.sample(6, random_state=1).index
    data["positions"].loc[idx, "service_id"] = None
    log += [("missing_service", p) for p in pos.loc[idx, "position_id"]]
    # 2) расхождение остатка с движениями (ручная правка остатка без документа)
    snap = data["snapshot"]
    sel = snap[(snap.m == 30) & (snap.qty > 5)].sample(5, random_state=2).index
    for i in sel:
        snap.loc[i, "qty"] += 2
        snap.loc[i, "value"] += 2 * snap.loc[i, "price"]
        log.append(("balance_mismatch", snap.loc[i, "position_id"]))
    # 3) резерв больше остатка
    sel = snap[(snap.m == N_MONTHS - 1) & (snap.qty > 0)].sample(4, random_state=3).index
    snap.loc[sel, "reserved_qty"] = snap.loc[sel, "qty"] + 3
    log += [("reserve_exceeds", p) for p in snap.loc[sel, "position_id"]]
    # 4) несоответствие единиц измерения в движениях
    mov = data["movements"]
    sel = mov[mov.mtype == "Потребление"].sample(7, random_state=4).index
    mov["unit"] = None
    mov.loc[sel, "unit"] = "кг"
    log += [("unit_mismatch", p) for p in mov.loc[sel, "position_id"]]
    # 5) валюта: часть заказов в USD без пересчёта
    po = data["purchase_orders"]
    po["currency"] = "RUB"
    sel = po.sample(5, random_state=5).index
    po.loc[sel, "currency"] = "USD"
    log += [("currency", p) for p in po.loc[sel, "po_id"]]
    data["dq_injected"] = pd.DataFrame(log, columns=["issue", "ref"])


def save(data: dict[str, pd.DataFrame], path) -> None:
    import pathlib
    p = pathlib.Path(path)
    p.mkdir(parents=True, exist_ok=True)
    for k, df in data.items():
        df.to_parquet(p / f"{k}.parquet", index=False)


if __name__ == "__main__":
    import sys, time
    t = time.time()
    d = generate()
    out = sys.argv[1] if len(sys.argv) > 1 else "data/demo"
    save(d, out)
    print({k: len(v) for k, v in d.items()}, f"{time.time() - t:.1f}s")
