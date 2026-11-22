import time
from uuid import uuid4

import pytest
from app import db
from app.agent import registry, runtime
from app.agent.store import run, transition
from app.schemas import Scope
from conftest import wait_run
from pydantic import ValidationError

GOLD = "分析德国 Klarna 最近 24 小时成功率下降的原因"


def start(client, question=GOLD):
    res = client.post("/api/diagnoses", json={"question": question})
    assert res.status_code == 202, res.text
    return res.json()


def test_contract_and_roles():
    reg = registry.registry
    for name in ("refund", "run_sql", "shell", "change_route"):
        with pytest.raises(PermissionError):
            reg.validate_arguments(name, {}, "ANALYST")
    with pytest.raises(PermissionError):
        reg.validate_arguments("get_payment_metrics", {}, "GUEST")
    with pytest.raises(ValidationError):
        reg.validate_arguments("get_failure_breakdown", {"dimension": "arbitrary"}, "ANALYST")


def test_full_trace(client):
    tid = start(client)["task_id"]
    r = wait_run(client, tid)
    assert r["state"] == "COMPLETED", r["reason"]
    assert r["report"]["metrics"]["delta_pp"] == -5.8
    assert r["report"]["metrics"]["current_psr"] == client.get("/api/metrics").json()["psr"]
    assert r["report"]["hypotheses"] and r["report"]["citations"]
    assert len(r["tools"]) == 5
    rid = r["run_id"]
    assert r["events"][-1]["event_type"] == "report.ready"
    seq = r["events"][-2]["sequence"]
    replay = client.get(f"/api/diagnoses/{tid}/events", headers={"Last-Event-ID": f"{rid}:{seq}"}).text
    assert replay.count("event:") == 1 and "report.ready" in replay
    assert len(client.get("/api/diagnoses/" + tid).json()["tools"]) == 5
    with db.writer.begin() as conn, pytest.raises(Exception, match="409"):
        transition(conn, run(conn, rid, True), "QUERYING")


def test_clarification_and_followup(client):
    tid = start(client, "分析成功率")["task_id"]
    r = wait_run(client, tid)
    assert r["state"] == "CLARIFYING" and not r["tools"]
    path = "/api/diagnoses/" + tid + "/messages"
    res = client.post(path, json={"run_id": r["run_id"], "question": "德国 Klarna"})
    assert res.json()["run_id"] == r["run_id"]
    done = wait_run(client, tid)
    assert done["report"]["metrics"]["current_psr"] == 0.892
    second = client.post(path, json={"run_id": r["run_id"], "question": "Android 版本发布有关吗"})
    assert second.status_code == 202 and second.json()["run_id"] != r["run_id"]
    follow = wait_run(client, tid)
    assert follow["parent_run"] == r["run_id"] and "get_release_changes" in [
        t["tool_name"] for t in follow["tools"]
    ]
    assert client.get("/api/reports/" + done["report"]["report_id"]).json()["run_id"] == r["run_id"]
    assert client.post(path, json={"run_id": r["run_id"], "question": "旧请求"}).status_code == 409


def test_exclusion_clarifies_before_query_and_resumes_same_scope(client):
    tid = start(client, "分析德国最近7天，排除安卓")["task_id"]
    r = wait_run(client, tid)
    assert r["state"] == "CLARIFYING" and not r["tools"]
    assert r["events"][-1]["payload"]["missing_fields"] == ["payment_method", "channel"]
    path = f"/api/diagnoses/{tid}/messages"
    rid = r["run_id"]
    assert client.post(path, json={"run_id": rid, "question": "Web"}).status_code == 202
    r = wait_run(client, tid)
    assert r["events"][-1]["payload"]["missing_fields"] == ["payment_method"]
    assert r["filters"]["channel"] == "Web" and not r["tools"]
    assert client.post(path, json={"run_id": rid, "question": "Klarna"}).status_code == 202
    done = wait_run(client, tid)
    assert done["state"] == "COMPLETED" and done["run_id"] == rid
    scope = done["report"]["scope"]
    assert [scope[k] for k in ("country_code", "payment_method", "period", "channel")] == [
        "DE",
        "Klarna",
        "7d",
        "Web",
    ]
    assert (
        done["report"]["metrics"]["valid_attempts"]
        == client.get(
            "/api/metrics",
            params={k: scope[k] for k in ("country_code", "payment_method", "period", "channel")},
        ).json()["valid_attempts"]
    )


@pytest.mark.parametrize(
    "question,intent,state",
    [
        ("直接切换支付渠道", "refuse", "INSUFFICIENT_DATA"),
        ("自动退款", "refuse", "INSUFFICIENT_DATA"),
        ("分析德国 Klarna iOS", "diagnosis", "INSUFFICIENT_DATA"),
        ("解释未知术语 XYZ", "knowledge", "INSUFFICIENT_DATA"),
        ("解释 redirect_timeout 含义", "knowledge", "COMPLETED"),
    ],
)
def test_edges(client, question, intent, state):
    r = wait_run(client, start(client, question)["task_id"])
    assert (r["intent"], r["state"]) == (intent, state)
    if intent == "refuse":
        assert not r["tools"] and not r["evidence"]


@pytest.mark.parametrize(
    "reply",
    [
        {"question": "换成最近七天"},
        {"question": "按所选的周期查", "filters": {"period": "7d"}},
    ],
)
def test_period_clarification_resumes_after_partial_answers(client, reply):
    from datetime import datetime, timedelta

    tid = start(client, "英国 Web 最近17天的成功率")["task_id"]
    r = wait_run(client, tid)
    assert r["state"] == "CLARIFYING" and not r["tools"] and "period" not in r["filters"]
    assert r["events"][-1]["payload"]["missing_fields"] == ["payment_method", "period"]
    path = f"/api/diagnoses/{tid}/messages"
    rid = r["run_id"]
    assert client.post(path, json={"run_id": rid, **reply}).status_code == 202
    partial = wait_run(client, tid)
    assert partial["state"] == "CLARIFYING" and not partial["tools"]
    assert partial["filters"]["period"] == "7d"
    assert partial["events"][-1]["payload"]["missing_fields"] == ["payment_method"]
    assert client.post(path, json={"run_id": rid, "question": "Card"}).status_code == 202
    done = wait_run(client, tid)
    assert done["run_id"] == rid and done["state"] == "COMPLETED"
    assert done["report"]["scope"]["period"] == "7d"
    evidence = next(e["payload"] for e in done["evidence"] if e["source_key"] == "get_payment_metrics")
    window = evidence["query_window"]
    assert datetime.fromisoformat(window["end_at"]) - datetime.fromisoformat(window["start_at"]) == timedelta(
        days=7
    )
    assert evidence["valid_attempts"] == done["report"]["metrics"]["valid_attempts"]


def test_explicit_unsupported_period_overrides_a_provider_guess(client, monkeypatch):
    from app.agent import intent

    async def guess_period(question, filters):
        return intent.Intent(intent="diagnosis", period="24h", country_code="GB", payment_method="Card"), {}

    monkeypatch.setattr(intent, "parse", guess_period)
    run = wait_run(client, start(client, "英国 Card 最近 27 天")["task_id"])
    assert run["state"] == "CLARIFYING" and not run["tools"] and "period" not in run["filters"]


def test_period_wording_resumes_diagnosis_instead_of_kb_lookup(client):
    tid = start(client, "新加坡 Card 的 Web 支付，7 天和 30 天两个口径分别统计。")["task_id"]
    first = wait_run(client, tid)
    assert first["state"] == "CLARIFYING" and first["intent"] == "diagnosis"
    assert first["events"][-1]["payload"]["missing_fields"] == ["period"] and not first["tools"]
    reply = client.post(
        f"/api/diagnoses/{tid}/messages", json={"run_id": first["run_id"], "question": "取7天"}
    )
    assert reply.status_code == 202
    done = wait_run(client, tid)
    assert (
        done["run_id"] == first["run_id"] and done["intent"] == "diagnosis" and done["state"] == "COMPLETED"
    )
    assert done["report"]["scope"]["period"] == "7d"
    expected = client.get(
        "/api/metrics",
        params={"country_code": "SG", "payment_method": "Card", "channel": "Web", "period": "7d"},
    ).json()
    assert done["report"]["metrics"]["valid_attempts"] == expected["valid_attempts"] > 0


def test_definition_request_with_scope_wording_stays_knowledge(client):
    done = wait_run(
        client, start(client, "解释 PSR 分母的口径，按这个口径统计时包括 PENDING 吗？")["task_id"]
    )
    assert done["state"] == "COMPLETED" and done["intent"] == "knowledge"
    assert done["report"]["metrics"] is None and done["report"]["citations"]


def test_idempotency(client):
    key = {"Idempotency-Key": uuid4().hex}

    def post(q):
        return client.post("/api/diagnoses", json={"question": q}, headers=key)

    r = post("成功率").json()
    assert post("成功率").json()["run_id"] == r["run_id"]
    assert post("其他问题").status_code == 409


def test_cancellation_during_tool(client, monkeypatch):
    import threading

    from app.agent.registry import Tool

    invoked = threading.Event()
    release = threading.Event()

    def slow(scope):
        invoked.set()
        release.wait(3)
        return {}

    monkeypatch.setitem(registry.registry.tools, "get_payment_metrics", Tool(Scope, slow))
    r = start(client)
    assert invoked.wait(2)
    path = "/api/diagnoses/" + r["task_id"]
    for _ in range(2):
        assert client.post(path + "/cancel", json={"run_id": r["run_id"]}).json()["state"] == "CANCELLED"
    release.set()
    for _ in range(100):
        if r["run_id"] not in runtime.workers:
            break
        time.sleep(0.02)
    last = client.get(path).json()
    assert last["state"] == "CANCELLED" and not last["evidence"] and len(last["tools"]) == 1
    assert last["tools"][0]["result_status"] == "DISCARDED"


def test_timeout(client, monkeypatch):
    from app.agent.registry import Tool

    monkeypatch.setattr(registry, "TIMEOUT", 0.01)
    monkeypatch.setitem(
        registry.registry.tools,
        "get_payment_metrics",
        Tool(Scope, lambda _: time.sleep(0.06)),
    )
    r = wait_run(client, start(client)["task_id"])
    assert r["state"] == "FAILED" and r["reason"] == "TIMEOUT"
    assert r["tools"][0]["result_status"] == "INTERRUPTED"


def test_other_owner(client, monkeypatch):
    monkeypatch.setenv("DEMO_IDENTITIES", '{"test-token":{"owner":"analyst-b","role":"ANALYST"}}')
    r = start(client)
    path = "/api/diagnoses/" + r["task_id"]
    other = {"Authorization": "Bearer test-token"}
    assert client.get(path, headers=other).status_code == 404
    assert client.get(path + "/events", headers=other).status_code == 404
    assert client.post(path + "/cancel", json={"run_id": r["run_id"]}, headers=other).status_code == 404
    wait_run(client, r["task_id"])


def test_restart_recovers_completed_tool_without_duplication():
    import asyncio

    from app.agent.store import create
    from app.main import app
    from app.schemas import CreateTask
    from fastapi.testclient import TestClient

    tid, rid, _, _ = create("demo-analyst", CreateTask(question=GOLD), uuid4().hex)

    # Crash boundary after the first evidence was committed, before QUERYING finished.
    async def checkpoint():
        for _ in range(2):
            with db.writer.connect() as conn:
                r = run(conn, rid)
            await runtime.node(r)
        with db.writer.connect() as conn:
            r = run(conn, rid)
        await registry.registry.invoke(rid, "QUERYING", "get_payment_metrics", r.filters)

    asyncio.run(checkpoint())
    with TestClient(app) as client:
        saved = wait_run(client, tid)
    assert saved["state"] == "COMPLETED"
    assert [x["tool_name"] for x in saved["tools"]].count("get_payment_metrics") == 1
