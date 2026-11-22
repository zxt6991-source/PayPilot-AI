"""Paired component-fault experiment. Launched by study.py in an empty private DB."""

import argparse
import json
import math
import re
import statistics
import time
from datetime import timedelta
from pathlib import Path

from app.config import ADMIN_URL, ANCHOR, LAG
from app.knowledge import ingest
from app.main import app
from fastapi.testclient import TestClient
from runner import oracle, run_question
from sqlalchemy import create_engine, text

# Within each 3,000-row block both markets get the same traffic, with 2/100
# ordinary issuer declines per cell. Three older slices and two current slices.
TRAFFIC = """
create temporary table traffic as
with cells as (
    select i, i % 100 as request, i / 100 % 5 as slice,
        i / 500 % 3 as cohort, i / 1500 % 2 as market
    from generate_series(0, :size - 1) i
)
select 'lab-' || i as id, request, market, cohort, slice,
    case when request between 2 and 13 then 'external_app' else 'inline' end as return_path,
    case when request between 2 and 13 then 'secondary' else 'primary' end as gateway_pool,
    cast(:window_end as timestamptz)
        - (array[60,42,30,20,8])[slice+1] * interval '1 hour'
        + ((i * 31) % 7200) * interval '1 second' as finished,
    case when market=0 then 'DE' else 'SG' end as country,
    case when market=0 then 'Klarna' else 'Card' end as method,
    case when cohort=2 then 'Web' else 'Android' end as channel,
    (array['2.4','2.5','web'])[cohort+1] as version
from cells
"""
BASELINE = """
insert into payment_attempts (payment_attempt_id, order_id_hash, created_at, finalized_at,
    country_code, payment_method, channel, app_version, status, failure_stage, error_code,
    dataset_version, environment, seed_batch_id)
select id, md5(id), finished - interval '5 seconds', finished, country, method, channel, version,
    case when request < 2 then 'FAILED' else 'SUCCESS' end,
    case when request < 2 then 'authorization' end, case when request < 2 then 'issuer_declined' end,
    'demo-v1', 'DEMO', 'component-study-v1' from traffic
"""
# Replay the same attempts through both component configurations. Only their
# normalized payment outcomes enter the reader's schema. The fixture's paths,
# gateway health and callback delays live in the setup connection alone.
REPLAY = """
with components as (
    select id, request,
        case when :remove_handler and country='DE' and channel='Android' and version='2.5'
            and finished>=:rollout and return_path='external_app'
            then null else 2 end as callback_after_seconds,
        not (:disable_pool and country='SG' and channel='Web' and finished>=:rollout
            and gateway_pool='secondary') as gateway_connected
    from traffic
), outcomes as (
    select id, case when not gateway_connected then 'network_error'
        when request<2 then 'issuer_declined'
        when callback_after_seconds is null or callback_after_seconds>30 then 'redirect_timeout'
        end as error from components
)
update payment_attempts p set status=case when o.error is null then 'SUCCESS' else 'FAILED' end,
    failure_stage=case o.error when 'redirect_timeout' then 'client' when 'network_error' then 'gateway'
        when 'issuer_declined' then 'authorization' end,
    error_code=o.error from outcomes o where o.id=p.payment_attempt_id and p.error_code is distinct from o.error
returning p.country_code, p.channel, p.app_version, p.error_code
"""
SCENARIOS = [
    ("callback", "DE", "Klarna", None, "Android", "redirect_timeout", "回跳", "回跳处理器未注册"),
    ("gateway", "SG", "Card", None, "Web", "network_error", "网络", "网关连接池不可用"),
    ("de-control", "DE", "Klarna", "Web", None, None, None, None),
    ("sg-control", "SG", "Card", "Android", None, None, None, None),
]


def record(client, scenario, arm, size, repeat):
    name, country, method, channel, target, code, direction, cause = scenario
    scope = [country, method, "24h", channel]
    q = f"分析 {country} {method} 最近24小时 {channel or '全部终端'} 的支付异常和失败分布。"
    row = dict(scenario=name, arm=arm, size=size, repeat=repeat, question=q)
    start = time.monotonic()
    try:
        run, seconds = run_question(client, q)
        row.update(seconds=round(seconds, 4), state=run["state"], run_id=run["run_id"])
        report = run["report"] or {}
        evidence = {e["source_key"]: e for e in run["evidence"]}
        errors = evidence.get("get_error_distribution", {}).get("payload", {})
        top = next(iter(errors.get("rows", [])), {})
        focus = errors.get("filters", {}).get("channel")
        hypotheses = [h["text"] for h in report.get("hypotheses", [])]
        claims = [f["text"] for f in report.get("findings", [])] + hypotheses
        metrics = report.get("metrics") or {}
        gold, _, error_counts = oracle(scope)
        affected = arm == "injected" and code is not None
        evidence_ids = {e["evidence_id"] for e in run["evidence"]}
        row.update(
            oracle=gold,
            observed_metrics={k: metrics.get(k) for k in gold},
            metrics_match=all(k in metrics and metrics[k] == v for k, v in gold.items()),
            error_counts_match=errors.get("failed_attempts") == sum(error_counts.values())
            and {item["error_code"]: item["count"] for item in errors.get("rows", [])} == error_counts,
            scope_match=[
                report.get("scope", {}).get(k)
                for k in ("country_code", "payment_method", "period", "channel")
            ]
            == scope,
            focus=focus,
            top_error=top,
            focus_failures=errors.get("failed_attempts"),
            hypotheses=hypotheses,
            status=report.get("status"),
            evidence_ids=sorted(evidence_ids),
            evidence_linked=bool(report.get("findings"))
            and all(
                h["evidence_ids"] and set(h["evidence_ids"]) <= evidence_ids
                for h in report.get("findings", []) + report.get("hypotheses", [])
            ),
            symptom_match=(focus == target and top.get("error_code") == code)
            if affected
            else top.get("error_code") == "issuer_declined",
            hypothesis_points_to_component=any(direction in h for h in hypotheses) if affected else None,
            exact_cause_named=any(cause in h for h in claims) if affected else None,
            unexpected_hypothesis=bool(hypotheses) if not affected else None,
        )
    except Exception as exc:
        row.update(error=type(exc).__name__, seconds=row.get("seconds", round(time.monotonic() - start, 4)))
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("size", type=int, choices=(3000, 30000, 300000))
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    engine = create_engine(ADMIN_URL)
    rows = []
    changed = {}
    end = ANCHOR - LAG
    rollout = end - timedelta(hours=12)
    with engine.connect() as conn:
        name = conn.scalar(text("select current_database()"))
        if not re.fullmatch(r"paypilot_study_[0-9a-f]{32}", name) or conn.scalar(
            text("select count(*) from payment_attempts")
        ):
            raise ValueError("run via study.py scale in a fresh study database")
        conn.execute(text(TRAFFIC), {"size": args.size, "window_end": end})
        conn.execute(text(BASELINE))
        conn.execute(
            text("""create temporary table original_outcomes as select payment_attempt_id,
            status, error_code, failure_stage from payment_attempts""")
        )
        if conn.scalar(text("select count(*) from payment_attempts")) != args.size:
            raise ValueError("fixture size mismatch")
        ingest(conn)
        conn.execute(
            text("""insert into release_events values
            ('study-release','Android','2.5',cast(:end as timestamptz)-interval '12 hours',
             'Android rollout', 'demo-v1')"""),
            {"end": end},
        )
        conn.commit()
        with TestClient(app) as client:
            for arm in ("healthy", "injected", "repaired"):
                if arm != "healthy":
                    enabled = arm == "injected"
                    transitions = {}
                    params = {"remove_handler": enabled, "disable_pool": enabled, "rollout": rollout}
                    for c, ch, version, code in conn.execute(text(REPLAY), params):
                        key = "/".join((c, ch, version, code or "SUCCESS"))
                        transitions[key] = transitions.get(key, 0) + 1
                    changed[arm] = transitions
                    expected = args.size // 3000 * 12
                    if transitions != {
                        "DE/Android/2.5/" + ("redirect_timeout" if enabled else "SUCCESS"): expected,
                        "SG/Web/web/" + ("network_error" if enabled else "SUCCESS"): expected,
                    }:
                        raise ValueError("unexpected intervention cohorts")
                conn.execute(text("analyze payment_attempts"))
                conn.commit()
                for repeat in range(5):
                    for n in range(len(SCENARIOS)):
                        scenario = SCENARIOS[(n + repeat) % len(SCENARIOS)]
                        rows.append(record(client, scenario, arm, args.size, repeat + 1))
        residual = conn.scalar(
            text("""select count(*) from original_outcomes o full join payment_attempts p
            using (payment_attempt_id) where (o.status,o.error_code,o.failure_stage)
            is distinct from (p.status,p.error_code,p.failure_stage)""")
        )
    durations = sorted(r["seconds"] for r in rows)
    passed = sum(
        all(
            r.get(k)
            for k in (
                "metrics_match",
                "error_counts_match",
                "scope_match",
                "symptom_match",
                "evidence_linked",
            )
        )
        for r in rows
    )
    summary = dict(
        size=args.size,
        provider="rules",
        repeats_per_arm_scenario=5,
        changed=changed,
        repaired_outcome_differences=residual,
        fixture="component-study-v1",
        rollout_utc=rollout.isoformat(),
        completed=sum(r.get("state") == "COMPLETED" for r in rows),
        total=len(rows),
        data_checks_passed=passed,
        p50_seconds=statistics.median(durations),
        p95_seconds=durations[math.ceil(len(rows) * 0.95) - 1],
        postgres=engine.dialect.server_version_info,
    )
    (args.out / f"{args.size}.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    )
    (args.out / f"{args.size}-summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    )
    print(summary, flush=True)
    return int(passed != len(rows) or residual != 0)


if __name__ == "__main__":
    raise SystemExit(main())
