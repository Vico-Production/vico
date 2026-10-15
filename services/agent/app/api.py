"""HTTP API for the desktop shell. Bound to 127.0.0.1 and protected by a per-launch token."""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field
from starlette.middleware.base import BaseHTTPMiddleware

from app.agent.orchestrator import Orchestrator
from app.audio.recorder import Recorder
from app.config import MAX_TEXT_INPUT_CHARS, VERSION, data_dir
from app.contracts import API_PREFIX, ErrorCode, Language, StrictModel, VicoError, fail, ok
from app.interpreter.languages import capabilities
from app.platform import get_platform
from app.platform.base import PlatformAdapter
from app.providers.registry import SECRET_NAMES, ProviderHub
from app.providers.speech_server import _clean_url
from app.security.secret_store import SecretStore
from app.store.db import Database
from app.store.history import HistoryRepository
from app.store.settings import SettingsPatch, SettingsRepository
from app.tools import build_registry
from app.tools.browser import BrowserController

log = logging.getLogger(__name__)
ALLOWED_ORIGINS = {"tauri://localhost", "http://tauri.localhost", "https://tauri.localhost",
                   "http://localhost:1420", "http://127.0.0.1:1420"}


# --- request bodies --------------------------------------------------------------------
class RunRequest(StrictModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_INPUT_CHARS)
    language: Language | None = None  # None: detect from the request
    original: str | None = Field(default=None, max_length=MAX_TEXT_INPUT_CHARS)


class DecisionRequest(StrictModel):
    step_id: str = Field(min_length=1, max_length=40)
    approved: bool
    confirm: bool = False


class ReplyRequest(StrictModel):
    answer: str = Field(min_length=1, max_length=MAX_TEXT_INPUT_CHARS)


class SecretRequest(StrictModel):
    api_key: str = Field(min_length=8, max_length=400)


class SpeakRequest(StrictModel):
    text: str = Field(min_length=1, max_length=600)
    language: Language


class AudioStartRequest(StrictModel):
    language: Language | None = None  # None: detect from the speech


class AudioStopRequest(StrictModel):
    transcribe: bool = True


@dataclass
class Services:
    db: Database
    settings: SettingsRepository
    history: HistoryRepository
    secrets: SecretStore
    hub: ProviderHub
    orchestrator: Orchestrator
    recorder: Recorder
    browser: BrowserController | None
    platform: PlatformAdapter


def build_services(*, secrets: SecretStore | None = None, hub_overrides: dict[str, Any] | None = None,
                   platform: PlatformAdapter | None = None, recorder: Recorder | None = None,
                   browser: BrowserController | None = None, approval_timeout_s: float | None = None) -> Services:
    db = Database(data_dir() / "vico.db")
    settings = SettingsRepository(db)
    history = HistoryRepository(db)
    secrets = secrets or SecretStore()
    hub = ProviderHub(secrets, settings.load, overrides=hub_overrides)
    platform = platform or get_platform()
    if browser is None:
        browser = BrowserController(data_dir() / "browser-profile", settings.load().browser_channel)
    kwargs = {"approval_timeout_s": approval_timeout_s} if approval_timeout_s else {}
    orchestrator = Orchestrator(registry=build_registry(), hub=hub, settings=settings, history=history,
                                platform=platform, browser=browser, **kwargs)
    return Services(db, settings, history, secrets, hub, orchestrator, recorder or Recorder(), browser, platform)


class TokenMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str):
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin not in ALLOWED_ORIGINS:
            return JSONResponse(fail(ErrorCode.UNAUTHORIZED, "Origin not allowed."), status_code=403)
        auth = request.headers.get("authorization", "")
        supplied = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
        if not supplied or not hmac.compare_digest(supplied, self.token):
            return JSONResponse(fail(ErrorCode.UNAUTHORIZED, "Missing or invalid launch token."), status_code=401)
        return await call_next(request)


def create_app(token: str, services: Services | None = None) -> FastAPI:
    if not token or len(token) < 16:
        raise ValueError("a launch token of at least 16 characters is required")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = services or build_services()
        app.state.background = set()
        warm = asyncio.create_task(app.state.services.hub.warm())
        yield
        warm.cancel()
        s: Services = app.state.services
        s.recorder.cancel()
        await s.orchestrator.shutdown()
        if s.browser is not None:
            await s.browser.close()
        await s.hub.aclose()
        s.db.close()

    app = FastAPI(title="Vico agent", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.add_middleware(TokenMiddleware, token=token)
    if os.environ.get("VICO_DEV_CORS") == "1":
        # Browser-only UI development (vite on :1420). Never enabled in the packaged app.
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:1420", "http://127.0.0.1:1420"],
                           allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])

    @app.exception_handler(VicoError)
    async def vico_error(_: Request, exc: VicoError):
        return JSONResponse(fail(exc.code, exc.message, exc.retryable, exc.retry_after_s), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        msg = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:]) or 'body'}: {e['msg']}" for e in exc.errors())
        return JSONResponse(fail(ErrorCode.VALIDATION_ERROR, msg[:500]), status_code=422)

    @app.exception_handler(Exception)
    async def internal_error(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(fail(ErrorCode.INTERNAL, "Unexpected error inside Vico."), status_code=500)

    def svc(request: Request) -> Services:
        return request.app.state.services

    # --- health and settings -----------------------------------------------------------
    @app.get(f"{API_PREFIX}/health")
    async def health(request: Request):
        s = svc(request)
        settings = s.settings.load()
        online = await s.hub.online()
        return ok({
            "version": VERSION, "platform": sys.platform, "adapter": s.platform.name, "online": online,
            "cloud_ready": online and s.hub.has_role("llm"), "speech_ready": online and s.hub.has_role("stt"),
            "voice_ready": online and s.hub.voice_ready(),
            "cloud_consent": settings.cloud_consent, "providers": s.hub.status(),
            "recording": s.recorder.active, "browser_open": bool(s.browser and s.browser.is_open),
        })

    @app.get(f"{API_PREFIX}/settings")
    async def get_settings(request: Request):
        return ok(svc(request).settings.load().model_dump(mode="json"))

    @app.put(f"{API_PREFIX}/settings")
    async def put_settings(request: Request, patch: SettingsPatch):
        s = svc(request)
        if patch.speech_server_url:
            patch.speech_server_url = _clean_url(patch.speech_server_url)
        updated = s.settings.update(patch)
        if s.browser is not None:
            s.browser.channel = updated.browser_channel
        return ok(updated.model_dump(mode="json"))

    @app.get(f"{API_PREFIX}/languages")
    async def languages():
        return ok(capabilities())

    # --- secrets -------------------------------------------------------------------------
    def _provider(name: str) -> str:
        if name not in SECRET_NAMES:
            raise VicoError(ErrorCode.NOT_FOUND, f"Unknown provider {name}.", status=404)
        return name

    @app.get(f"{API_PREFIX}/secrets")
    async def list_secrets(request: Request):
        s = svc(request)
        return ok({name: s.secrets.has(name) for name in SECRET_NAMES})

    @app.put(f"{API_PREFIX}/secrets/{{name}}")
    async def put_secret(request: Request, name: str, body: SecretRequest):
        s = svc(request)
        try:
            s.secrets.set(_provider(name), body.api_key)
            task = asyncio.create_task(s.hub.warm())
            request.app.state.background.add(task)
            task.add_done_callback(request.app.state.background.discard)
        except VicoError:
            raise
        except Exception as exc:
            raise VicoError(ErrorCode.INTERNAL, "The system credential store is unavailable.", status=500) from exc
        return ok({"provider": name, "configured": True})

    @app.delete(f"{API_PREFIX}/secrets/{{name}}")
    async def delete_secret(request: Request, name: str):
        svc(request).secrets.delete(_provider(name))
        return ok({"provider": name, "configured": False})

    @app.post(f"{API_PREFIX}/voice/speak")
    async def speak(request: Request, body: SpeakRequest):
        return ok(await svc(request).hub.speak(body.text, body.language.value))

    @app.get(f"{API_PREFIX}/speech-server/health")
    async def speech_server_health(request: Request):
        return ok(await svc(request).hub.speech_server_health())

    @app.get(f"{API_PREFIX}/providers/{{name}}/models")
    async def provider_models(request: Request, name: str):
        s = svc(request)
        s.hub.require_consent()
        return ok({"provider": name, "models": await s.hub.list_models(_provider(name))})

    # --- agent ---------------------------------------------------------------------------
    @app.post(f"{API_PREFIX}/agent/runs")
    async def start_run(request: Request, body: RunRequest):
        language = body.language.value if body.language else None
        run = svc(request).orchestrator.start(body.text, language, body.original)
        return ok(run.public())

    @app.get(f"{API_PREFIX}/agent/runs/current")
    async def current_run(request: Request):
        """The most recent task, so every Vico surface can follow it."""
        runs = svc(request).orchestrator.runs.values()
        latest = max(runs, key=lambda r: r.created, default=None)
        return ok(latest.public() if latest else None)

    @app.get(f"{API_PREFIX}/agent/runs/{{run_id}}")
    async def get_run(request: Request, run_id: str):
        return ok(svc(request).orchestrator.get(run_id).public())

    @app.post(f"{API_PREFIX}/agent/runs/{{run_id}}/decision")
    async def decide(request: Request, run_id: str, body: DecisionRequest):
        run = svc(request).orchestrator.decide(run_id, body.step_id, body.approved, body.confirm)
        return ok(run.public())

    @app.post(f"{API_PREFIX}/agent/runs/{{run_id}}/reply")
    async def reply(request: Request, run_id: str, body: ReplyRequest):
        return ok(svc(request).orchestrator.reply(run_id, body.answer).public())

    @app.post(f"{API_PREFIX}/agent/runs/{{run_id}}/cancel")
    async def cancel(request: Request, run_id: str):
        return ok(svc(request).orchestrator.cancel(run_id).public())

    @app.get(f"{API_PREFIX}/agent/tools")
    async def tools(request: Request):
        registry = svc(request).orchestrator.registry
        return ok([{"name": n, "category": registry.get(n).category, "risk": registry.get(n).risk.value,
                    "description": registry.get(n).description} for n in registry.names()])

    # --- audio ---------------------------------------------------------------------------
    @app.post(f"{API_PREFIX}/audio/start")
    async def audio_start(request: Request, body: AudioStartRequest):
        s = svc(request)
        s.recorder.start(body.language.value if body.language else None)
        return ok(s.recorder.status())

    @app.get(f"{API_PREFIX}/audio/status")
    async def audio_status(request: Request):
        return ok(svc(request).recorder.status())

    @app.post(f"{API_PREFIX}/audio/stop")
    async def audio_stop(request: Request, body: AudioStopRequest):
        s = svc(request)
        language = s.recorder.language
        wav, seconds = s.recorder.stop()
        if not body.transcribe:
            return ok({"seconds": round(seconds, 1), "transcript": None})
        try:
            transcript = await s.hub.transcribe(wav, "audio/wav", language)
        finally:
            del wav  # audio is never kept after transcription
        return ok({"seconds": round(seconds, 1), "transcript": {
            "text": transcript.text, "language": transcript.language, "provider": transcript.provider,
            "model": transcript.model, "latency_ms": transcript.latency_ms, "confidence": transcript.confidence}})

    @app.post(f"{API_PREFIX}/audio/cancel")
    async def audio_cancel(request: Request):
        svc(request).recorder.cancel()
        return ok({"recording": False})

    # --- history -------------------------------------------------------------------------
    @app.get(f"{API_PREFIX}/history")
    async def history(request: Request, limit: int = 100):
        return ok([e.model_dump() for e in svc(request).history.list(limit)])

    @app.delete(f"{API_PREFIX}/history")
    async def clear_history(request: Request):
        return ok({"deleted": svc(request).history.clear()})

    @app.post(f"{API_PREFIX}/browser/close")
    async def close_browser(request: Request):
        s = svc(request)
        if s.browser is not None:
            await s.browser.close()
        return ok({"browser_open": False})

    return app
