import pytest
from pydantic import ValidationError

from app.agent.schemas import (
    CreateFolderArgs,
    KeyArgs,
    ToolCallPlan,
    UrlArgs,
    parse_plan,
)


def test_parse_valid_plans():
    assert isinstance(parse_plan({"kind": "tool_call", "tool": "create_folder",
                                  "arguments": {"path": "Demo"}, "explanation": "x"}), ToolCallPlan)
    assert parse_plan({"kind": "done", "message": "ok"}).kind == "done"
    assert parse_plan({"kind": "clarify", "question": "Which file?"}).kind == "clarify"
    assert parse_plan({"kind": "unsupported", "reason": "no"}).kind == "unsupported"


@pytest.mark.parametrize("raw", [
    None,
    [],
    "create_folder",
    {"kind": "shell", "command": "rm -rf /"},
    {"kind": "tool_call", "tool": "create_folder", "arguments": {}, "extra": 1},
    {"kind": "done"},
    {"tool": "create_folder"},
])
def test_invalid_plans_rejected(raw):
    with pytest.raises((ValueError, ValidationError)):
        parse_plan(raw)


def test_extra_tool_arguments_rejected():
    with pytest.raises(ValidationError):
        CreateFolderArgs.model_validate({"path": "Demo", "recursive": True})


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///C:/x", "ftp://x.com", "https://exa mple.com"])
def test_bad_urls_rejected(url):
    with pytest.raises(ValidationError):
        UrlArgs(url=url)


def test_bare_domains_get_https():
    assert UrlArgs(url="example.com").url == "https://example.com"


def test_key_names_are_restricted():
    assert KeyArgs(key="ctrl+s").key == "ctrl+s"
    with pytest.raises(ValidationError):
        KeyArgs(key="{ENTER}; rm")
