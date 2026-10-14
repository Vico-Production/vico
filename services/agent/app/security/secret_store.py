"""API keys in the OS credential store (Windows Credential Manager / Secret Service).

Keys never go to SQLite, logs, or the frontend. `VICO_<PROVIDER>_API_KEY` environment
variables are accepted as a developer fallback.
"""

from __future__ import annotations

import logging
import os

SERVICE = "vico-desktop"
log = logging.getLogger(__name__)


class SecretStore:
    def __init__(self, backend: object | None = None):
        if backend is None:
            import keyring

            backend = keyring
        self._kr = backend

    def get(self, provider: str) -> str | None:
        env = os.environ.get(f"VICO_{provider.upper()}_API_KEY")
        if env:
            return env
        try:
            return self._kr.get_password(SERVICE, provider)  # type: ignore[attr-defined]
        except Exception as exc:  # backend unavailable (e.g. headless Linux without Secret Service)
            log.warning("credential store unavailable: %s", type(exc).__name__)
            return None

    def set(self, provider: str, value: str) -> None:
        self._kr.set_password(SERVICE, provider, value.strip())  # type: ignore[attr-defined]

    def delete(self, provider: str) -> None:
        try:
            self._kr.delete_password(SERVICE, provider)  # type: ignore[attr-defined]
        except Exception:
            log.info("no stored key for %s", provider)

    def has(self, provider: str) -> bool:
        return bool(self.get(provider))


class MemorySecretBackend:
    """In-memory keyring stand-in for tests."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, user: str) -> str | None:
        return self.values.get((service, user))

    def set_password(self, service: str, user: str, value: str) -> None:
        self.values[(service, user)] = value

    def delete_password(self, service: str, user: str) -> None:
        self.values.pop((service, user), None)
