import asyncio
import os
import time
from dataclasses import dataclass

from pydantic import Field
from sqlalchemy import select

from app import db, knowledge
from app.config import VERSION
from app.schemas import Dimension, Filters, Scope
from app.services import metric_service as metrics

from .store import digest, event, run, uid

TIMEOUT = float(os.getenv("AGENT_TOOL_TIMEOUT_SECONDS", "10"))


class BreakdownArgs(Scope):
    dimension: Dimension = "channel"


class SearchArgs(Filters):
    query: str = Field(min_length=1, max_length=1800)


@dataclass(frozen=True)
class Tool:
    schema: type[Filters]
    execute: object
    roles: tuple = ("ANALYST", "ADMIN")


class Registry:
    def __init__(self):
        self.tools = {}

    def register(self, name, tool):
        if name in self.tools:
            raise ValueError("duplicate tool")
        self.tools[name] = tool

    def list_allowed(self, role):
        return [k for k, t in self.tools.items() if role in t.roles]

    def validate_arguments(self, name, arguments, role):
        if name not in self.list_allowed(role):
            raise PermissionError("TOOL_DENIED")
        return self.tools[name].schema.model_validate(arguments)

    async def invoke(self, rid, state, name, arguments, role="ANALYST"):
        args = self.validate_arguments(name, arguments, role)
        values = args.model_dump(mode="json")
        checksum = digest(values)
        with db.writer.begin() as conn:
            r = run(conn, rid, True)
            if r.state != state:
                raise InterruptedError()
            stmt = select(db.calls).where(
                db.calls.c.run_id == rid, db.calls.c.tool_name == name, db.calls.c.input_digest == checksum
            )
            prev = conn.execute(stmt).mappings().one_or_none()
            if prev and prev.evidence_id:
                return conn.scalar(
                    select(db.evidence.c.payload).where(db.evidence.c.evidence_id == prev.evidence_id)
                )
            invocation = prev.invocation_id if prev else uid("call")
            if not prev:
                conn.execute(
                    db.calls.insert().values(
                        invocation_id=invocation,
                        run_id=rid,
                        tool_name=name,
                        input_digest=checksum,
                        result_status="STARTED",
                    )
                )
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(asyncio.to_thread(self.tools[name].execute, args), TIMEOUT)
            if not isinstance(result, dict):
                raise ValueError("INVALID_TOOL_RESULT")
        except BaseException:
            with db.writer.begin() as conn:
                conn.execute(
                    db.calls.update()
                    .where(db.calls.c.invocation_id == invocation)
                    .values(result_status="INTERRUPTED", duration_ms=int((time.monotonic() - start) * 1000))
                )
            raise
        with db.writer.begin() as conn:
            r = run(conn, rid, True)
            active = r.state == state
            eid = uid("ev") if active else None
            if active:
                conn.execute(
                    db.evidence.insert().values(
                        evidence_id=eid,
                        run_id=rid,
                        source_key=name,
                        filters=values,
                        payload=result,
                        data_version=VERSION,
                    )
                )
                event(conn, r, "tool.completed", tool=name, evidence_id=eid)
            conn.execute(
                db.calls.update()
                .where(db.calls.c.invocation_id == invocation)
                .values(
                    evidence_id=eid,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    result_status="SUCCESS" if active else "DISCARDED",
                )
            )
        if not active:
            raise InterruptedError()
        return result


registry = Registry()
for name, fn in [
    ("get_payment_metrics", metrics.metrics),
    ("compare_payment_periods", metrics.compare),
    ("get_error_distribution", metrics.errors),
    ("get_release_changes", metrics.release_changes),
]:
    registry.register(name, Tool(Scope, fn))
registry.register(
    "get_failure_breakdown",
    Tool(
        BreakdownArgs,
        lambda args: metrics.breakdown(
            Scope.model_validate(args.model_dump(exclude={"dimension"})), args.dimension
        ),
    ),
)
registry.register(
    "search_payment_kb", Tool(SearchArgs, lambda args: knowledge.search(args.query, args.model_dump()))
)
