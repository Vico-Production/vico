"""Speech chain Gemini -> Omnilingual -> Groq (English only), voice replies, tone marks."""

import base64
import json

import httpx
import pytest

from app.agent.language import safe_restoration, strip_diacritics
from app.contracts import VicoError
from app.providers.base import QuotaTracker
from app.providers.groq import GroqProvider
from app.providers.mock import MockProvider
from app.providers.registry import ProviderHub
from app.providers.speech_server import OmnilingualProvider, SpeechServer, VoiceProvider, _clean_url
from app.security.secret_store import MemorySecretBackend, SecretStore
from app.store.settings import Settings

pytestmark = pytest.mark.anyio
WAV = b"RIFF" + b"\0" * 2000


def server(handler, url="https://speech.example.org"):
    return SpeechServer(url, "tok-123", httpx.AsyncClient(transport=httpx.MockTransport(handler)), QuotaTracker())


async def test_omnilingual_sends_wav_in_memory_with_token():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(path=request.url.path, auth=request.headers["authorization"], lang=request.url.params.get("language"),
                    body=request.content, ctype=request.headers["content-type"])
        return httpx.Response(200, json={"text": " Ṣí Notepad ", "model": "omniASR_CTC_300M", "latency_ms": 900})

    t = await OmnilingualProvider(server(handler)).transcribe(WAV, "audio/wav", "yo")
    assert t.text == "Ṣí Notepad" and t.provider == "omnilingual" and t.model == "omniASR_CTC_300M"
    assert seen == {"path": "/v1/transcribe", "auth": "Bearer tok-123", "lang": "yo", "body": WAV,
                    "ctype": "audio/wav"}


async def test_omnilingual_errors_map_to_fallback_codes():
    def down(request):
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(VicoError) as exc:
        await OmnilingualProvider(server(down)).transcribe(WAV, "audio/wav", None)
    assert exc.value.code == "offline"

    def bad_token(request):
        return httpx.Response(401, json={"error": {}})

    with pytest.raises(VicoError) as exc:
        await OmnilingualProvider(server(bad_token)).transcribe(WAV, "audio/wav", None)
    assert exc.value.code == "provider_auth"


async def test_voice_reply_comes_back_as_base64_audio():
    def handler(request):
        assert json.loads(request.content) == {"text": "Mo ti ṣẹ̀dá fóldà", "language": "yo"}
        return httpx.Response(200, content=b"RIFFxxxx", headers={"content-type": "audio/wav", "x-latency-ms": "1500"})

    out = await VoiceProvider(server(handler)).speak("Mo ti ṣẹ̀dá fóldà", "yo")
    assert base64.b64decode(out["audio_b64"]) == b"RIFFxxxx" and out["latency_ms"] == 1500
    with pytest.raises(VicoError):
        await VoiceProvider(server(handler)).speak("x", "pcm")


@pytest.mark.parametrize("url,ok", [
    ("https://speech.example.org/", True),
    ("http://127.0.0.1:8088", True),
    ("http://speech.example.org", False),
    ("ftp://x", False),
])
def test_server_address_must_be_https(url, ok):
    if ok:
        assert _clean_url(url).startswith("http")
    else:
        with pytest.raises(VicoError):
            _clean_url(url)


def hub(overrides, **settings):
    return ProviderHub(SecretStore(MemorySecretBackend()), lambda: Settings(cloud_consent=True, **settings),
                       overrides=overrides)


async def test_stt_chain_is_gemini_then_omnilingual_then_groq():
    order = []

    class Fake(MockProvider):
        def __init__(self, name, fail=None):
            super().__init__()
            self.label, self.fail = name, fail

        async def transcribe(self, audio, mime, language):
            order.append(self.label)
            if self.fail:
                raise self.fail
            return await super().transcribe(audio, mime, language)

    resting = VicoError("rate_limited", "resting", retry_after_s=30)
    h = hub({"gemini": Fake("gemini", resting), "omnilingual": Fake("omnilingual"), "groq": Fake("groq")})
    await h.transcribe(WAV, "audio/wav", None)
    assert order == ["gemini", "omnilingual"]

    order.clear()
    h = hub({"gemini": Fake("gemini", resting), "omnilingual": Fake("omnilingual", VicoError("offline", "down")),
             "groq": Fake("groq")})
    await h.transcribe(WAV, "audio/wav", None)
    assert order == ["gemini", "omnilingual", "groq"]


async def test_groq_whisper_is_english_only():
    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "whisper-large-v3"}]})
        return httpx.Response(200, json={"text": "Bawo ni", "language": "yoruba"})

    groq = GroqProvider("gsk", httpx.AsyncClient(transport=httpx.MockTransport(handler)), QuotaTracker())
    with pytest.raises(VicoError):
        await groq.transcribe(WAV, "audio/wav", "yo")
    with pytest.raises(VicoError):  # auto-detected Yoruba is not accepted from Whisper
        await groq.transcribe(WAV, "audio/wav", None)


async def test_voice_needs_consent_and_a_server():
    h = ProviderHub(SecretStore(MemorySecretBackend()), lambda: Settings(cloud_consent=False))
    with pytest.raises(VicoError) as exc:
        await h.speak("hi", "en")
    assert exc.value.code == "consent_required"
    h = hub({})
    with pytest.raises(VicoError):
        await h.speak("hi", "en")
    assert not h.voice_ready()


def test_speech_server_built_from_settings_and_keyring():
    store = SecretStore(MemorySecretBackend())
    store.set("speech_server", "tok-123")
    h = ProviderHub(store, lambda: Settings(cloud_consent=True, speech_server_url="https://speech.example.org"))
    assert h.configured("omnilingual") and h.voice_ready()
    bad = ProviderHub(store, lambda: Settings(cloud_consent=True, speech_server_url="http://plain.example.org"))
    assert not bad.configured("omnilingual")


@pytest.mark.parametrize("original,restored,expected", [
    ("Se folda tuntun", "Ṣe fóldà tuntun", "Ṣe fóldà tuntun"),
    ("Mepee folda", "Mepee folda", None),  # nothing changed
    ("Se folda tuntun", "Ṣe fóldà tuntun kan", None),  # a word was added: rejected
    ("Se folda Demo", "Ṣe fóldà Dẹmo", "Ṣe fóldà Dẹmo"),  # only marks differ (the prompt asks to keep names)
    ("Kirkiri babban fayil", "Ƙirƙiri babban fayil", "Ƙirƙiri babban fayil"),
    ("open notepad", None, None),
])
def test_tone_mark_restoration_only_changes_marks(original, restored, expected):
    assert safe_restoration(original, restored) == expected


def test_strip_diacritics():
    assert strip_diacritics("Ṣẹ̀dá  Ƙirƙiri") == "seda kirkiri"


async def test_understand_returns_safe_restoration():
    reply = {"language": "yo", "restored": "Ṣí fóldà mi", "english": "Open my folder"}
    h = hub({"gemini": MockProvider(replies=[reply])})
    out = await h.understand("Si folda mi")
    assert out == {"language": "yo", "english": "Open my folder", "restored": "Ṣí fóldà mi", "control": None}
    tampered = {"language": "yo", "restored": "Pa gbogbo faili re", "english": "Delete all your files"}
    h = hub({"gemini": MockProvider(replies=[tampered])})
    assert (await h.understand("Si folda mi"))["restored"] == "Si folda mi"
