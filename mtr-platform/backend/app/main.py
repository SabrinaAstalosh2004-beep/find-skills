"""FastAPI-приложение аналитической платформы управления запасами МТР."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import time
import traceback

import pandas as pd
from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import actions as act
from . import adapters, assistant, db, dq, engine, export, insights, metrics, scenarios
from . import settings as cfg
from .filters import DIMENSIONS, FILTER_COLUMNS, Ctx, ctx_from_request
from .vitrines import BY_ID, GROUPS, registry
from .vitrines.common import clean, col, table
from .vitrines.directions import hierarchy

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(_app):
    db.con()
    yield


app = FastAPI(title="Платформа управления запасами МТР", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
FRONT = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "dist"
VIEWS_FILE = cfg.DATA_DIR / "views.json"


@app.exception_handler(Exception)
async def _err(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": f"Ошибка расчёта: {exc}"})


def ctx_dep(request: Request) -> Ctx:
    return ctx_from_request(request)


def _opts(request: Request) -> dict:
    return {k[2:]: v for k, v in request.query_params.items() if k.startswith("o_")}


def _jsonable(o):
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    return clean(o)


# ---------------------------------------------------------------------------------------
@app.get("/api/meta")
def meta(ctx: Ctx = Depends(ctx_dep)):
    m = db.meta()
    acc = ctx.access_clause()
    q = lambda sql: db.q(sql).to_dict("records")
    dirs = db.q("SELECT direction_id, direction_name, parent_id, direction_group FROM directions").to_dict("records")
    return _jsonable(dict(
        meta=m, roles=[dict(id=k, label=v["label"]) for k, v in cfg.ROLES.items()], role=ctx.role,
        months=[dict(m=i, label=db.month_label(i)) for i in range(1, m["last_closed_m"] + 1)],
        vitrines=registry(), groups=GROUPS,
        options=dict(
            company=q(f"SELECT DISTINCT company_id AS value, company_name AS label, ownership_type FROM v_pos WHERE {acc} ORDER BY 1"),
            segment=q(f"SELECT DISTINCT segment AS value, segment AS label FROM v_pos WHERE {acc} ORDER BY 1"),
            ownership=[dict(value="ДО", label="ДО"), dict(value="СП", label="СП")],
            warehouse=q(f"SELECT DISTINCT warehouse_id AS value, warehouse_name || ' (' || company_id || ')' AS label FROM v_pos WHERE {acc} ORDER BY 2"),
            direction=[dict(value=d["direction_id"], label=("— " if d["parent_id"] else "") + d["direction_name"], parent=d["parent_id"]) for d in dirs],
            dgroup=q("SELECT DISTINCT direction_group AS value, direction_group AS label FROM directions ORDER BY 1"),
            program=q("SELECT DISTINCT COALESCE(program,'Вне программ') AS value, COALESCE(program,'Вне программ') AS label FROM v_pos ORDER BY 1"),
            service=q("SELECT service_id AS value, service_name AS label FROM services ORDER BY 1"),
            mclass=q("SELECT DISTINCT mclass AS value, mclass AS label FROM materials ORDER BY 1"),
            criticality=q("SELECT DISTINCT criticality AS value, criticality AS label FROM materials ORDER BY 1"),
            demand_type=[dict(value=v, label=v) for v in ["Регулярный", "Нерегулярный", "Проектный", "Без потребности"]],
            policy=q("SELECT DISTINCT replenishment_policy AS value, replenishment_policy AS label FROM positions ORDER BY 1"),
            project=q(f"SELECT DISTINCT project_id AS value, project_name || ' (' || company_id || ')' AS label FROM v_pos WHERE project_id IS NOT NULL AND {acc} ORDER BY 2"),
            supplier=q("SELECT supplier_id AS value, supplier_name AS label FROM suppliers ORDER BY 1"),
            proc_model=q("SELECT DISTINCT proc_model AS value, proc_model AS label FROM materials ORDER BY 1"),
        ),
        dimensions=[dict(key=k, label=v[2]) for k, v in DIMENSIONS.items()],
        filter_keys=list(FILTER_COLUMNS), settings=cfg.get(),
        metrics=[dict(id=x.id, label=x.label, unit=x.unit, sliceable=x.sliceable) for x in metrics.M],
    ))


@app.get("/api/vitrine/{vid}")
def vitrine(vid: int, request: Request, ctx: Ctx = Depends(ctx_dep)):
    if vid not in BY_ID or BY_ID[vid][3] is None:
        raise HTTPException(404, "Витрина рассчитывается специализированным API")
    t = time.time()
    _, title, group, fn, desc = BY_ID[vid]
    p = fn(ctx, _opts(request))
    ins = insights.for_vitrine(ctx, vid)
    out = dict(id=vid, title=title, group=group, description=desc, ctx=ctx.to_dict(), is_demo=db.meta()["is_demo"],
               data_meta=db.meta(), insights=ins[:12], elapsed=round(time.time() - t, 2), **p)
    return _jsonable(out)


@app.get("/api/hierarchy")
def api_hierarchy(request: Request, level: str, path: str = "", ctx: Ctx = Depends(ctx_dep)):
    pp = [tuple(x.split(":", 1)) for x in path.split("|") if ":" in x]
    for d, _ in pp:
        if d not in FILTER_COLUMNS:
            raise HTTPException(400, "Недопустимый разрез")
    if level not in DIMENSIONS:
        raise HTTPException(400, "Недопустимый уровень")
    return _jsonable(hierarchy(ctx, pp, level))


@app.get("/api/drill")
def drill(request: Request, ctx: Ctx = Depends(ctx_dep), dim: str | None = None, value: str | None = None, limit: int = 500):
    c = ctx
    if dim and value:
        if dim not in FILTER_COLUMNS:
            raise HTTPException(400, "Недопустимый разрез")
        c = ctx.with_filters(**{dim: [value]})
    d = engine.positions_at(c, limit=limit)
    cols = [col("company_name", "Общество"), col("warehouse_name", "Склад"), col("direction_name", "Направление"), col("service_name", "Служба"),
            col("mclass", "Класс"), col("nsi_code", "Код НСИ"), col("material_name", "Номенклатура"), col("criticality", "Критичность"),
            col("replenishment_policy", "Политика"), col("project_name", "Проект"), col("qty", "Кол-во", "num"), col("unit", "Ед."),
            col("value", "Стоимость", "money"), col("free_value", "Свободно", "money"), col("reserved_value", "Резерв", "money"),
            col("nez_value", "НЭЗ", "money"), col("days_no_issue", "Дней без потребл.", "int"), col("age_days", "Возраст, дн.", "int"),
            col("last_receipt_date", "Посл. поступление", "date"), col("last_issue_date", "Посл. отпуск", "date")]
    return _jsonable(dict(ctx=c.to_dict(), table=table(d, cols, row_key="position_id", limit=limit, total=True)))


@app.get("/api/position/{pid}")
def position(pid: str, ctx: Ctx = Depends(ctx_dep)):
    info = db.q(f"SELECT * FROM v_pos WHERE position_id = ? AND {ctx.access_clause()}", [pid])
    if info.empty:
        raise HTTPException(404, "Позиция не найдена или нет доступа")
    snap = db.q("SELECT m, qty, value, free_value, reserved_value, nez_value, days_no_issue FROM snap WHERE position_id = ? ORDER BY m", [pid])
    snap["label"] = snap.m.map(db.month_label)
    mov = db.q("SELECT date, mtype, subtype, qty, value, po_id FROM movements WHERE position_id = ? AND mtype <> 'Переоценка' ORDER BY date DESC LIMIT 200", [pid])
    po = db.q("SELECT po_id, order_date, qty, value, planned_delivery, actual_delivery, need_date, proc_model, supplier_id, currency FROM purchase_orders WHERE position_id = ? ORDER BY order_date DESC LIMIT 50", [pid])
    dem = db.q(f"SELECT m, plan_init_qty, plan_qty FROM demand WHERE position_id = ? AND m BETWEEN {ctx.m2 - 11} AND {ctx.m2 + 12} ORDER BY m", [pid])
    dem["label"] = dem.m.map(db.month_label)
    return _jsonable(dict(info=info.iloc[0].to_dict(), snapshots=snap.to_dict("records"), movements=mov.to_dict("records"),
                          purchase_orders=po.to_dict("records"), demand=dem.to_dict("records")))


@app.get("/api/insights")
def api_insights(ctx: Ctx = Depends(ctx_dep)):
    return _jsonable(dict(ctx=ctx.to_dict(), insights=insights.compute(ctx)))


@app.get("/api/slice")
def api_slice(request: Request, metric: str = "stock_end", dim1: str = "company", dim2: str | None = None, chart: str = "bar",
              sort: str = "desc", top: int = 20, ctx: Ctx = Depends(ctx_dep)):
    if metric not in metrics.REGISTRY:
        raise HTTPException(400, "Неизвестный показатель")
    m = metrics.REGISTRY[metric]
    if dim1 == "time":
        dims = [dim2] if dim2 else []
        if metric == "turnover_days":
            s = engine.turnover_ltm(ctx, dims)
            val = "turnover_days"
        else:
            s = engine.series(ctx, dims, ctx.m1, ctx.m2)
            s = engine.to_grain(s, ctx.grain, keys=dims)
            mp = {"stock_end": "stock", "nez_end": "nez", "free_end": "free", "reserved_end": "reserved", "noissue_end": "noissue",
                  "consumption": "consumption", "receipts": "receipts", "reval": "reval"}
            if metric == "nez_share":
                s["nez_share"] = s.nez / s.stock * 100
                val = "nez_share"
            elif metric in mp:
                val = mp[metric]
            else:
                raise HTTPException(400, "Показатель недоступен во временном разрезе; выберите: запасы, НЭЗ, доля НЭЗ, свободный, резерв, без потребления, потребление, поступление, переоценка, оборачиваемость")
        xs = list(dict.fromkeys(s.label.tolist()))
        if dims:
            d2 = dims[0]
            tops = s.groupby(f"{d2}_label")[val].sum().sort_values(ascending=False).head(top).index
            series = [dict(name=str(g), data=[clean(s[(s[f"{d2}_label"] == g) & (s.label == x)][val].sum()) for x in xs]) for g in tops]
        else:
            series = [dict(name=m.label, data=[clean(v) for v in s[val]])]
        spec = dict(kind="line" if chart in ("line", "area") else "bar", x=xs, categories=xs, series=series,
                    unit={"rub": "rub", "pct": "pct", "days": "days"}.get(m.unit, "num"), stacked=chart == "stacked", horizontal=False)
        tb = pd.DataFrame({"Период": xs, **{sr["name"]: sr["data"] for sr in series}})
        return _jsonable(dict(chart=spec, table=table(tb, [col("Период", "Период")] + [col(sr["name"], sr["name"], "money" if m.unit == "rub" else "num") for sr in series]),
                              metric=metrics.asdict(m) if hasattr(metrics, "asdict") else None, ctx=ctx.to_dict()))
    dims = [dim1] + ([dim2] if dim2 else [])
    for d in dims:
        if d not in DIMENSIONS:
            raise HTTPException(400, "Неизвестный разрез")
    a = engine.aggregate(ctx, dims)
    a = a[a[metric].notna()]
    a = a.sort_values(metric, ascending=(sort == "asc"))
    unit = {"rub": "rub", "pct": "pct", "days": "days"}.get(m.unit, "num")
    if dim2:
        top1 = a.groupby(f"{dim1}_label")[metric].sum().sort_values(ascending=(sort == "asc")).head(top).index.tolist()
        top2 = a.groupby(f"{dim2}_label")[metric].sum().sort_values(ascending=False).head(12).index.tolist()
        if chart == "heatmap":
            spec = dict(kind="heatmap", x=top2, y=top1, values=[[clean(a[(a[f"{dim1}_label"] == y) & (a[f"{dim2}_label"] == x)][metric].sum()) for x in top2] for y in top1], unit=unit)
        else:
            spec = dict(kind="bar", categories=top1, series=[dict(name=str(g), data=[clean(a[(a[f"{dim1}_label"] == c_) & (a[f"{dim2}_label"] == g)][metric].sum()) for c_ in top1])
                                                            for g in top2], unit=unit, stacked=chart != "grouped", horizontal=chart == "hbar")
    else:
        t = a.head(top)
        if chart == "pareto":
            spec = dict(kind="pareto", **engine.pareto(a, metric, f"{dim1}_label"), unit=unit)
        elif chart == "treemap":
            spec = dict(kind="treemap", nodes=[dict(name=str(r[f"{dim1}_label"]), value=clean(r[metric])) for _, r in t.iterrows() if (r[metric] or 0) > 0], unit=unit)
        else:
            spec = dict(kind="bar", categories=t[f"{dim1}_label"].astype(str).tolist(), series=[dict(name=m.label, data=[clean(v) for v in t[metric]])],
                        unit=unit, horizontal=chart == "hbar", stacked=False)
    cols = [col(f"{d}_label", DIMENSIONS[d][2]) for d in dims] + [col(metric, m.label, {"rub": "money", "pct": "pct", "days": "days"}.get(m.unit, "num"))]
    extra = [x for x in ["stock_end", "nez_end", "consumption"] if x != metric]
    cols += [col(x, metrics.REGISTRY[x].label, "money") for x in extra]
    return _jsonable(dict(chart=spec, table=table(a.head(500), cols, drill={"dim": dim1, "key": dim1}), ctx=ctx.to_dict(),
                          metric=dict(label=m.label, formula=m.formula, limitations=m.limitations)))


# ------------------------------- настройки и каталог ----------------------------------
@app.get("/api/settings")
def get_settings():
    return cfg.get()


@app.put("/api/settings")
def put_settings(patch: dict = Body(...), request: Request = None):
    role = request.headers.get("x-role", "board")
    if role not in ("board", "ceo", "mto"):
        raise HTTPException(403, "Изменение методики доступно ролям группового уровня")
    s = cfg.update(patch)
    db.build_views()
    insights._cache.clear()
    return s


@app.post("/api/settings/reset")
def reset_settings():
    s = cfg.reset()
    db.build_views()
    insights._cache.clear()
    return s


@app.get("/api/metrics")
def api_metrics():
    return dict(metrics=metrics.catalog(), settings=cfg.get())


# ------------------------------- мероприятия ------------------------------------------
@app.get("/api/actions")
def api_actions(ctx: Ctx = Depends(ctx_dep)):
    w = ctx.with_filters(**{k: None for k in ctx.filters if k not in ("company", "segment", "ownership")}).where("c")
    d = db.q(f"""SELECT a.*, c.company_name, c.ownership_type FROM actions a LEFT JOIN companies c USING (company_id)
                WHERE a.company_id IS NULL OR ({w})""", cache=False)
    today = dt.date(2026, 11, 1) if db.meta()["is_demo"] else dt.date.today()
    recs = d.to_dict("records")
    for r in recs:
        r["effective_status"] = act.effective_status(r, today)
        r["owner_display"] = r["owner"] if r.get("owner") and r["owner"] != act.TBD else act.TBD
        r["deadline_display"] = r["deadline"] or act.TBD
    df = pd.DataFrame(recs)
    stats = {}
    if len(df):
        stats = dict(total=len(df), overdue=int((df.effective_status == "Просрочено").sum()), tbd=int((df.effective_status == "Требует назначения").sum()),
                     in_work=int((df.effective_status == "В работе").sum()), done=int(df.effective_status.str.startswith("Выполнено").sum()),
                     forecast=float(df.forecast_effect.fillna(0).sum()), actual=float(df.actual_effect.fillna(0).sum()),
                     repeated=int((df.repeat_count > 1).sum()))
    return _jsonable(dict(actions=recs, stats=stats, statuses=act.STATUSES, authority=act.AUTHORITY))


@app.post("/api/actions")
def create_action(body: dict = Body(...), ctx: Ctx = Depends(ctx_dep)):
    now = dt.datetime.now().isoformat(timespec="seconds")
    src = body.get("insight_id")
    rec = dict(action_id=None, issue_key=None, created_at=now, source="Ручной ввод", company_id=None, direction_id=None, service_id=None,
               mclass=None, material_id=None, title="", deviation="", cause="", cause_status="Гипотеза", evidence="", measure="",
               owner=act.TBD, deadline=None, forecast_effect=None, actual_effect=None, status="Новое", acceptance="", priority=2,
               value_at_risk=0.0, criticality="Средняя", repeat_count=1, updated_at=now, comment=None)
    if src:
        ins = next((i for i in insights.compute(ctx) if i["id"] == src), None)
        if not ins:
            raise HTTPException(404, "Находка не найдена в текущем срезе")
        ev = "; ".join(f"{e['label']}: {e['value']:,.0f}".replace(",", " ") for e in ins["evidence"] if e["value"] is not None)
        rec.update(issue_key=ins["id"], source="Аналитический механизм", company_id=ins.get("company_id"), direction_id=ins.get("direction_id"),
                   service_id=ins.get("service_id"), mclass=ins.get("mclass"), title=ins["title"], deviation=ins["observation"],
                   cause=ins["cause"], cause_status=ins["cause_status"], evidence=ev, measure=ins["action"], owner=ins["owner"],
                   forecast_effect=ins.get("effect"), value_at_risk=ins["value_at_risk"],
                   criticality={3: "Высокая", 2: "Средняя", 1: "Низкая"}[ins["severity"]], priority=4 - ins["severity"],
                   acceptance="Отклонение устранено по данным витрины-источника; эффект подтверждён финансовой службой")
    for k in ("title", "measure", "owner", "deadline", "company_id", "acceptance", "comment", "source", "issue_key", "status",
              "forecast_effect", "value_at_risk", "deviation", "cause", "evidence", "mclass"):
        if k in body and body[k] not in (None, ""):
            rec[k] = body[k]
    with db._lock:
        c = db.con()
        prev = c.execute("SELECT COUNT(*) FROM actions WHERE issue_key = ?", [rec["issue_key"]]).fetchone()[0] if rec["issue_key"] else 0
        rec["repeat_count"] = int(prev) + 1
        n = c.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
        rec["action_id"] = f"A{n + 1:04d}"
        if rec["owner"] in (None, "", act.TBD):
            rec["owner"] = act.TBD
            if rec["status"] == "Новое":
                rec["status"] = "Требует назначения"
        cols = db.ACTION_COLUMNS
        c.execute(f"INSERT INTO actions ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [rec.get(k) for k in cols])
    db.persist_actions()
    return _jsonable(rec)


@app.patch("/api/actions/{aid}")
def update_action(aid: str, body: dict = Body(...)):
    allowed = {"owner", "deadline", "status", "actual_effect", "forecast_effect", "comment", "measure", "acceptance", "priority"}
    upd = {k: v for k, v in body.items() if k in allowed}
    if not upd:
        raise HTTPException(400, "Нет допустимых полей")
    if upd.get("status") == "Выполнено, эффект подтверждён" and body.get("actual_effect") in (None, ""):
        cur = db.q("SELECT actual_effect FROM actions WHERE action_id = ?", [aid], cache=False)
        if cur.empty or pd.isna(cur.actual_effect.iloc[0]):
            raise HTTPException(400, "Для статуса «эффект подтверждён» укажите фактический эффект")
    upd["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    with db._lock:
        db.con().execute(f"UPDATE actions SET {', '.join(f'{k} = ?' for k in upd)} WHERE action_id = ?", list(upd.values()) + [aid])
    db.persist_actions()
    return {"ok": True}


@app.post("/api/redistribution/decision")
def redist_decision(body: dict = Body(...), ctx: Ctx = Depends(ctx_dep)):
    key, decision, row = body.get("key"), body.get("decision"), body.get("row") or {}
    if decision not in ("Принято в работу", "Отклонено", "На технической проверке"):
        raise HTTPException(400, "Недопустимое решение")
    status = {"Принято в работу": "Требует назначения", "Отклонено": "Отклонено", "На технической проверке": "Требует назначения"}[decision]
    rec = create_action(dict(title=f"Перераспределение: {row.get('material_name')} {row.get('source_company')} → {row.get('target_company')}",
                             measure=f"{decision}. Перемещение {row.get('qty')} {row.get('unit') or ''}; согласование: {row.get('approval')}",
                             owner=act.owner_for("redistribution"), source="Витрина 16: перераспределение", issue_key=key,
                             forecast_effect=row.get("group_effect"), value_at_risk=row.get("value"), status=status,
                             company_id=row.get("target_company_id"), comment=decision,
                             acceptance="Перемещение оформлено; закупка у получателя не размещена/отменена"), ctx)
    with db._lock:
        db.con().execute("UPDATE actions SET status = ? WHERE action_id = ?", [decision if decision != "Принято в работу" else "В работе", rec["action_id"]])
    db.persist_actions()
    return rec


# ------------------------------- прочее -----------------------------------------------
@app.get("/api/dq")
def api_dq(ctx: Ctx = Depends(ctx_dep)):
    return _jsonable(dq.run(ctx))


@app.get("/api/scenarios/defaults")
def sc_defaults():
    return dict(params=scenarios.params_meta())


@app.post("/api/scenarios/compute")
def sc_compute(body: dict = Body(default={}), ctx: Ctx = Depends(ctx_dep)):
    return _jsonable(scenarios.compute(ctx, body.get("params") or {}))


@app.post("/api/assistant")
def api_assistant(body: dict = Body(...), ctx: Ctx = Depends(ctx_dep)):
    q = (body.get("question") or "").strip()
    if not q:
        raise HTTPException(400, "Пустой вопрос")
    return _jsonable(dict(question=q, **assistant.answer(q, ctx)))


@app.get("/api/export/{vid}.{fmt}")
def api_export(vid: int, fmt: str, request: Request, ctx: Ctx = Depends(ctx_dep)):
    if vid not in BY_ID or BY_ID[vid][3] is None:
        raise HTTPException(400, "Экспорт этой витрины выполняется из её интерфейса")
    p = vitrine(vid, request, ctx)
    name = f"vitrina_{vid:02d}_{ctx.asof}"
    if fmt == "xlsx":
        return Response(export.to_xlsx(p), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    if fmt == "pdf":
        return Response(export.to_pdf(p), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
    raise HTTPException(400, "Формат: xlsx или pdf")


@app.get("/api/views")
def get_views():
    return json.loads(VIEWS_FILE.read_text("utf-8")) if VIEWS_FILE.exists() else []


@app.post("/api/views")
def save_view(body: dict = Body(...)):
    v = get_views()
    body["id"] = body.get("id") or f"V{int(time.time() * 1000)}"
    body["saved_at"] = dt.datetime.now().isoformat(timespec="seconds")
    v = [x for x in v if x["id"] != body["id"]] + [body]
    cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    VIEWS_FILE.write_text(json.dumps(v, ensure_ascii=False, indent=2), "utf-8")
    return v


@app.delete("/api/views/{vid}")
def del_view(vid: str):
    v = [x for x in get_views() if x["id"] != vid]
    VIEWS_FILE.write_text(json.dumps(v, ensure_ascii=False, indent=2), "utf-8")
    return v


@app.get("/api/sources")
def api_sources():
    return _jsonable(dict(**adapters.list_sources(), schema=adapters.canonical_schema(), status=dq.sources_status()))


@app.post("/api/sources/upload")
async def api_upload(table_name: str = Form(...), file: UploadFile = File(...)):
    content = await file.read()
    try:
        df = adapters.read_upload(table_name, file.filename, content)
    except Exception as e:
        raise HTTPException(400, str(e))
    errs = adapters.validate(table_name, df)
    if errs:
        raise HTTPException(400, "; ".join(errs))
    adapters.stage(table_name, df)
    return dict(ok=True, rows=len(df), table=table_name)


@app.post("/api/sources/config/{adapter_id}")
def api_src_config(adapter_id: str, body: dict = Body(...)):
    return adapters.save_config(adapter_id, body)


@app.post("/api/sources/sql")
def api_src_sql(body: dict = Body(...)):
    return dict(errors=adapters.load_sql(body.get("connection", ""), body.get("queries", {})))


@app.post("/api/sources/activate")
def api_activate():
    r = adapters.activate()
    insights._cache.clear()
    return r


@app.post("/api/sources/reset-demo")
def api_reset_demo():
    r = adapters.reset_demo()
    insights._cache.clear()
    return r


@app.get("/api/health")
def health():
    return dict(ok=True, **db.meta())


if FRONT.exists():
    app.mount("/assets", StaticFiles(directory=FRONT / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = FRONT / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(FRONT / "index.html")
