"""One bounded worker per run. Database state owns progress and cancellation."""

import asyncio
import logging
import os

import httpx
from sqlalchemy import select

from app import db
from app.schemas import Filters

from . import intent, report
from .registry import registry
from .store import TERMINAL, event, now, run, transition

MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "8"))
RUN_TIMEOUT = float(os.getenv("AGENT_RUN_TIMEOUT_SECONDS", "30"))
workers = {}
log = logging.getLogger(__name__)


def records(rid):
    with db.writer.connect() as conn:
        q = select(db.evidence).where(db.evidence.c.run_id == rid)
        return {row.source_key: row for row in conn.execute(q).mappings()}


def advance(r, state, reason=None, *, event_details=None, **updates):
    with db.writer.begin() as conn:
        locked = run(conn, r.run_id, True)
        if locked.state != r.state:
            raise InterruptedError()
        if updates:
            conn.execute(db.runs.update().where(db.runs.c.run_id == r.run_id).values(**updates))
        transition(conn, locked, state, reason, **(event_details or {}))


def usage(r, counts):
    if counts:
        with db.writer.begin() as conn:
            locked = run(conn, r.run_id, True)
            if locked.state == r.state:
                event(
                    conn,
                    r,
                    "model.usage",
                    **{
                        k: v
                        for k, v in counts.items()
                        if k in ("prompt_tokens", "completion_tokens", "total_tokens") and isinstance(v, int)
                    },
                )


async def node(r):
    scope = r.filters

    async def tool(name, **extra):
        return await registry.invoke(r.run_id, r.state, name, {**scope, **extra})

    if r.state == "CREATED":
        advance(r, "PARSING")
    elif r.state == "PARSING":
        parsed, counts = await intent.parse(r.question, scope)
        usage(r, counts)
        if parsed.intent == "refuse":
            advance(
                r, "INSUFFICIENT_DATA", "只读演示仅支持支付分析与知识查询，本次请求已拒绝。", intent="refuse"
            )
            return
        scope = Filters.model_validate(
            {**scope, **parsed.model_dump(exclude={"intent"}, exclude_none=True)}
        ).model_dump(mode="json")
        channel = intent.channel_request(r.question)
        period = intent.period_request(r.question)
        if r.step_count > 1:
            # Replay partial answers in order. Each answer overrides only its own field.
            with db.writer.connect() as conn:
                replies = conn.scalars(
                    select(db.events.c.payload)
                    .where(db.events.c.run_id == r.run_id, db.events.c.event_type == "step.started")
                    .order_by(db.events.c.sequence)
                )
                for reply in replies:
                    channel = reply.get("channel_request", channel)
                    period = reply.get("period_request", period)
        if channel:
            scope["channel"] = None if channel in ("clarify", "all") else channel
        required = () if parsed.intent == "knowledge" else ("country_code", "payment_method")
        missing = [key for key in required if not scope.get(key)]
        if channel == "clarify":
            missing.append("channel")
        if period == "clarify":
            missing.append("period")
            scope.pop("period", None)
        elif period and period != "clarify":
            scope["period"] = period
        state = "CLARIFYING" if missing else "RETRIEVING" if parsed.intent == "knowledge" else "QUERYING"
        labels = {
            "country_code": "地区",
            "payment_method": "支付方式",
            "channel": "要查询的单个终端（Android、Web 或 iOS）",
            "period": "查询周期（最近 24 小时、7 天或 30 天）",
        }
        advance(
            r,
            state,
            "请补充" + "、".join(labels[key] for key in missing) if state == "CLARIFYING" else None,
            event_details={"missing_fields": missing} if state == "CLARIFYING" else None,
            filters=scope,
            intent=parsed.intent,
        )
    elif r.state == "QUERYING":
        current = await tool("get_payment_metrics")
        if current["valid_attempts"] < 30:
            advance(
                r, "INSUFFICIENT_DATA", f"有效支付尝试 {current['valid_attempts']} 笔，低于 30 笔的分析门槛。"
            )
        else:
            await tool("compare_payment_periods")
            advance(r, "ANALYZING")
    elif r.state == "ANALYZING":
        groups = await tool("get_failure_breakdown")
        focus = min((x for x in groups["rows"] if x["psr"] is not None), key=lambda x: (x["psr"], x["value"]))
        await tool("get_error_distribution", channel=focus["value"])
        if r.intent == "release":
            await tool("get_release_changes")
        advance(r, "RETRIEVING")
    elif r.state == "RETRIEVING":
        query = r.question
        extra = {}
        if r.intent != "knowledge":
            errors = records(r.run_id)["get_error_distribution"]["payload"]
            extra["channel"] = errors["filters"]["channel"]
            query = " ".join(x["error_code"] for x in errors["rows"][:2])
            if r.intent == "release":
                query += " 版本发布"
        result = await tool("search_payment_kb", query=query or "错误分布", **extra)
        if r.intent == "knowledge" and not result["hits"]:
            advance(r, "INSUFFICIENT_DATA", "知识库没有匹配此问题的来源。")
        else:
            advance(r, "VALIDATING")
    elif r.state == "VALIDATING":
        items = records(r.run_id)
        hits = items["search_payment_kb"]["payload"]["hits"]
        errors = items.get("get_error_distribution", {}).get("payload", {}).get("rows", [])
        degraded = False
        try:
            draft, counts = await intent.draft(
                r.intent, any(x["error_code"] == "redirect_timeout" for x in errors), hits
            )
            usage(r, counts)
        except (ValueError, httpx.HTTPError):
            draft = intent.Draft(action="compare")
            degraded = True
        result = report.build(r, items, draft.action)
        if degraded:
            result["uncertainties"].append("模型建议暂不可用，本报告采用已保存的数据与知识证据。")
        report.validate(result, r, items)
        with db.writer.begin() as conn:
            locked = run(conn, r.run_id, True)
            if locked.state != r.state:
                raise InterruptedError()
            conn.execute(
                db.reports.insert().values(
                    report_id=result["report_id"],
                    run_id=r.run_id,
                    schema_version="report-v1",
                    report_json=result,
                    created_at=now(),
                )
            )
            transition(conn, locked, "COMPLETED", report_id=result["report_id"])


async def execute(rid):
    try:
        async with asyncio.timeout(RUN_TIMEOUT):
            while True:
                with db.writer.connect() as conn:
                    r = run(conn, rid)
                if r.state in TERMINAL | {"CLARIFYING"}:
                    return
                if r.step_count > MAX_STEPS:
                    raise RuntimeError("STEP_BUDGET")
                await node(r)
                await asyncio.sleep(0)
    except InterruptedError:
        return
    except Exception as exc:
        code = (
            "TIMEOUT"
            if isinstance(exc, TimeoutError)
            else "STEP_BUDGET"
            if str(exc) == "STEP_BUDGET"
            else "NODE_FAILED"
        )
        log.warning("run %s failed at %s (%s)", rid, r.state, type(exc).__name__)
        with db.writer.begin() as conn:
            locked = run(conn, rid, True)
            if locked.state not in TERMINAL:
                transition(conn, locked, "FAILED", code)


def schedule(rid):
    if rid not in workers or workers[rid].done():
        task = asyncio.create_task(execute(rid))
        workers[rid] = task

        def cleanup(done):
            if workers.get(rid) is done:
                workers.pop(rid, None)

        task.add_done_callback(cleanup)


def recover():
    with db.writer.connect() as conn:
        pending = conn.scalars(
            select(db.runs.c.run_id).where(db.runs.c.state.not_in(TERMINAL | {"CLARIFYING"}))
        ).all()
    for rid in pending:
        schedule(rid)
