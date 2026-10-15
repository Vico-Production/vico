import json

import httpx
import pytest

from app.contracts import VicoError
from app.providers.base import QuotaTracker, parse_json_text, pick_model
from app.providers.gemini import GeminiProvider, choose_gemini_model
from app.providers.groq import GroqProvider
from app.providers.mock import MockProvider
from app.providers.registry import ProviderHub
from app.security.secret_store import MemorySecretBackend, SecretStore
from app.store.settings import Settings

pytestmark = pytest.mark.anyio


def client_for(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def groq(handler, **kw):
    return GroqProvider("gsk_test", client_for(handler), QuotaTracker(), **kw)


GROQ_MODELS = {"data": [{"id": "whisper-large-v3"}, {"id": "llama-guard-4"}, {"id": "llama-3.3-70b-versatile"}]}


async def test_groq_picks_models_from_live_list_and_transcribes():
    seen = {}

    def handler(request: httpx.Request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=GROQ_MODELS)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.content
        return httpx.Response(200, json={"text": " Open my folder ", "language": "english"})

    t = await groq(handler).transcribe(b"RIFF" + b"\0" * 1000, "audio/wav", "en")
    assert t.text == "Open my folder" and t.model == "whisper-large-v3" and t.confidence is None
    assert seen["auth"] == "Bearer gsk_test"
    assert b'name="language"\r\n\r\nen' in seen["body"]


@pytest.mark.parametrize("language", ["yo", "ha", "ig", "pcm"])
async def test_groq_whisper_is_not_used_for_nigerian_languages(language):
    bodies = []

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=GROQ_MODELS)
        bodies.append(request.content)
        return httpx.Response(200, json={"text": "ok"})

    with pytest.raises(VicoError) as exc:
        await groq(handler).transcribe(b"x" * 100, "audio/wav", language)
    assert exc.value.code == "provider_unavailable" and bodies == []  # no audio was sent


async def test_groq_chat_json_mode():
    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=GROQ_MODELS)
        body = json.loads(request.content)
        assert body["model"] == "llama-3.3-70b-versatile"
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"kind\":\"done\",\"message\":\"x\"}"}}]})

    c = await groq(handler).complete("sys", "user", json_mode=True)
    assert json.loads(c.text)["kind"] == "done"


@pytest.mark.parametrize("status,code", [(401, "provider_auth"), (429, "rate_limited"), (503, "provider_unavailable")])
async def test_error_mapping(status, code):
    def handler(request):
        return httpx.Response(status, headers={"retry-after": "7"}, json={"error": "x"})

    with pytest.raises(VicoError) as exc:
        await groq(handler, llm_model="m").complete("s", "u", json_mode=False)
    assert exc.value.code == code
    if status == 429:
        assert exc.value.retry_after_s == 7


async def test_rate_limit_blocks_next_request_until_retry_after():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "30"})

    p = groq(handler, llm_model="m")
    with pytest.raises(VicoError):
        await p.complete("s", "u", json_mode=False)
    first = len(calls)  # model list + the chosen model
    with pytest.raises(VicoError) as exc:
        await p.complete("s", "u", json_mode=False)
    assert exc.value.code == "rate_limited" and exc.value.retry_after_s > 20
    assert len(calls) == first  # the resting model is not called again


async def test_timeout_and_offline_mapping():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    def offline(request):
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(VicoError) as exc:
        await groq(timeout, llm_model="m").complete("s", "u", json_mode=False)
    assert exc.value.code == "timeout"
    with pytest.raises(VicoError) as exc:
        await groq(offline, llm_model="m").complete("s", "u", json_mode=False)
    assert exc.value.code == "offline"


async def test_daily_budget():
    quota = QuotaTracker(daily_budget=1)

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    p = GroqProvider("k", client_for(handler), quota, llm_model="m")
    await p.complete("s", "u", json_mode=False)
    with pytest.raises(VicoError) as exc:
        await p.complete("s", "u", json_mode=False)
    assert exc.value.code == "rate_limited"


async def test_gemini_generate_and_model_choice():
    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"models": [
                {"name": "models/gemini-x-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-x-flash-image", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/text-embedding", "supportedGenerationMethods": ["embedContent"]},
            ]})
        assert request.headers["x-goog-api-key"] == "AIzaTest"
        assert "key=" not in str(request.url)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{\"translation\": \"Hello\"}"}]}}]})

    p = GeminiProvider("AIzaTest", client_for(handler), QuotaTracker())
    c = await p.complete("s", "u", json_mode=True)
    assert c.model == "gemini-x-flash" and "Hello" in c.text


def test_model_pickers_only_return_listed_models():
    assert pick_model(["a", "whisper-large-v3"], ["whisper-large-v3"]) == "whisper-large-v3"
    assert pick_model(["a"], ["whisper"]) is None
    assert choose_gemini_model(["gemini-2-flash-preview", "gemini-1-flash"]) == "gemini-1-flash"
    assert choose_gemini_model(["gemini-pro"]) is None


def test_parse_json_text_tolerates_fence_only():
    assert parse_json_text("```json\n{\"a\": 1}\n```") == {"a": 1}
    with pytest.raises(VicoError):
        parse_json_text("Sure! Here is the plan: {")


def make_hub(settings: Settings, overrides=None, keys=None):
    backend = MemorySecretBackend()
    store = SecretStore(backend)
    for name, key in (keys or {}).items():
        store.set(name, key)
    return ProviderHub(store, lambda: settings, overrides=overrides)


async def test_hub_requires_consent():
    hub = make_hub(Settings(cloud_consent=False), overrides={"groq": MockProvider()})
    with pytest.raises(VicoError) as exc:
        await hub.complete("s", "u")
    assert exc.value.code == "consent_required"


async def test_hub_without_provider():
    hub = make_hub(Settings(cloud_consent=True))
    with pytest.raises(VicoError) as exc:
        await hub.complete("s", "u")
    assert exc.value.code == "provider_unavailable"


async def test_hub_fallback_only_with_consent():
    failing = MockProvider(replies=[VicoError("offline", "down")] * 3)
    backup = MockProvider(replies=["{\"translation\": \"Hi\"}"] * 2)
    hub = make_hub(Settings(cloud_consent=True, fallback_consent=False, llm_provider="groq"),
                   overrides={"groq": failing, "gemini": backup})
    with pytest.raises(VicoError):
        await hub.complete("s", "u")
    assert backup.calls == []
    hub = make_hub(Settings(cloud_consent=True, fallback_consent=True, llm_provider="groq"),
                   overrides={"groq": failing, "gemini": backup})
    result = await hub.translate("Bawo", "yo", "en")
    assert result["text"] == "Hi"


async def test_hub_does_not_fall_back_on_auth_errors():
    failing = MockProvider(replies=[VicoError("provider_auth", "bad key")])
    backup = MockProvider()
    hub = make_hub(Settings(cloud_consent=True, fallback_consent=True, llm_provider="groq"), overrides={"groq": failing, "gemini": backup})
    with pytest.raises(VicoError) as exc:
        await hub.complete("s", "u")
    assert exc.value.code == "provider_auth" and backup.calls == []


async def test_translate_same_language_is_free():
    hub = make_hub(Settings(cloud_consent=True), overrides={"groq": MockProvider()})
    assert (await hub.translate("hi", "en", "en"))["text"] == "hi"


def test_status_never_contains_keys():
    hub = make_hub(Settings(cloud_consent=True), keys={"groq": "gsk_secretvalue123456789"})
    assert "gsk_" not in json.dumps(hub.status())
    assert hub.status()["groq"]["configured"] is True
