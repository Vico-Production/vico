"""User settings, persisted as JSON values in SQLite. Secrets never live here."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import Field

from app.config import DEFAULT_MAX_STEPS, default_workspace
from app.contracts import StrictModel
from app.store.db import Database

ProviderName = Literal["groq", "gemini", "none"]


class Settings(StrictModel):
    onboarding_complete: bool = False
    # The user accepted the disclosure that audio/text go to the configured cloud provider.
    cloud_consent: bool = False
    # Approval switch: on by default. Off lets ordinary steps run without asking.
    require_approval: bool = True
    # Sends/posts/submissions still ask even with the switch off, unless this is set.
    allow_send_without_approval: bool = False
    workspace: str = Field(default_factory=lambda: str(default_workspace()))
    allowed_roots: list[str] = Field(default_factory=lambda: ["~"])
    stt_provider: ProviderName = "gemini"
    llm_provider: ProviderName = "gemini"
    # When the first provider's free models are all resting, use the other provider's key
    # (only if the user added one). Disclosed when the key is added.
    fallback_consent: bool = True
    stt_model: str | None = None
    llm_model: str | None = None
    daily_request_budget: int = Field(default=500, ge=1, le=100_000)
    max_steps: int = Field(default=DEFAULT_MAX_STEPS, ge=1, le=40)
    browser_channel: Literal["auto", "msedge", "chrome", "chromium"] = "auto"
    # The user's own Vico Speech Server (Omnilingual ASR + YarnGPT voices); token in the keyring.
    speech_server_url: str | None = None
    # Speak answers aloud when a speech server with voices is set up.
    voice_replies: bool = True
    # Listen on this computer for "Hey Vico" (nothing heard while waiting leaves the computer).
    wake_word: bool = True


class SettingsPatch(StrictModel):
    onboarding_complete: bool | None = None
    cloud_consent: bool | None = None
    require_approval: bool | None = None
    allow_send_without_approval: bool | None = None
    workspace: str | None = Field(default=None, max_length=400)
    allowed_roots: list[str] | None = Field(default=None, max_length=20)
    stt_provider: ProviderName | None = None
    llm_provider: ProviderName | None = None
    fallback_consent: bool | None = None
    stt_model: str | None = Field(default=None, max_length=120)
    llm_model: str | None = Field(default=None, max_length=120)
    daily_request_budget: int | None = Field(default=None, ge=1, le=100_000)
    max_steps: int | None = Field(default=None, ge=1, le=40)
    browser_channel: Literal["auto", "msedge", "chrome", "chromium"] | None = None
    speech_server_url: str | None = Field(default=None, max_length=300)
    voice_replies: bool | None = None
    wake_word: bool | None = None


class SettingsRepository:
    def __init__(self, db: Database):
        self.db = db

    def load(self) -> Settings:
        rows = self.db.execute("SELECT key, value FROM settings").fetchall()
        stored = {}
        known = set(Settings.model_fields)
        for row in rows:
            if row["key"] in known:
                stored[row["key"]] = json.loads(row["value"])
        try:
            return Settings(**stored)
        except ValueError:
            return Settings()

    def update(self, patch: SettingsPatch) -> Settings:
        current = self.load()
        changes = patch.model_dump(exclude_unset=True)
        # Explicit nulls only clear the optional model overrides.
        changes = {k: v for k, v in changes.items()
                   if v is not None or k in ("stt_model", "llm_model", "speech_server_url")}
        merged = Settings(**{**current.model_dump(), **changes})
        for key, value in merged.model_dump(mode="json").items():
            self.db.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
        return merged

    def reset(self) -> Settings:
        """Forget every setting, so the next summon starts at first-run setup."""
        self.db.execute("DELETE FROM settings")
        return Settings()
