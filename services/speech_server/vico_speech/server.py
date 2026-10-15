"""Vico Speech Server: Omnilingual ASR (listen) and YarnGPT (speak) over HTTP.

Run it on a Linux machine you control (for example a free Oracle Cloud server) behind
HTTPS. Every request needs the shared token. Audio is processed in memory only: nothing
received or generated is written to disk or logged.
"""

from __future__ import annotations

import hmac
import logging
import os
import time
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import BaseHTTPMiddleware

from vico_speech.engines import BadAudio, Recognizer, Voice, decode_wav, encode_wav

log = logging.getLogger("vico_speech")
MAX_AUDIO_BYTES = 2_000_000  # ~60 s of 16 kHz 16-bit mono; the model limit (40 s) is checked after decoding
LANGUAGES = {"en", "yo", "ha", "ig", "pcm"}
VERSION = "0.1.0"


class SpeakRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=600)
    language: str = Field(min_length=2, max_length=3)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


class TokenMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str):
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("authorization", "")
        supplied = auth[7:] if auth.startswith("Bearer ") else ""
        if not supplied or not hmac.compare_digest(supplied, self.token):
            return _error(401, "unauthorized", "Missing or wrong speech-server token.")
        return await call_next(request)


def create_app(token: str, recognizer: Recognizer | None, voice: Voice | None) -> FastAPI:
    if len(token) < 24:
        raise ValueError("VICO_SPEECH_TOKEN must be at least 24 characters")
    app = FastAPI(title="Vico Speech Server", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TokenMiddleware, token=token)

    @app.get("/v1/health")
    async def health() -> dict[str, Any]:
        return {
            "version": VERSION,
            "asr": {"ready": recognizer is not None, "model": getattr(recognizer, "model", None)},
            "voice": {"ready": voice is not None, "model": getattr(voice, "model", None),
                      "languages": list(getattr(voice, "languages", ()))},
        }

    @app.post("/v1/transcribe")
    async def transcribe(request: Request, language: str | None = Query(default=None, max_length=3)):
        if recognizer is None:
            return _error(503, "unavailable", "Speech recognition is not enabled on this server.")
        if language is not None and language not in LANGUAGES:
            return _error(422, "validation_error", "Unknown language.")
        body = await request.body()
        if len(body) > MAX_AUDIO_BYTES:
            return _error(413, "too_large", "The recording is too long.")
        try:
            samples = decode_wav(body)
        except BadAudio as exc:
            return _error(422, "bad_audio", str(exc))
        started = time.perf_counter()
        text = await run_in_threadpool(recognizer.transcribe, samples, language)
        latency = int((time.perf_counter() - started) * 1000)
        return {"text": text, "language": None, "model": recognizer.model, "latency_ms": latency,
                "audio_seconds": round(samples.size / 16_000, 2)}

    @app.post("/v1/speak")
    async def speak(body: SpeakRequest):
        if voice is None:
            return _error(503, "unavailable", "Voice replies are not enabled on this server.")
        if body.language not in voice.languages:
            return _error(422, "unsupported_language", f"No voice for '{body.language}'.")
        started = time.perf_counter()
        samples, rate = await run_in_threadpool(voice.speak, body.text, body.language)
        latency = int((time.perf_counter() - started) * 1000)
        return Response(encode_wav(samples, rate), media_type="audio/wav",
                        headers={"X-Latency-Ms": str(latency), "X-Model": voice.model})

    return app


def main() -> None:
    from pathlib import Path

    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.environ.get("VICO_SPEECH_TOKEN", "")
    models = Path(os.environ.get("VICO_SPEECH_MODELS", "/opt/vico-speech/models"))
    enable = {p.strip() for p in os.environ.get("VICO_SPEECH_ENABLE", "asr").split(",") if p.strip()}
    models.mkdir(parents=True, exist_ok=True)
    recognizer = voice = None
    if "asr" in enable:
        from vico_speech.engines import OmnilingualRecognizer

        recognizer = OmnilingualRecognizer(models)
        log.info("speech recognition ready (%s)", recognizer.model)
    if "voice" in enable:
        from vico_speech.engines import YarnVoice

        code = Path(os.environ.get("VICO_YARNGPT_CODE", "/opt/vico-speech/yarngpt"))
        voice = YarnVoice(models, code)
        log.info("voice ready (%s)", voice.model)
    host = os.environ.get("VICO_SPEECH_HOST", "127.0.0.1")
    port = int(os.environ.get("VICO_SPEECH_PORT", "8088"))
    uvicorn.run(create_app(token, recognizer, voice), host=host, port=port, access_log=False)


if __name__ == "__main__":
    main()
