"""Deterministic providers for tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.contracts import VicoError
from app.providers.base import Completion, Transcript


class MockProvider:
    name = "mock"

    def __init__(self, replies: list[Any] | None = None, transcript: str = "create folder Demo",
                 responder: Callable[[str, str], Any] | None = None):
        self.replies = list(replies or [])
        self.transcript = transcript
        self.responder = responder
        self.calls: list[tuple[str, str]] = []

    async def list_models(self) -> list[str]:
        return ["mock-model"]

    async def complete(self, system: str, user: str, *, json_mode: bool) -> Completion:
        self.calls.append((system, user))
        if self.responder is not None:
            reply = self.responder(system, user)
        elif self.replies:
            reply = self.replies.pop(0)
        else:
            reply = {"kind": "done", "message": "Finished."}
        if isinstance(reply, VicoError):
            raise reply
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return Completion(text=text, provider=self.name, model="mock-model", latency_ms=1)

    async def transcribe(self, audio: bytes, mime: str, language: str, hints: list[str] | None = None) -> Transcript:
        return Transcript(text=self.transcript, language=language, provider=self.name, model="mock-stt",
                          latency_ms=1)
