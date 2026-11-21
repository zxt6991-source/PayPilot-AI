import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select

from app import db
from app.config import RANKER, VERSION

from .intent import MODEL, PROMPT_VERSION

TERMINAL = {"COMPLETED", "INSUFFICIENT_DATA", "FAILED", "CANCELLED"}
TRANSITIONS = {
    "CREATED": {"PARSING"},
    "PARSING": {"CLARIFYING", "QUERYING", "RETRIEVING", "INSUFFICIENT_DATA"},
    "CLARIFYING": {"PARSING"},
    "QUERYING": {"ANALYZING", "INSUFFICIENT_DATA"},
    "ANALYZING": {"RETRIEVING"},
    "RETRIEVING": {"VALIDATING", "INSUFFICIENT_DATA"},
    "VALIDATING": {"COMPLETED"},
}
FLOW = "workflow-" + RANKER


def uid(prefix):
    return prefix + "_" + uuid4().hex


def now():
    return datetime.now(timezone.utc)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def run(conn, rid, lock=False):
    q = select(db.runs).where(db.runs.c.run_id == rid)
    return conn.execute(q.with_for_update() if lock else q).mappings().one()


def event(conn, r, kind, **payload):
    # Every caller holds the run row lock, or owns its uncommitted creation.
    seq = 1 + (conn.scalar(select(func.max(db.events.c.sequence)).where(db.events.c.run_id == r.run_id)) or 0)
    conn.execute(
        db.events.insert().values(
            run_id=r.run_id,
            sequence=seq,
            event_type=kind,
            payload=dict(task_id=r.task_id, run_id=r.run_id, **payload),
            created_at=now(),
        )
    )


def transition(conn, r, state, reason=None, **details):
    if r.state in TERMINAL or (state not in {"FAILED", "CANCELLED"} and state not in TRANSITIONS[r.state]):
        raise HTTPException(409, "任务状态已变化")
    t = now()
    conn.execute(
        db.steps.update()
        .where(db.steps.c.run_id == r.run_id, db.steps.c.ended_at.is_(None))
        .values(ended_at=t)
    )
    event(conn, r, "step.completed", state=r.state)
    values = dict(state=state, reason=reason)
    if state in TERMINAL:
        values["ended_at"] = t
    else:
        values["step_count"] = r.step_count + int(state != "CLARIFYING")
        seq = 1 + (
            conn.scalar(select(func.max(db.steps.c.sequence)).where(db.steps.c.run_id == r.run_id)) or 0
        )
        conn.execute(db.steps.insert().values(run_id=r.run_id, sequence=seq, node=state, started_at=t))
    conn.execute(db.runs.update().where(db.runs.c.run_id == r.run_id).values(**values))
    kind = {
        "COMPLETED": "report.ready",
        "FAILED": "run.failed",
        "CANCELLED": "run.cancelled",
        "CLARIFYING": "clarification.required",
        "INSUFFICIENT_DATA": "run.insufficient_data",
    }.get(state, "step.started")
    event(conn, r, kind, state=state, reason=reason, **details)


def new_run(conn, tid, rid, question, filters, parent=None):
    conn.execute(
        db.runs.insert().values(
            run_id=rid,
            task_id=tid,
            parent_run=parent,
            state="CREATED",
            question=question,
            filters=filters,
            intent="diagnosis",
            workflow_version=FLOW,
            model_id=MODEL,
            prompt_version=PROMPT_VERSION,
            step_count=0,
            started_at=now(),
        )
    )
    event(conn, run(conn, rid), "run.started", state="CREATED")


def visible(conn, tid, owner, lock=False):
    q = select(db.tasks).where(db.tasks.c.task_id == tid, db.tasks.c.owner == owner)
    row = conn.execute(q.with_for_update() if lock else q).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "找不到任务")
    return row


def create(owner, body, key):
    from sqlalchemy.dialects.postgresql import insert

    payload = body.model_dump(mode="json")
    checksum = digest(payload)
    tid, rid = uid("task"), uid("run")
    with db.writer.begin() as conn:
        stmt = insert(db.tasks).values(
            task_id=tid,
            owner=owner,
            idempotency_key=key,
            digest=checksum,
            user_query=body.question,
            filters=payload["filters"],
            dataset_version=VERSION,
            current_run=rid,
        )
        added = conn.scalar(
            stmt.on_conflict_do_nothing(index_elements=["owner", "idempotency_key"]).returning(
                db.tasks.c.task_id
            )
        )
        if not added:
            row = (
                conn.execute(
                    select(db.tasks).where(db.tasks.c.owner == owner, db.tasks.c.idempotency_key == key)
                )
                .mappings()
                .one()
            )
            if row.digest != checksum:
                raise HTTPException(409, "幂等键已用于其他问题")
            initial = (
                conn.execute(
                    select(db.runs).where(db.runs.c.task_id == row.task_id, db.runs.c.parent_run.is_(None))
                )
                .mappings()
                .one()
            )
            return row.task_id, initial.run_id, initial.state, False
        new_run(conn, tid, rid, body.question, payload["filters"])
    return tid, rid, "CREATED", True


def snapshot(conn, r):
    def rows(table, order):
        return conn.execute(select(table).where(table.c.run_id == r.run_id).order_by(order)).mappings().all()

    return {
        **r,
        "environment": "DEMO",
        "steps": rows(db.steps, db.steps.c.sequence),
        "events": rows(db.events, db.events.c.sequence),
        "evidence": rows(db.evidence, db.evidence.c.source_key),
        "tools": rows(db.calls, db.calls.c.tool_name),
        "report": conn.scalar(select(db.reports.c.report_json).where(db.reports.c.run_id == r.run_id)),
    }
