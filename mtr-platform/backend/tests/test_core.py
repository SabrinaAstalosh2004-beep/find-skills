"""Тесты расчётов, согласованности данных, доступа и API."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import db, engine, forecast, insights, scenarios
from app import settings as cfg
from app.filters import Ctx


@pytest.fixture(scope="session", autouse=True)
def _init(tmp_path_factory):
    act_file = cfg.DATA_DIR / "actions.parquet"
    backup = act_file.read_bytes() if act_file.exists() else None
    cfg.reset()
    db.init()
    yield
    cfg.reset()
    if backup is None:
        act_file.unlink(missing_ok=True)
    else:
        act_file.write_bytes(backup)


def ctx(**kw):
    a = kw.pop("asof", 36)
    w = kw.pop("window", 12)
    return Ctx(asof=a, window=w, m1=a - w + 1, **kw)


# ----------------------------- сверка и аддитивность -----------------------------
def test_group_waterfall_reconciles():
    k = engine.kpis(ctx(window=24))
    flows = k["receipts"] + k["returns"] + k["tr_in"] - k["consumption"] - k["tr_out"] + k["adjust"] + k["reval"] - k["sales"] - k["writeoff"]
    assert math.isclose(k["stock_start"] + flows + k["discrepancy"], k["stock_end"], rel_tol=1e-9)
    # искажения внесены только в m=30 (и компенсируются в m=31) — в окне 24 мес. итоговое расхождение ≈ 0
    assert abs(k["discrepancy"]) < 1.0


def test_position_reconciliation_detects_only_injected():
    inj = set(db.q("SELECT ref FROM dq_injected WHERE issue='balance_mismatch'").ref)
    from app import dq
    res = dq.run(ctx())
    chk = next(c for c in res["checks"] if c["id"] == "recon")
    found = {r["position_id"] for r in chk["sample"]}
    assert chk["count"] == 2 * len(inj)  # месяц искажения и следующий месяц
    assert found <= inj


def test_additivity_no_double_count():
    c = ctx()
    tot = engine.kpis(c)["stock_end"]
    for dims in (["company"], ["direction"], ["service"], ["mclass"], ["program", "dgroup"]):
        a = engine.aggregate(c, dims, parts=("snap",))
        assert math.isclose(a.stock_end.sum(), tot, rel_tol=1e-9), dims


def test_gas_program_included_once():
    c = ctx()
    gas = engine.kpis(c.with_filters(program=["Газовая программа"]))["stock_end"]
    other = engine.kpis(c.with_filters(program=["Вне программ"]))["stock_end"]
    assert math.isclose(gas + other, engine.kpis(c)["stock_end"], rel_tol=1e-9)
    by_dir = engine.aggregate(c.with_filters(program=["Газовая программа"]), ["direction"], parts=("snap",))
    assert math.isclose(by_dir.stock_end.sum(), gas, rel_tol=1e-9)


# ----------------------------- оборачиваемость -----------------------------------
def test_turnover_formula_and_group_from_sums():
    c = ctx()
    k = engine.kpis(c)
    assert math.isclose(k["turnover_days"], k["stock_avg"] / k["consumption"] * c.days(), rel_tol=1e-9)
    a = engine.aggregate(c, ["company"], parts=("snap", "mov"))
    from_sums = a.stock_avg.sum() / a.consumption.sum() * c.days()
    assert math.isclose(from_sums, k["turnover_days"], rel_tol=1e-9)
    assert not math.isclose(a.turnover_days.mean(), k["turnover_days"], rel_tol=1e-3)  # среднее по обществам — не групповой показатель


def test_chronological_average():
    c = ctx(window=3)
    s = engine.series(c, [], c.m1 - 1, c.m2).set_index("m").stock
    expect = (s[c.m1 - 1] / 2 + s[c.m1] + s[c.m1 + 1] + s[c.m2] / 2) / 3
    assert math.isclose(engine.kpis(c)["stock_avg"], expect, rel_tol=1e-9)


def test_zero_consumption_gives_status_not_days():
    a = engine.aggregate(ctx(), ["demand_type"], parts=("snap", "mov"))
    row = a[a.demand_type == "Без потребности"]
    if len(row) and row.consumption.iloc[0] <= 0:
        assert np.isnan(row.turnover_days.iloc[0])
    df = pd.DataFrame({"stock_end": [10.0], "consumption": [0.0]})
    from app.metrics import derive
    base = {c: [0.0] for c in engine.BASE_COLS}
    base.update(stock_end=[10.0], stock_avg=[10.0])
    d = derive(pd.DataFrame(base), 30, 1)
    assert np.isnan(d.turnover_days.iloc[0])


# ----------------------------- НЭЗ -----------------------------------------------
def test_nez_flow_reconciles():
    k = engine.kpis(ctx(window=24))
    calc = k["nez_start"] + k["nez_new"] - k["nez_consumed"] - k["nez_transferred"] - k["nez_sold"] - k["nez_written_off"] - k["nez_reclass_out"] + k["nez_reval"]
    assert math.isclose(calc, k["nez_end"], rel_tol=1e-6)


def test_nez_excludes_protected_stock():
    d = db.q("SELECT SUM(nez_value) v FROM snap WHERE nez_protected")
    assert (d.v.iloc[0] or 0) == 0


def test_nez_threshold_is_configurable_and_monotonic():
    base = engine.kpis(ctx())["nez_end"]
    cfg.update({"nez": {"no_issue_days": 730}})
    db.build_views()
    stricter = engine.kpis(ctx())["nez_end"]
    cfg.reset()
    db.build_views()
    assert stricter < base
    assert math.isclose(engine.kpis(ctx())["nez_end"], base, rel_tol=1e-9)


# ----------------------------- фильтры и доступ ----------------------------------
def test_filter_matches_breakdown():
    c = ctx()
    a = engine.aggregate(c, ["company"]).set_index("company")
    k = engine.kpis(c.with_filters(company=["C02"]))
    assert math.isclose(k["stock_end"], a.loc["C02", "stock_end"], rel_tol=1e-9)
    assert math.isclose(k["nez_end"], a.loc["C02", "nez_end"], rel_tol=1e-9)


def test_direction_group_filter_expands():
    c = ctx()
    capex = engine.kpis(c.with_filters(direction=["G_CAPEX"]))["stock_end"]
    g = engine.aggregate(c, ["dgroup"], parts=("snap",)).set_index("dgroup")
    assert math.isclose(capex, g.loc["CAPEX", "stock_end"], rel_tol=1e-9)


def test_role_access():
    c1 = engine.aggregate(ctx(role="c01"), ["company"], parts=("snap",))
    assert set(c1.company) == {"C01"}
    an = engine.aggregate(ctx(role="analyst"), ["ownership"], parts=("snap",))
    assert "СП" not in set(an.ownership)
    client = TestClient(__import__("app.main", fromlist=["app"]).app)
    r = client.get("/api/vitrine/1?company=C02", headers={"x-role": "c01"})
    assert r.status_code == 200 and r.json()["ctx"]["filters"]["company"] == ["C01"]
    r = client.get("/api/position/" + db.q("SELECT position_id FROM positions WHERE company_id='C02' LIMIT 1").position_id.iloc[0], headers={"x-role": "c01"})
    assert r.status_code == 404


# ----------------------------- прогнозирование -----------------------------------
def test_forecast_no_leakage():
    rng = np.random.default_rng(1)
    y = rng.poisson(0.4, 30).astype(float)
    for m in forecast.METHODS:
        f1 = forecast.one_step(y, m)
        y2 = y.copy()
        y2[20:] = 99
        f2 = forecast.one_step(y2, m)
        assert np.allclose(np.nan_to_num(f1[:21]), np.nan_to_num(f2[:21])), m


def test_croston_sba_values():
    y = np.array([0, 0, 4, 0, 0, 0, 2, 0, 3, 0], dtype=float)
    f = forecast.one_step(y, "croston", alpha=0.1)
    fs = forecast.one_step(y, "sba", alpha=0.1)
    assert math.isclose(f[3], 4 / 3, rel_tol=1e-9)
    assert math.isclose(fs[3], 4 / 3 * 0.95, rel_tol=1e-9)
    assert forecast.classify(y).startswith("Комковатый") or forecast.classify(y).startswith("Прерывистый")


def test_poisson_quantile():
    assert forecast.poisson_quantile(0, 0.95) == 0
    assert forecast.poisson_quantile(1.0, 0.95) == 3  # P(X≤2)=0.920, P(X≤3)=0.981
    assert forecast.poisson_quantile(2.0, 0.5) == 2


# ----------------------------- сценарии и перераспределение ----------------------
def test_scenario_no_double_count_and_uncertainty():
    r = scenarios.compute(ctx())
    lv = r["levers"]
    t = r["totals"]
    assert math.isclose(t["wc_release"], sum(x["wc_release"] for x in lv), rel_tol=1e-9)
    pools = r["pools"]
    surplus_levers = sum(x["wc_release"] for x in lv if x["name"] in ("Ускорение потребления существующих запасов", "Перераспределение"))
    assert surplus_levers <= pools["surplus"] + 1
    u = r["uncertainty"]["cash_flow"]
    assert u["p10"] <= u["p50"] <= u["p90"]
    zero = scenarios.compute(ctx(), {k: 0 for k in scenarios.defaults() if k not in ("horizon", "cover_months", "forecast_stock_conv")}, mc=False)
    assert abs(zero["totals"]["wc_release"]) < 1


def test_redistribution_respects_surplus():
    from app.vitrines.v16 import redistribution_candidates
    c = redistribution_candidates(ctx())
    assert len(c) > 0
    src = db.q("SELECT position_id, GREATEST(free_qty - fut_need_12, 0) s FROM snap WHERE m=36").set_index("position_id").s
    used = c.groupby("source_position").qty.sum()
    assert (used <= src.reindex(used.index) + 1e-6).all()
    assert (c.group_effect <= c.value + 1e-6).all()
    assert (c.group_effect == c.value - c.transport_cost).all()


# ----------------------------- качество данных и мероприятия ---------------------
def test_dq_detects_injected_issues():
    from app import dq
    res = {c["id"]: c for c in dq.run(ctx())["checks"]}
    inj = db.q("SELECT issue, COUNT(*) n FROM dq_injected GROUP BY 1").set_index("issue").n
    assert res["mand"]["count"] == inj["missing_service"]
    assert res["reserve"]["count"] == inj["reserve_exceeds"]
    assert res["units"]["count"] == inj["unit_mismatch"]
    assert res["cur"]["count"] == inj["currency"]
    assert res["dups"]["count"] == 18
    assert res["double"]["count"] == 0 and res["pk_pos"]["count"] == 0


def test_owner_and_deadline_not_invented():
    from app import actions as act
    assert act.owner_for("unknown_type") == act.TBD
    seed = act.seed_actions()
    assert seed[seed.owner == act.TBD].deadline.isna().all()
    client = TestClient(__import__("app.main", fromlist=["app"]).app)
    r = client.post("/api/actions", json={"title": "Тест без ответственного"})
    assert r.status_code == 200
    j = r.json()
    assert j["owner"] == act.TBD and j["deadline"] is None and j["status"] == "Требует назначения"


def test_insights_have_evidence_chain():
    ins = insights.compute(ctx())
    assert len(ins) >= 5
    for i in ins:
        if i["type"] == "engine_error":
            pytest.fail(i["observation"])
        assert i["observation"] and i["cause_status"] in (insights.CONFIRMED, insights.DEPENDENCY, insights.HYPOTHESIS)
        assert i["checks"] and i["action"]
    kinds = {i["type"] for i in ins}
    assert {"nez_growth", "plan_bias", "supplier_delay"} <= kinds
    assert any(i["type"] in ("open_po_postponed", "project_postponed") for i in ins)


# ----------------------------- API ---------------------------------------------
def test_all_vitrines_and_exports():
    client = TestClient(__import__("app.main", fromlist=["app"]).app)
    for v in range(1, 19):
        r = client.get(f"/api/vitrine/{v}")
        assert r.status_code == 200, (v, r.text[:300])
        j = r.json()
        assert j["is_demo"] is True and j["sections"], v
    assert client.get("/api/export/2.xlsx").status_code == 200
    assert client.get("/api/export/2.pdf").content[:4] == b"%PDF"
    assert client.post("/api/scenarios/compute", json={}).status_code == 200
    assert client.get("/api/dq").status_code == 200


def test_assistant_answers_supported_questions():
    from app import assistant
    qs = ["Почему увеличились НЭЗ за последние 6 месяцев?", "Какие общества обеспечили 80% прироста запасов?",
          "Какие службы имеют худшую динамику?", "Какие классы МТР формируют наибольшее отвлечение капитала?",
          "Какие запасы можно вовлечь без риска для производства?", "Какие закупки потенциально можно предотвратить?",
          "Как изменится структура запасов через 6 месяцев?", "Какие три решения дадут наибольший обоснованный эффект?",
          "Какие общества ухудшили оборачиваемость при росте закупок?", "Какие проблемы системно повторяются?"]
    for q in qs:
        a = assistant.answer(q, ctx())
        assert a["intent"] != "unknown", q
        assert a["summary"] and a["period"] and a["limitations"]
    assert assistant.answer("Какая погода завтра?", ctx())["intent"] == "unknown"
    a = assistant.answer("Почему увеличились НЭЗ за последние 6 месяцев?", ctx())
    assert a["period"] == ctx(window=6).period_label()


def test_generator_is_deterministic():
    from app.generator import build_dimensions, build_materials
    a = build_materials(np.random.default_rng(5))
    b = build_materials(np.random.default_rng(5))
    pd.testing.assert_frame_equal(a, b)
    d1 = build_dimensions(np.random.default_rng(5))
    d2 = build_dimensions(np.random.default_rng(5))
    pd.testing.assert_frame_equal(d1["suppliers"], d2["suppliers"])
