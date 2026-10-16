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


async def test_groq_chain_switches_models_too():
    from app.providers.groq import GroqProvider

    calls: list[str] = []

    def handler(request: httpx.Request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen/qwen3.8-27b"}, {"id": "openai/gpt-oss-120b"}]})
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == "openai/gpt-oss-120b":
            return httpx.Response(429, headers={"retry-after": "12"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    p = GroqProvider("gsk_test", httpx.AsyncClient(transport=httpx.MockTransport(handler)), QuotaTracker())
    c = await p.complete("s", "u", json_mode=True)
    assert c.model == "qwen/qwen3.8-27b" and calls == ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]


async def test_mistral_and_openrouter_are_further_fallbacks():
    from app.providers.groq import MistralProvider, OpenRouterProvider

    seen = []

    def handler(request: httpx.Request):
        if request.url.path.endswith("/models"):
            if "openrouter" in request.url.host:
                return httpx.Response(200, json={"data": [{"id": "openai/gpt-oss-120b"},
                                                          {"id": "openai/gpt-oss-120b:free"}]})
            return httpx.Response(200, json={"data": [{"id": "mistral-embed"}, {"id": "mistral-small-latest"},
                                                      {"id": "voxtral-mini-latest"}]})
        body = json.loads(request.content) if request.content.startswith(b"{") else {}
        seen.append((request.url.host, body.get("model"), "response_format" in body))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert (await MistralProvider("k", client, QuotaTracker()).complete("s", "u", json_mode=True)).model == \
        "mistral-small-latest"
    # OpenRouter: only free models, and no JSON mode flag (not every free model accepts it)
    assert (await OpenRouterProvider("k", client, QuotaTracker()).complete("s", "u", json_mode=True)).model == \
        "openai/gpt-oss-120b:free"
    assert seen == [("api.mistral.ai", "mistral-small-latest", True), ("openrouter.ai", "openai/gpt-oss-120b:free", False)]


async def test_hub_falls_back_to_groq_instantly_and_reports_soonest_cooldown():
    from app.providers.mock import MockProvider
    from app.providers.registry import ProviderHub
    from app.security.secret_store import MemorySecretBackend, SecretStore
    from app.store.settings import Settings

    resting = MockProvider(replies=[VicoError("rate_limited", "gemini resting", retry_after_s=40)] * 2)
    groq_ok = MockProvider(replies=["{\"kind\": \"done\", \"message\": \"ok\"}"])
    hub = ProviderHub(SecretStore(MemorySecretBackend()), lambda: Settings(cloud_consent=True),
                      overrides={"gemini": resting, "groq": groq_ok})
    c = await hub.complete("s", "u")
    assert "done" in c.text and len(groq_ok.calls) == 1

    groq_resting = MockProvider(replies=[VicoError("rate_limited", "groq resting", retry_after_s=9)])
    hub = ProviderHub(SecretStore(MemorySecretBackend()), lambda: Settings(cloud_consent=True),
                      overrides={"gemini": resting, "groq": groq_resting})
    with pytest.raises(VicoError) as exc:
        await hub.complete("s", "u")
    assert exc.value.retry_after_s == 9


@pytest.mark.parametrize("text,expected", [
    ("open my downloads folder", "en"),
    ("create a folder called Hackathon on my desktop", "en"),
    ("Ṣẹ̀dá fóldà tuntun", "yo"),
    ("Ƙirƙiri babban fayil", "ha"),
    ("Mepụta folda ọhụrụ", "ig"),
    ("bude notepad", None),
])
def test_local_language_guess(text, expected):
    from app.agent.language import guess_language

    assert guess_language(text) == expected


async def test_thinking_is_kept_short_and_speech_prefers_flash_lite():
    bodies: list[tuple[str, dict]] = []

    def handler(request: httpx.Request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS)
        model = request.url.path.split("/models/")[1].split(":")[0]
        bodies.append((model, json.loads(request.content)))
        text = "{\"language\":\"en\",\"text\":\"open notepad\"}"
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})

    p = GeminiProvider("AIzaTest", httpx.AsyncClient(transport=httpx.MockTransport(handler)), QuotaTracker())
    await p.complete("s", "u", json_mode=True)
    t = await p.transcribe(b"RIFF" + b"\0" * 40000, "audio/wav", None)
    assert bodies[0][1]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
    assert bodies[1][0] == "gemini-3.5-flash-lite"
    assert bodies[1][1]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "minimal"}
    assert t.text == "open notepad"


async def test_a_model_that_rejects_the_thinking_setting_is_retried_plainly():
    seen: list[bool] = []

    def handler(request: httpx.Request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS)
        has = "thinkingConfig" in json.loads(request.content)["generationConfig"]
        seen.append(has)
        if has:
            return httpx.Response(400, json={"error": {"message": "Unknown name \"thinkingConfig\""}})
        return httpx.Response(200, json=OK)

    p = GeminiProvider("AIzaTest", httpx.AsyncClient(transport=httpx.MockTransport(handler)), QuotaTracker())
    await p.complete("s", "u", json_mode=True)
    await p.complete("s", "u", json_mode=True)
    assert seen == [True, False, False]
