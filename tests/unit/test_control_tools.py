import pytest
from PIL import Image

import app.tools.control as control
from app.platform.linux import ydotool_keys
from app.tools import build_registry

pytestmark = pytest.mark.anyio


def test_the_new_tools_are_registered():
    names = set(build_registry().names())
    assert {"set_volume", "set_brightness", "media_key", "clipboard_get", "clipboard_set", "screenshot",
            "compose_email", "click_at", "scroll", "look_at_screen", "click_on_screen", "browser_upload"} <= names


def test_arguments_are_checked():
    with pytest.raises(ValueError):
        control.VolumeArgs(action="set")  # set needs a percent
    with pytest.raises(ValueError):
        control.ScreenshotArgs(area="region", x=1)
    assert control.VolumeArgs(action="up").percent is None


def test_wayland_key_chords():
    assert ydotool_keys("ctrl+c") == ["29:1", "46:1", "46:0", "29:0"]
    assert ydotool_keys("enter") == ["28:1", "28:0"]


async def test_screenshot_crops_and_saves(ctx, monkeypatch, tmp_path):
    screen = Image.new("RGB", (1000, 600), "white")
    monkeypatch.setattr(control, "grab_screen", lambda: screen.copy())
    monkeypatch.setattr(control, "screenshots_dir", lambda: tmp_path)
    r = await control.screenshot(ctx, control.ScreenshotArgs(area="top_half", name="half"))
    with Image.open(tmp_path / "half.png") as img:
        assert img.size == (1000, 300)
    r = await control.screenshot(ctx, control.ScreenshotArgs(area="region", x=100, y=50, width=200, height=80))
    with Image.open(r.data["path"]) as img:
        assert img.size == (200, 80)


async def test_click_on_screen_clicks_the_centre_of_what_it_sees(ctx, monkeypatch):
    screen = Image.new("RGB", (2000, 1000), "white")
    monkeypatch.setattr(control, "grab_screen", lambda: screen.copy())
    clicks = []
    monkeypatch.setattr(control, "click_at_now", lambda a: clicks.append((a.x, a.y)))

    async def vision(image, question):
        assert "Subscribe" in question
        return '{"found": true, "box_2d": [500, 400, 600, 600], "label": "Subscribe"}'

    ctx.vision = vision
    r = await control.click_on_screen(ctx, control.ClickOnScreenArgs(target="the Subscribe button"))
    assert r.ok and clicks == [(1000, 550)]  # centre of the box, in real screen pixels


async def test_click_on_screen_never_presses_payment_or_ambiguous_things(ctx, monkeypatch):
    monkeypatch.setattr(control, "grab_screen", lambda: Image.new("RGB", (100, 100)))
    clicks = []
    monkeypatch.setattr(control, "click_at_now", lambda a: clicks.append(a))

    async def pay(image, question):
        return '{"found": true, "box_2d": [0, 0, 10, 10], "label": "Pay now"}'

    async def many(image, question):
        return '{"found": true, "box_2d": [0, 0, 10, 10], "label": "OK", "ambiguous": true}'

    ctx.vision = pay
    assert not (await control.click_on_screen(ctx, control.ClickOnScreenArgs(target="the blue button"))).ok
    ctx.vision = many
    assert not (await control.click_on_screen(ctx, control.ClickOnScreenArgs(target="OK"))).ok
    assert clicks == []
