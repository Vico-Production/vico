"""The self-hosted speech server, with fake engines (no models, no network)."""

import hashlib
import io
import sys
import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "speech_server"))

from vico_speech.artifacts import (  # noqa: E402
    ASR_ARTIFACTS,
    VOICE_ARTIFACTS,
    Artifact,
    ChecksumError,
    git_blob_sha1,
    verify,
)
from vico_speech.engines import BadAudio, decode_wav, encode_wav  # noqa: E402
from vico_speech.server import create_app  # noqa: E402

TOKEN = "speech-token-0123456789abcdefghij"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def wav_bytes(seconds: float, rate: int = 16_000, channels: int = 1) -> bytes:
    n = int(seconds * rate)
    samples = (np.sin(np.arange(n) / 9) * 8000).astype("<i2")
    if channels == 2:
        samples = np.repeat(samples, 2)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


class FakeRecognizer:
    model = "fake-asr"

    def __init__(self):
        self.calls = []

    def transcribe(self, samples, language):
        self.calls.append((samples.size, language))
        return "Ṣí Notepad"


class FakeVoice:
    model = "fake-voice"
    languages = ("en", "yo", "ha", "ig")

    def speak(self, text, language):
        return np.zeros(2400, dtype=np.float32), 24_000


@pytest.fixture
def client():
    recognizer = FakeRecognizer()
    app = create_app(TOKEN, recognizer, FakeVoice())
    with TestClient(app) as c:
        c.recognizer = recognizer
        yield c


def test_token_required(client):
    assert client.get("/v1/health").status_code == 401
    assert client.get("/v1/health", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/v1/health", headers=AUTH).json()["asr"]["ready"] is True


def test_short_tokens_refused():
    with pytest.raises(ValueError):
        create_app("short", None, None)


def test_transcribe_in_memory(client):
    r = client.post("/v1/transcribe?language=yo", headers={**AUTH, "Content-Type": "audio/wav"},
                    content=wav_bytes(1.5))
    assert r.status_code == 200
    assert r.json()["text"] == "Ṣí Notepad" and r.json()["audio_seconds"] == 1.5
    assert client.recognizer.calls == [(24_000, "yo")]


BAD_AUDIO = {
    "not-wav": lambda: b"not a wav",
    "44khz": lambda: wav_bytes(1.0, rate=44_100),
    "stereo": lambda: wav_bytes(1.0, channels=2),
    "too-long": lambda: wav_bytes(41.0),
}


@pytest.mark.parametrize("kind", list(BAD_AUDIO))
def test_bad_audio_is_rejected(client, kind):
    r = client.post("/v1/transcribe", headers=AUTH, content=BAD_AUDIO[kind]())
    assert r.status_code in (413, 422) and r.json()["error"]["code"] in ("bad_audio", "too_large")
    assert client.recognizer.calls == []


def test_unknown_language(client):
    r = client.post("/v1/transcribe?language=fr", headers=AUTH, content=wav_bytes(1.0))
    assert r.status_code == 422


def test_speak_returns_wav(client):
    r = client.post("/v1/speak", headers=AUTH, json={"text": "Mo ti ṣẹ̀dá fóldà", "language": "yo"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(r.content)) as w:
        assert w.getframerate() == 24_000
    assert client.post("/v1/speak", headers=AUTH, json={"text": "x", "language": "pcm"}).status_code == 422


def test_disabled_engines():
    with TestClient(create_app(TOKEN, None, None)) as c:
        assert c.post("/v1/transcribe", headers=AUTH, content=wav_bytes(1)).status_code == 503
        assert c.post("/v1/speak", headers=AUTH, json={"text": "x", "language": "en"}).status_code == 503


def test_wav_round_trip():
    samples = decode_wav(wav_bytes(0.5))
    assert samples.dtype == np.float32 and samples.size == 8000
    with pytest.raises(BadAudio):
        decode_wav(wav_bytes(0.05))
    assert encode_wav(samples, 16_000)[:4] == b"RIFF"


def test_checksum_verification(tmp_path):
    good = tmp_path / "model.bin"
    good.write_bytes(b"vico" * 100)
    artifact = Artifact(repo="r", revision="c", filename="model.bin", size=400,
                        sha256=hashlib.sha256(b"vico" * 100).hexdigest())
    verify(artifact, good)
    bad = Artifact(repo="r", revision="c", filename="model.bin", size=400, sha256="0" * 64)
    with pytest.raises(ChecksumError):
        verify(bad, good)
    assert not good.exists()  # a file that fails verification is deleted


def test_git_blob_sha1_matches_git(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_bytes(b"hello\n")
    assert git_blob_sha1(f) == "ce013625030ba8dba906f756967f9e9ca394464a"  # `git hash-object`


def test_every_pinned_artifact_has_a_checksum_and_revision():
    for a in (*ASR_ARTIFACTS, *VOICE_ARTIFACTS):
        assert len(a.revision) == 40 and (a.sha256 or a.git_sha1) and a.size > 0
        assert a.license in ("Apache-2.0", "MIT")
