from app.config import VERSION
from app.schemas import DiagnosisReport

from .intent import ACTIONS
from .store import uid


def projection(items):
    current, comp = (items[k]["payload"] for k in ("get_payment_metrics", "compare_payment_periods"))
    fields = ("valid_attempts", "successful_attempts", "failed_attempts", "psr")
    if (
        any(current[k] != comp["current"][k] for k in fields)
        or current["query_window"] != comp["query_window"]
    ):
        raise ValueError("METRIC_EVIDENCE_MISMATCH")
    return {k: current[k] for k in fields[:-1]} | {
        "current_psr": current["psr"],
        "baseline_psr": comp["baseline"]["psr"],
        "delta_pp": comp["delta_pp"],
        "evidence_ids": [items[k]["evidence_id"] for k in ("get_payment_metrics", "compare_payment_periods")],
    }


def build(r, items, action):
    def claim(key, text):
        return {"text": text, "evidence_ids": [items[key]["evidence_id"]]}

    hits = items["search_payment_kb"]["payload"]["hits"]
    report = dict(
        schema_version="report-v1",
        environment="DEMO",
        report_id=uid("report"),
        run_id=r.run_id,
        dataset_version=VERSION,
        scope=r.filters,
        status="HYPOTHESIS_ONLY",
        metrics=None,
        findings=[],
        hypotheses=[],
        citations=[h["chunk_id"] for h in hits],
        actions=[ACTIONS[action]],
        uncertainties=["现有观察无法确认具体 SDK 版本或发布为故障根因。"],
    )
    kb = items["search_payment_kb"]["payload"]
    if kb["status"] == "CONFLICT":
        report["uncertainties"].append("命中的知识来源存在版本冲突，需要复核原文。")
    if not hits:
        report["uncertainties"].append("当前范围缺少匹配的知识条目。")
    if r.intent == "knowledge":
        report["findings"] = [claim("search_payment_kb", h["content"]) for h in hits]
        report["actions"] = []
        return report
    report["metrics"] = projection(items)
    for row in items["get_failure_breakdown"]["payload"]["rows"]:
        if row["psr"] is not None:
            report["findings"].append(
                claim(
                    "get_failure_breakdown",
                    f"{row['value']} 成功 {row['successful_attempts']}/{row['valid_attempts']}，PSR {row['psr']:.1%}。",
                )
            )
    errors = items["get_error_distribution"]["payload"]
    for row in errors["rows"]:
        report["findings"].append(
            claim(
                "get_error_distribution",
                f"{errors['filters']['channel']} · {row['error_code']} 占该终端失败尝试 {row['count']}/{errors['failed_attempts']}（{row['share_of_failures']:.1%}）。",
            )
        )
    timeout = next((x for x in errors["rows"] if x["error_code"] == "redirect_timeout"), None)
    if (
        timeout
        and kb["status"] != "CONFLICT"
        and errors["failed_attempts"] >= 30
        and timeout["share_of_failures"] >= 0.5
        and hits
    ):
        report["hypotheses"].append(
            dict(
                claim("get_error_distribution", f"{errors['filters']['channel']} 回跳链路值得优先排查。"),
                confidence_label="NEEDS_VERIFICATION",
                evidence_ids=[
                    items["get_error_distribution"]["evidence_id"],
                    items["search_payment_kb"]["evidence_id"],
                ],
            )
        )
    if "get_release_changes" in items:
        changes = items["get_release_changes"]["payload"]["rows"]
        report["findings"].append(
            claim("get_release_changes", f"所选窗口和终端匹配 {len(changes)} 条演示发布记录。")
        )
    if items["compare_payment_periods"]["payload"]["baseline"]["quality_flags"]:
        report["uncertainties"].append("基准样本不足，周期差异需谨慎解读。")
    return report


def validate(report, r, items):
    from sqlalchemy import select

    from app.db import chunks, reader

    DiagnosisReport.model_validate(report)
    if report["run_id"] != r.run_id or report["scope"] != r.filters or report["status"] != "HYPOTHESIS_ONLY":
        raise ValueError("REPORT_SCOPE_MISMATCH")
    for item in items.values():
        if (
            item["run_id"] != r.run_id
            or item["data_version"] != VERSION
            or item["filters"]["as_of"] != r.filters["as_of"]
        ):
            raise ValueError("FOREIGN_EVIDENCE")
        for key in ("country_code", "payment_method", "period", "app_version"):
            if item["filters"].get(key) != r.filters.get(key):
                raise ValueError("FOREIGN_SCOPE")
        if r.filters.get("channel") and item["filters"].get("channel") != r.filters["channel"]:
            raise ValueError("FOREIGN_CHANNEL")
    if r.intent != "knowledge" and report["metrics"] != projection(items):
        raise ValueError("METRIC_EVIDENCE_MISMATCH")
    expected = build(r, items, "compare")
    if any(report[k] != expected[k] for k in ("findings", "hypotheses", "citations")):
        raise ValueError("UNSUPPORTED_CLAIM")
    allowed = {i["evidence_id"] for i in items.values()}
    for claim in report["findings"] + report["hypotheses"]:
        if not claim["evidence_ids"] or not set(claim["evidence_ids"]) <= allowed:
            raise ValueError("UNKNOWN_EVIDENCE")
    citations = set(report["citations"])
    retrieved = {h["chunk_id"] for h in items["search_payment_kb"]["payload"]["hits"]}
    with reader.connect() as conn:
        existing = set(conn.scalars(select(chunks.c.chunk_id).where(chunks.c.chunk_id.in_(citations))))
    if not citations <= retrieved or existing != citations:
        raise ValueError("UNKNOWN_CITATION")
