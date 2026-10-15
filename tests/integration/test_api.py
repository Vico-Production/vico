import time

import pytest
from fastapi.testclient import TestClient

from app.api import build_services, create_app
from app.providers.mock import MockProvider
from app.security.secret_store import MemorySecretBackend, SecretStore
from app.store.settings import SettingsPatch

TOKEN = "test-token-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(roots, platform, monkeypatch):
    root, ws = roots
    provider = MockProvider(replies=[
        {"kind": "tool_call", "tool": "create_folder", "arguments": {"path": "ApiDemo"}, "explanation": "x"},
        {"kind": "done", "message": "Made it."},
    ])
    services = build_services(secrets=SecretStore(MemorySecretBackend()), hub_overrides={"gemini": provider},
                              platform=platform)
    services.settings.update(SettingsPatch(workspace=str(ws), allowed_roots=[str(root)], cloud_consent=True))

    async def online():
        return True

    monkeypatch.setattr(services.hub, "online", online)
    with TestClient(create_app(TOKEN, services)) as c:
        yield c


def test_requests_without_token_are_rejected(client):
    assert client.get("/api/v1/health").status_code == 401
    r = client.get("/api/v1/health", headers={"Authorization": "Bearer wrong-token-xxxxxxxxxxxx"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


def test_foreign_origin_is_rejected(client):
    r = client.get("/api/v1/health", headers={**AUTH, "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_short_token_is_refused():
    with pytest.raises(ValueError):
        create_app("short")


def test_health_and_envelope(client):
    body = client.get("/api/v1/health", headers=AUTH).json()
    assert body["ok"] and body["api_version"] == "1"
    assert body["data"]["cloud_ready"] is True


def test_settings_round_trip_rejects_unknown_fields(client):
    r = client.put("/api/v1/settings", headers=AUTH, json={"require_approval": False})
    assert r.json()["data"]["require_approval"] is False
    bad = client.put("/api/v1/settings", headers=AUTH, json={"api_key": "x"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"


def test_secrets_are_write_only(client):
    r = client.put("/api/v1/secrets/groq", headers=AUTH, json={"api_key": "gsk_supersecretvalue123"})
    assert r.json()["data"] == {"provider": "groq", "configured": True}
    listing = client.get("/api/v1/secrets", headers=AUTH).text
    assert "supersecret" not in listing
    assert client.put("/api/v1/secrets/openai", headers=AUTH, json={"api_key": "x" * 20}).status_code == 404


def test_agent_run_over_http(client, roots):
    _, ws = roots
    run = client.post("/api/v1/agent/runs", headers=AUTH, json={"text": "make ApiDemo", "language": "en"}).json()
    run_id = run["data"]["id"]
    for _ in range(200):
        data = client.get(f"/api/v1/agent/runs/{run_id}", headers=AUTH).json()["data"]
        if data["state"] == "awaiting_approval":
            break
        time.sleep(0.02)
    assert data["pending_step_id"]
    r = client.post(f"/api/v1/agent/runs/{run_id}/decision", headers=AUTH,
                    json={"step_id": data["pending_step_id"], "approved": True})
    assert r.json()["ok"]
    for _ in range(200):
        data = client.get(f"/api/v1/agent/runs/{run_id}", headers=AUTH).json()["data"]
        if data["state"] == "completed":
            break
        time.sleep(0.02)
    assert data["state"] == "completed" and (ws / "ApiDemo").is_dir()
    history = client.get("/api/v1/history", headers=AUTH).json()["data"]
    assert history[0]["tool"] == "create_folder" and history[0]["verified"]
    assert client.delete("/api/v1/history", headers=AUTH).json()["data"]["deleted"] == 1


def test_invalid_language_rejected(client):
    r = client.post("/api/v1/agent/runs", headers=AUTH, json={"text": "x", "language": "fr"})
    assert r.status_code == 422


def test_current_run_endpoint(client):
    assert client.get("/api/v1/agent/runs/current", headers=AUTH).json()["data"] is None
    client.post("/api/v1/agent/runs", headers=AUTH, json={"text": "make ApiDemo"})
    current = client.get("/api/v1/agent/runs/current", headers=AUTH).json()["data"]
    assert current["text"] == "make ApiDemo"


def test_interpreter_endpoint_is_gone(client):
    r = client.post("/api/v1/interpreter/translate", headers=AUTH, json={"text": "hi", "source": "en", "target": "yo"})
    assert r.status_code in (404, 405)


def test_languages_are_labelled_untested_by_default(client):
    langs = client.get("/api/v1/languages", headers=AUTH).json()["data"]
    assert {lang["code"] for lang in langs} >= {"en", "yo", "ha", "ig"}
    assert all(lang["speech_label"] == "untested" for lang in langs)


def test_audio_stop_without_recording(client):
    r = client.post("/api/v1/audio/stop", headers=AUTH, json={"transcribe": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"


def test_reset_removes_codes_and_settings(client):
    client.put("/api/v1/secrets/gemini", headers=AUTH, json={"api_key": "AIzaSomethingSecret123"})
    client.put("/api/v1/settings", headers=AUTH, json={"onboarding_complete": True})
    assert client.post("/api/v1/reset", headers=AUTH).json()["data"]["reset"] is True
    assert client.get("/api/v1/secrets", headers=AUTH).json()["data"]["gemini"] is False
    assert client.get("/api/v1/settings", headers=AUTH).json()["data"]["onboarding_complete"] is False
