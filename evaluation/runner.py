"""Run the actual ASGI app and audit each result against independent PostgreSQL queries."""

import argparse
import hashlib
import json
import math
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent / "backend"))
from app import db
from app.agent.intent import MODEL, PROMPT_VERSION
from app.agent.store import FLOW
from app.config import ANCHOR, LAG, RANKER, VERSION
from app.main import app


def oracle(scope):
    country, method, period, channel = scope
    span = timedelta(days={"24h": 1, "7d": 7, "30d": 30}[period])
    end = ANCHOR - LAG
    with db.reader.connect() as conn:

        def grouped(start, stop):
            return conn.execute(
                text("""select channel,count(*) as n,count(*) filter(where status='SUCCESS') as s
                from payment_attempts where country_code=:country and payment_method=:method
                and channel=coalesce(:channel,channel) and finalized_at>=:start and finalized_at<:stop
                and status in ('SUCCESS','FAILED') and dataset_version=:version group by channel order by channel"""),
                dict(
                    country=country,
                    method=method,
                    channel=channel,
                    start=start,
                    stop=stop,
                    version=VERSION,
                ),
            ).all()

        current, base = grouped(end - span, end), grouped(end - 3 * span, end - span)
        focus = min(current, key=lambda r: (r.s / r.n, r.channel)).channel if current else None
        errors = dict(
            conn.execute(
                text("""select error_code,count(*) from payment_attempts where
             dataset_version=:version and country_code=:country and payment_method=:method and channel=:ch
             and status='FAILED' and finalized_at>=:start and finalized_at<:end group by error_code"""),
                dict(
                    version=VERSION,
                    country=country,
                    method=method,
                    ch=focus,
                    start=end - span,
                    end=end,
                ),
            ).all()
        )
    n = sum(r.n for r in current)
    s = sum(r.s for r in current)
    bn = sum(r.n for r in base)
    bs = sum(r.s for r in base)
    a, b = s / n if n else None, bs / bn if bn else None
    return (
        dict(
            valid_attempts=n,
            successful_attempts=s,
            failed_attempts=n - s,
            current_psr=a,
            baseline_psr=b,
            delta_pp=round((a - b) * 100, 6) if a is not None and b is not None else None,
        ),
        {r.channel: r.n for r in current},
        errors,
    )


def score(case, r):
    gold = case["expected"]
    checks = {"state": r["state"] == gold["state"]}
    report = r["report"] or {}
    ev = {e["source_key"]: e for e in r["evidence"]}
    if "intent" in gold:
        checks["intent"] = r["intent"] == gold["intent"]
    if gold.get("refusal"):
        checks["readonly_refusal"] = r["intent"] == "refuse" and not r["tools"]
    if "scope" in gold:
        metrics, groups, errors = oracle(gold["scope"])
        observed = report.get("metrics") or {}
        for k, v in metrics.items():
            checks[k] = k in observed and (
                observed[k] == v
                or isinstance(v, float)
                and isinstance(observed[k], (float, int))
                and abs(v - observed[k]) < 1e-8
            )
        checks["scope"] = [
            r["filters"].get(k) for k in ("country_code", "payment_method", "period", "channel")
        ] == gold["scope"]
        if case["category"] == "异常诊断":
            total = sum(errors.values())
            concentrated = total >= 30 and errors.get("redirect_timeout", 0) * 2 >= total
            checks["diagnosis_class"] = bool(report.get("hypotheses")) == concentrated
        if gold.get("breakdown"):
            rows = ev.get("get_failure_breakdown", {}).get("payload", {}).get("rows", [])
            checks["group_denominators"] = {row["value"]: row["valid_attempts"] for row in rows} == groups
            rows = ev.get("get_error_distribution", {}).get("payload", {}).get("rows", [])
            checks["error_counts"] = {row["error_code"]: row["count"] for row in rows} == errors
    if gold.get("abstain"):
        checks["abstain"] = report.get("status") == "HYPOTHESIS_ONLY" and bool(report.get("uncertainties"))
    hits = ev.get("search_payment_kb", {}).get("payload", {}).get("hits", [])
    if "doc" in gold:
        checks["expected_document"] = any(
            h["document_id"] == gold["doc"] for h in hits if h["chunk_id"] in report.get("citations", [])
        )
    if report:
        allowed = {e["evidence_id"] for e in r["evidence"]}
        checks["evidence_links"] = all(
            bool(f["evidence_ids"]) and set(f["evidence_ids"]) <= allowed
            for f in report["findings"] + report["hypotheses"]
        )
        cited = report["citations"]
        checks["citation_membership"] = set(cited) <= {h["chunk_id"] for h in hits}
        if cited:
            with db.reader.connect() as conn:
                checks["citation_exists"] = set(cited) == set(
                    conn.scalars(
                        db.chunks.select()
                        .with_only_columns(db.chunks.c.chunk_id)
                        .where(db.chunks.c.chunk_id.in_(cited))
                    )
                )
    return checks


def execute(client, case):
    start = time.monotonic()
    response = client.post("/api/diagnoses", json={"question": case["input"]})
    response.raise_for_status()
    ids = response.json()
    while time.monotonic() - start < 40:
        snap = client.get(ids["status_url"])
        snap.raise_for_status()
        r = snap.json()
        if r["state"] in (
            "COMPLETED",
            "FAILED",
            "CLARIFYING",
            "INSUFFICIENT_DATA",
            "CANCELLED",
        ):
            break
        time.sleep(0.015)
    elapsed = time.monotonic() - start
    checks = score(case, r)
    return dict(
        case_id=case["case_id"],
        category=case["category"],
        task_id=r["task_id"],
        run_id=r["run_id"],
        state=r["state"],
        passed=all(checks.values()),
        checks=checks,
        seconds=round(elapsed, 4),
        trace=[
            {
                "seq": e["sequence"],
                "event": e["event_type"],
                **{k: v for k, v in e["payload"].items() if k not in ("task_id", "run_id")},
            }
            for e in r["events"]
        ],
        evidence_ids=[e["evidence_id"] for e in r["evidence"]],
        metrics=(r["report"] or {}).get("metrics"),
        citations=(r["report"] or {}).get("citations", []),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "holdout"], default="dev")
    args = parser.parse_args()
    if args.split == "holdout" and RANKER != "v0.4":
        parser.error("holdout is reserved for the frozen candidate")
    path = BASE / "datasets/cases_v1.jsonl"
    split = BASE / "datasets/splits_v1.json"
    ids = json.loads(split.read_text())[args.split]
    cases = [json.loads(line) for line in path.read_text().splitlines()]
    cases = [c for c in cases if c["case_id"] in ids]
    results = []
    with TestClient(app) as client:
        for c in cases:
            try:
                row = execute(client, c)
            except Exception as exc:
                row = dict(
                    case_id=c["case_id"],
                    category=c["category"],
                    passed=False,
                    state="ERROR",
                    error=type(exc).__name__,
                    checks={"state": False},
                    seconds=None,
                )
            results.append(row)
    durations = sorted(r["seconds"] for r in results if r["seconds"] is not None)
    multi_tool = sorted(
        r["seconds"] for r in results if r["state"] == "COMPLETED" and len(r.get("evidence_ids", [])) > 1
    )
    prefix = ("baseline-" if RANKER == "v0.3" else "") + args.split
    categories = defaultdict(lambda: dict(passed=0, total=0))
    for r in results:
        group = categories[r["category"]]
        group["total"] += 1
        group["passed"] += r["passed"]
    meta = dict(
        split=args.split,
        total=len(results),
        passed=sum(r["passed"] for r in results),
        categories=dict(categories),
        expected_state_matches=sum(r["checks"]["state"] for r in results),
        latency_sample_size=len(durations),
        p95_seconds=durations[math.ceil(0.95 * len(durations)) - 1] if durations else None,
        multi_tool_p95_seconds=multi_tool[math.ceil(0.95 * len(multi_tool)) - 1] if multi_tool else None,
        multi_tool_count=len(multi_tool),
        diagnosis_class_correct=sum(r["checks"].get("diagnosis_class", False) for r in results),
        diagnosis_class_total=sum(r["category"] == "异常诊断" for r in results),
        model_id=MODEL,
        workflow_version=FLOW,
        prompt_version=PROMPT_VERSION,
        dataset_version=VERSION,
        kb_version="kb-v1",
        generated_at=datetime.now(timezone.utc).isoformat(),
        dataset_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        split_sha256=hashlib.sha256(split.read_bytes()).hexdigest(),
    )
    out = BASE / "results"
    (out / (prefix + ".jsonl")).write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in results)
    )
    (out / (prefix + "-summary.json")).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    print(f"{prefix}: {meta['passed']}/{meta['total']}; P95 {meta['p95_seconds']}s")
    return int(meta["passed"] != meta["total"])


if __name__ == "__main__":
    raise SystemExit(main())
