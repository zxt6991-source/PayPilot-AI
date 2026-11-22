import json
import sys

from evaluation import runner


def test_pilot_retries_preserve_both_archives(tmp_path, monkeypatch):
    pilot = runner.BASE / "datasets/pilot-dev-v1.jsonl"
    monkeypatch.setattr(runner, "BASE", tmp_path)
    monkeypatch.setattr(sys, "argv", ["runner", "--dataset", str(pilot)])
    for _ in range(2):
        assert runner.main() == 0
    results = tmp_path / "results"
    summaries = list(results.glob("experiments/*/custom-summary.json"))
    assert len(summaries) == 2
    for path in summaries:
        summary = json.loads(path.read_text())
        assert (summary["provider"], summary["passed"], summary["total"]) == ("rules", 4, 4)
        rows = [json.loads(line) for line in path.with_name("custom.jsonl").read_text().splitlines()]
        assert len(rows) == 4 and rows[0]["observed_filters"]["channel"] == "Android"
        assert rows[0]["observed_usage"] is None
    assert not list(results.glob("*.json*"))


def test_clarification_state_alone_cannot_pass():
    expected = {
        "state": "CLARIFYING",
        "retained_filters": {"country_code": "GB", "period": "7d"},
        "missing_fields": ["payment_method"],
    }
    run = {
        "state": "CLARIFYING",
        "filters": {"period": "24h"},
        "events": [{"event_type": "clarification.required", "payload": {"missing_fields": ["country_code"]}}],
        "evidence": [],
        "report": None,
        "tools": [],
    }
    checks = runner.score({"expected": expected}, run)
    assert checks["state"] and not checks["retained_filters"] and not checks["missing_fields"]


def test_empty_scope_with_wrong_zero_denominator_is_rejected():
    scope = ["SG", "Klarna", "30d", "Web"]
    case = {"expected": {"state": "INSUFFICIENT_DATA", "empty_scope": scope}}
    filters = dict(country_code="DE", payment_method="PayPal", period="30d", channel="Web")
    result = {
        "state": "INSUFFICIENT_DATA",
        "report": None,
        "evidence": [
            {"source_key": "get_payment_metrics", "payload": {"valid_attempts": 0, "filters": filters}}
        ],
    }
    checks = runner.score(case, result)
    assert checks["empty_sample"] and not checks["empty_query_scope"]


def test_two_versions_partition_the_android_denominator():
    scope = ["DE", "Klarna", "24h", "Android"]
    overall, _, _ = runner.oracle(scope)
    by_version = [runner.oracle(scope, v) for v in ("2.4", "2.5")]
    assert [m["valid_attempts"] for m, _, _ in by_version] == [505, 495]
    assert sum(sum(errors.values()) for _, _, errors in by_version) == overall["failed_attempts"]
