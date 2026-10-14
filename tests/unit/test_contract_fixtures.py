"""The fixtures in tests/fixtures/contracts are also checked by the TypeScript tests."""

import json
from pathlib import Path

import pytest

from app.agent.orchestrator import Run, Step
from app.contracts import ApiError, Envelope
from app.store.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("*.json")))
def test_every_fixture_is_a_valid_envelope(name):
    env = Envelope[dict].model_validate(load(name))
    assert env.api_version == "1"
    assert env.ok == (env.error is None)


def test_settings_fixture_matches_model():
    data = load("settings.json")["data"]
    assert Settings.model_validate(data)
    assert set(data) == set(Settings.model_fields)


def test_run_fixture_has_current_shape():
    data = load("run_awaiting_approval.json")["data"]
    current = Run(id="x", text="t", language="en", original="t").public()
    assert set(data) == set(current)
    step = Step(id="s", tool="t", arguments={}, explanation="").public()
    assert set(data["steps"][0]) == set(step)


def test_error_fixture():
    ApiError.model_validate(load("error_policy_denied.json")["error"])
