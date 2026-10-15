import json
from datetime import UTC, datetime

import httpx
import pytest

from app.contracts import VicoError
from app.providers.base import QuotaTracker, seconds_until_quota_reset
from app.providers.gemini import GeminiProvider

pytestmark = pytest.mark.anyio

MODELS = {"models": [
    {"name": "models/gemini-3.6-flash", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-4-argon", "supportedGenerationMethods": ["generateContent"]},
]}
OK = {"candidates": [{"content": {"parts": [{"text": "{\"kind\":\"done\",\"message\":\"ok\"}"}]}}]}
PER_MINUTE = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [
    {"violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "34s"}]}}
PER_DAY = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [
    {"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}


def provider(limited: dict[str, dict], calls: list[str], **kw) -> GeminiProvider:
    def handler(request: httpx.Request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS)
        model = request.url.path.split("/models/")[1].split(":")[0]
        calls.append(model)
        if model in limited:
            return httpx.Response(429, json=limited[model])
        return httpx.Response(200, json=OK)

    return GeminiProvider("AIzaTest", httpx.AsyncClient(transport=httpx.MockTransport(handler)), QuotaTracker(), **kw)


async def test_uses_the_free_flash_model_first():
    calls: list[str] = []
    c = await provider({}, calls).complete("s", "u", json_mode=True)
    assert c.model == "gemini-3.6-flash" and calls == ["gemini-3.6-flash"]


async def test_switches_to_flash_lite_within_the_same_request():
    calls: list[str] = []
    p = provider({"gemini-3.6-flash": PER_MINUTE}, calls)
    c = await p.complete("s", "u", json_mode=True)
    assert c.model == "gemini-3.5-flash-lite"
    assert calls == ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
    # the limited model is skipped on the next request, so no wasted call
    await p.complete("s", "u", json_mode=True)
    assert calls[-1] == "gemini-3.5-flash-lite" and calls.count("gemini-3.6-flash") == 1
    assert 30 < p.cooldowns()["gemini-3.6-flash"] <= 34
    assert p.cooldown_s() == 0  # one model is still usable


async def test_both_limited_reports_the_shortest_cooldown():
    calls: list[str] = []
    p = provider({"gemini-3.6-flash": PER_DAY, "gemini-3.5-flash-lite": PER_MINUTE}, calls)
    with pytest.raises(VicoError) as exc:
        await p.complete("s", "u", json_mode=True)
    assert exc.value.code == "rate_limited"
    assert 30 < exc.value.retry_after_s <= 34
    assert p.cooldown_s() == pytest.approx(exc.value.retry_after_s, abs=1)


async def test_daily_limit_waits_until_midnight_pacific():
    calls: list[str] = []
    p = provider({"gemini-3.6-flash": PER_DAY, "gemini-3.5-flash-lite": PER_DAY}, calls)
    with pytest.raises(VicoError) as exc:
        await p.complete("s", "u", json_mode=True)
    assert exc.value.retry_after_s > 60
    assert "resets at about" in exc.value.message


async def test_paid_only_models_are_never_chosen_automatically():
    calls: list[str] = []
    p = provider({"gemini-3.6-flash": PER_MINUTE, "gemini-3.5-flash-lite": PER_MINUTE}, calls)
    with pytest.raises(VicoError):
        await p.complete("s", "u", json_mode=True)
    assert "gemini-4-argon" not in calls


async def test_chosen_model_is_tried_first_then_free_chain():
    calls: list[str] = []
    p = provider({"gemini-4-argon": PER_MINUTE}, calls, llm_model="gemini-4-argon")
    c = await p.complete("s", "u", json_mode=True)
    assert calls == ["gemini-4-argon", "gemini-3.6-flash"] and c.model == "gemini-3.6-flash"


def test_quota_reset_is_midnight_pacific():
    # 2026-10-14 23:00 UTC is 16:00 in Los Angeles (PDT), so 8 hours remain.
    assert seconds_until_quota_reset(datetime(2026, 10, 14, 23, 0, tzinfo=UTC)) == 8 * 3600


def test_error_bodies_are_realistic_json():
    assert json.loads(json.dumps(PER_MINUTE))["error"]["status"] == "RESOURCE_EXHAUSTED"
