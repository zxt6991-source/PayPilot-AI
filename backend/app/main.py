import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app import db, knowledge
from app.agent import intent, runtime
from app.agent.store import TERMINAL, create, new_run, run, snapshot, transition, uid, visible
from app.config import ANCHOR, ROOT
from app.schemas import CreateTask, Dimension, Feedback, Message, Scope, Strict
from app.services import metric_service as metrics


@asynccontextmanager
async def lifespan(app):
    intent.check_model_config()
    runtime.recover()
    yield
    pending = list(runtime.workers.values())
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


app = FastAPI(title="PayPilot AI · DEMO", version="0.4.0", lifespan=lifespan)


def principal(authorization: Annotated[str | None, Header()] = None):
    # Fixed local analyst. Additional identities come from server-side configuration only.
    identities = json.loads(os.getenv("DEMO_IDENTITIES", "{}"))
    if not authorization:
        return "demo-analyst"
    token = authorization.removeprefix("Bearer ")
    if token == authorization or token not in identities:
        raise HTTPException(401, "演示身份无效")
    ident = identities[token]
    if ident["role"] not in ("ANALYST", "ADMIN"):
        raise HTTPException(403, "缺少只读分析权限")
    return ident["owner"]


Owner = Annotated[str, Depends(principal)]
MetricScope = Annotated[Scope, Query()]


@app.get("/api/health")
def health():
    try:
        for engine in (db.reader, db.writer):
            with engine.connect() as conn:
                conn.execute(text("select 1"))
        return {
            "environment": "DEMO",
            "application": "up",
            "database": "up",
            "as_of_utc": ANCHOR,
            "llm_provider": intent.PROVIDER,
            "model_id": intent.MODEL,
        }
    except SQLAlchemyError:
        return JSONResponse({"environment": "DEMO", "application": "up", "database": "down"}, 503)


@app.get("/api/metrics")
def current(scope: MetricScope, owner: Owner):
    return metrics.metrics(scope)


@app.get("/api/metrics/compare")
def comparison(scope: MetricScope, owner: Owner):
    return metrics.compare(scope)


class BreakdownScope(Scope):
    dimension: Dimension = "channel"


@app.get("/api/metrics/breakdown")
def breakdown(scope: Annotated[BreakdownScope, Query()], owner: Owner):
    return metrics.breakdown(Scope.model_validate(scope.model_dump(exclude={"dimension"})), scope.dimension)


@app.get("/api/metrics/errors")
def errors(scope: MetricScope, owner: Owner):
    return metrics.errors(scope)


@app.get("/api/metrics/trend")
def trend(scope: MetricScope, owner: Owner):
    return metrics.trend(scope)


@app.get("/api/knowledge")
def kb(owner: Owner, q: str = Query(default="", max_length=1500)):
    return knowledge.search(q, {})["hits"] if q else knowledge.library()


@app.get("/api/evaluation")
def evaluation(owner: Owner):
    result = []
    for split in ("dev", "holdout"):
        path = ROOT / "evaluation/results" / (split + "-summary.json")
        if path.exists():
            result.append(json.loads(path.read_text()))
    return {"environment": "DEMO", "results": result}


def accepted(tid, rid, state):
    url = "/api/diagnoses/" + tid
    return dict(
        task_id=tid,
        run_id=rid,
        state=state,
        events_url=url + "/events?run_id=" + rid,
        status_url=url,
        environment="DEMO",
    )


@app.post("/api/diagnoses", status_code=202)
async def start(
    body: CreateTask, owner: Owner, idempotency_key: Annotated[str | None, Header(max_length=120)] = None
):
    tid, rid, state, added = create(owner, body, idempotency_key)
    if added:
        runtime.schedule(rid)
    return accepted(tid, rid, state)


def owned_run(conn, tid, owner, rid=None):
    task = visible(conn, tid, owner)
    row = (
        conn.execute(
            select(db.runs).where(db.runs.c.task_id == tid, db.runs.c.run_id == (rid or task.current_run))
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, "找不到运行记录")
    return row


@app.get("/api/diagnoses/{tid}")
def get(tid: str, owner: Owner, run_id: str | None = None):
    with db.writer.begin() as conn:
        row = owned_run(conn, tid, owner, run_id)
        return snapshot(conn, run(conn, row.run_id, True))


@app.get("/api/reports/{report_id}")
def report(report_id: str, owner: Owner):
    with db.writer.connect() as conn:
        row = (
            conn.execute(
                select(db.runs)
                .join(db.reports)
                .join(db.tasks, db.tasks.c.task_id == db.runs.c.task_id)
                .where(db.reports.c.report_id == report_id, db.tasks.c.owner == owner)
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            raise HTTPException(404, "找不到报告")
        return snapshot(conn, row)


@app.get("/api/diagnoses/{tid}/events")
async def stream(
    request: Request,
    tid: str,
    owner: Owner,
    run_id: str | None = None,
    after: str = "0",
    last_event_id: Annotated[str | None, Header()] = None,
):
    with db.writer.connect() as conn:
        rid = owned_run(conn, tid, owner, run_id).run_id
    cursor = last_event_id or after
    if ":" in cursor:
        prefix, cursor = cursor.split(":", 1)
        if prefix != rid:
            raise HTTPException(409, "事件属于不同运行")
    if not cursor.isascii() or not cursor.isdigit() or len(cursor) > 9:
        raise HTTPException(400, "非法事件序号")

    async def feed():
        seq = int(cursor)
        while not await request.is_disconnected():
            with db.writer.connect() as conn:
                state = run(conn, rid).state
                rows = (
                    conn.execute(
                        select(db.events)
                        .where(db.events.c.run_id == rid, db.events.c.sequence > seq)
                        .order_by(db.events.c.sequence)
                    )
                    .mappings()
                    .all()
                )
            for row in rows:
                seq = row.sequence
                yield f"id: {rid}:{seq}\nevent: {row.event_type}\ndata: {json.dumps(row.payload, ensure_ascii=False)}\n\n"
            if state in TERMINAL | {"CLARIFYING"}:
                return
            yield ": heartbeat\n\n"
            await asyncio.sleep(0.3)

    return StreamingResponse(
        feed(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class RunTarget(Strict):
    run_id: str


@app.post("/api/diagnoses/{tid}/cancel")
async def cancel(tid: str, body: RunTarget, owner: Owner):
    with db.writer.begin() as conn:
        t = visible(conn, tid, owner, True)
        if body.run_id != t.current_run:
            raise HTTPException(409, "运行已变化")
        r = run(conn, t.current_run, True)
        if r.state == "CANCELLED":
            return accepted(tid, r.run_id, r.state)
        transition(conn, r, "CANCELLED", "用户已停止执行")
    return accepted(tid, r.run_id, "CANCELLED")


@app.post("/api/diagnoses/{tid}/messages", status_code=202)
async def message(tid: str, body: Message, owner: Owner):
    with db.writer.begin() as conn:
        t = visible(conn, tid, owner, True)
        if body.run_id != t.current_run:
            raise HTTPException(409, "已存在更新的运行，请刷新任务")
        r = run(conn, t.current_run, True)
        scope = {**r.filters, **body.filters.model_dump(mode="json", exclude_unset=True)}
        if r.state == "CLARIFYING":
            rid = r.run_id
            question = (r.question + "\n" + body.question)[-1500:]
            conn.execute(
                db.runs.update().where(db.runs.c.run_id == rid).values(filters=scope, question=question)
            )
            transition(conn, r, "PARSING")
            state = "PARSING"
        elif r.state in TERMINAL:
            rid = uid("run")
            new_run(conn, tid, rid, body.question, scope, r.run_id)
            conn.execute(db.tasks.update().where(db.tasks.c.task_id == tid).values(current_run=rid))
            state = "CREATED"
        else:
            raise HTTPException(409, "当前运行尚未结束")
    runtime.schedule(rid)
    return accepted(tid, rid, state)


@app.post("/api/diagnoses/{tid}/feedback", status_code=201)
def send_feedback(tid: str, body: Feedback, owner: Owner):
    with db.writer.begin() as conn:
        r = owned_run(conn, tid, owner, body.run_id)
        report_id = conn.scalar(select(db.reports.c.report_id).where(db.reports.c.run_id == r.run_id))
        if body.report_id != report_id:
            raise HTTPException(409, "报告与运行不匹配")
        fid = uid("feedback")
        conn.execute(db.feedback.insert().values(feedback_id=fid, **body.model_dump()))
        return {"feedback_id": fid, "environment": "DEMO"}
