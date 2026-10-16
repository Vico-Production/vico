import pytest

from app.agent.policy import Outcome, preflight
from app.tools import build_registry

pytestmark = pytest.mark.anyio


@pytest.fixture
def registry():
    return build_registry()


async def test_unknown_tool_is_denied(registry, ctx):
    pf = await preflight(registry, ctx, "format_disk", {})
    assert pf.decision.outcome is Outcome.DENIED
    assert pf.spec is None


async def test_invalid_arguments_are_denied_and_fixable(registry, ctx):
    pf = await preflight(registry, ctx, "create_folder", {"path": "Demo", "mode": "777"})
    assert pf.decision.outcome is Outcome.DENIED
    assert pf.decision.fixable


async def test_path_escape_is_denied(registry, ctx):
    pf = await preflight(registry, ctx, "create_folder", {"path": "../../../../Windows/evil"})
    assert pf.decision.outcome is Outcome.DENIED
    assert not pf.decision.fixable


async def test_metadata_reads_run_without_approval(registry, ctx):
    pf = await preflight(registry, ctx, "list_folder", {"path": "."})
    assert pf.decision.outcome is Outcome.ALLOWED


async def test_writes_need_approval_when_switch_on(registry, ctx):
    pf = await preflight(registry, ctx, "create_folder", {"path": "Demo"})
    assert pf.decision.outcome is Outcome.APPROVAL_REQUIRED
    assert "Demo" in pf.decision.effect


async def test_writes_run_when_switch_off(registry, ctx):
    ctx.settings.require_approval = False
    pf = await preflight(registry, ctx, "create_folder", {"path": "Demo"})
    assert pf.decision.outcome is Outcome.ALLOWED


@pytest.mark.parametrize("tool,args", [
    ("run_command", {"command": "echo hi"}),
    ("summarize_document", {"path": "notes.txt"}),
    ("delete_path", {"path": "notes.txt"}),
])
async def test_risky_tools_ask_only_while_asking_is_on(registry, ctx, roots, tool, args):
    _, workspace = roots
    (workspace / "notes.txt").write_text("hello", encoding="utf-8")
    ctx.settings.require_approval = True
    assert (await preflight(registry, ctx, tool, args)).decision.outcome is Outcome.CONFIRM_REQUIRED
    ctx.settings.require_approval = False  # the user switched asking off: nothing is asked
    assert (await preflight(registry, ctx, tool, args)).decision.outcome is Outcome.ALLOWED
    ctx.tainted = True  # ...except right after reading a page or file, which could hijack Vico
    assert (await preflight(registry, ctx, tool, args)).decision.outcome is Outcome.CONFIRM_REQUIRED


async def test_ordinary_steps_never_ask_when_asking_is_off_even_after_reading(registry, ctx):
    ctx.settings.require_approval = False
    ctx.tainted = True
    assert (await preflight(registry, ctx, "create_folder", {"path": "New"})).decision.outcome is Outcome.ALLOWED


async def test_typing_card_number_is_denied(registry, ctx):
    pf = await preflight(registry, ctx, "type_text", {"text": "4111 1111 1111 1111"})
    assert pf.decision.outcome is Outcome.DENIED


async def test_clicking_payment_button_is_denied(registry, ctx):
    pf = await preflight(registry, ctx, "click_element", {"window": "Shop", "name": "Place order"})
    import sys
    if sys.platform != "win32":
        assert pf.decision.outcome is Outcome.DENIED  # tool unavailable off Windows
    else:
        assert pf.decision.outcome is Outcome.DENIED
        assert "payment" in pf.decision.reason


async def test_send_buttons_need_confirmation_unless_allowed(registry, ctx):
    import sys
    if sys.platform != "win32":
        pytest.skip("click_element is Windows-only")
    pf = await preflight(registry, ctx, "click_element", {"window": "Mail", "name": "Send"})
    assert pf.decision.outcome is Outcome.CONFIRM_REQUIRED
    ctx.settings.allow_send_without_approval = True
    ctx.settings.require_approval = False
    pf = await preflight(registry, ctx, "click_element", {"window": "Mail", "name": "Send"})
    assert pf.decision.outcome is Outcome.ALLOWED


async def test_browser_tools_need_an_open_page(registry, ctx):
    pf = await preflight(registry, ctx, "browser_click", {"target": "Search"})
    assert pf.decision.outcome is Outcome.DENIED
