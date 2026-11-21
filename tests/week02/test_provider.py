import asyncio

import httpx
from app.agent import intent
from conftest import wait_run


def test_provider_schema_repair(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        message = '{"intent":"knowledge"}' if len(requests) == 2 else '{"intent":"write"}'
        return httpx.Response(
            200, json={"choices": [{"message": {"content": message}}], "usage": {"total_tokens": 48}}
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        intent.httpx,
        "AsyncClient",
        lambda **opts: real_client(transport=httpx.MockTransport(respond), **opts),
    )
    monkeypatch.setattr(intent, "PROVIDER", "compatible")
    monkeypatch.setenv("LLM_BASE_URL", "http://provider.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-token")
    monkeypatch.setattr(intent, "MODEL", "test-model")
    result, usage = asyncio.run(intent.parse("解释 PSR", {}))
    assert result.intent == "knowledge" and usage["total_tokens"] >= 48 and len(requests) == 2
    assert requests[0].url.path == "/v1/chat/completions"


def test_draft_degrades_to_evidence(client, monkeypatch):
    async def broken(*args):
        raise ValueError("MODEL_SCHEMA_INVALID")

    monkeypatch.setattr(intent, "draft", broken)
    t = client.post("/api/diagnoses", json={"question": "分析德国 Klarna"}).json()
    r = wait_run(client, t["task_id"])
    assert r["state"] == "COMPLETED" and r["report"]["metrics"]["current_psr"] == 0.892
    assert any("模型建议暂不可用" in s for s in r["report"]["uncertainties"])


def test_deepseek_uses_official_host_and_validates_both_responses(monkeypatch):
    import json

    seen = []

    def respond(request):
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert request.headers["authorization"] == "Bearer test-only-deepseek-key"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-flash" and body["thinking"] == {"type": "disabled"}
        assert body["response_format"] == {"type": "json_object"}
        seen.append(body)
        contents = [
            "  ",
            '{"intent":"diagnosis","country_code":"DE","payment_method":"Klarna"}',
            '{"action":"callback"}',
        ]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": contents[len(seen) - 1]}}],
                "usage": {"total_tokens": 22},
            },
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        intent.httpx, "AsyncClient", lambda **opts: client(transport=httpx.MockTransport(respond), **opts)
    )
    monkeypatch.setattr(intent, "PROVIDER", "deepseek")
    monkeypatch.setattr(intent, "MODEL", "deepseek-flash")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-deepseek-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://other.invalid")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    intent.check_model_config()
    parsed, usage = asyncio.run(intent.parse("分析德国 Klarna", {}))
    assert parsed.country_code == "DE" and usage["total_tokens"] == 44
    draft, usage = asyncio.run(intent.draft("diagnosis", True, []))
    assert draft.action == "callback" and usage["total_tokens"] == 22


def test_missing_deepseek_key(monkeypatch):
    import pytest

    monkeypatch.setattr(intent, "PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        intent.check_model_config()
