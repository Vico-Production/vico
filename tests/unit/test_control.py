import pytest

from app.agent.control import clean, greeting_language, parse, reply


@pytest.mark.parametrize("text,expected", [
    ("Vico wassup", {"action": "greet"}),
    ("vico how far", {"action": "greet"}),
    ("Hey Vico", {"action": "greet"}),
    ("Vico!", {"action": "greet"}),
    ("Báwo ni Vico", {"action": "greet"}),
    ("vico, don't go yet, I still need you", None),  # long and unusual: left to the AI
    ("don't go", {"action": "stay"}),
    ("Vico stay with me abeg", {"action": "stay"}),
    ("no comot", {"action": "stay"}),
    ("you can go", {"action": "go"}),
    ("Vico, thank you that's all", {"action": "go"}),
    ("move to the left", {"action": "move", "where": "left"}),
    ("go to the top right corner", {"action": "move", "where": "top-right"}),
    ("get out of my way", {"action": "move", "where": "away"}),
    ("put your label at the bottom", {"action": "move", "where": "bottom"}),
    ("move the file report.docx to Documents", None),
    ("go to bbc.com", None),
    ("wait for the page to load then click subscribe", None),
    ("open notepad", None),
    ("hello world.txt create it in my documents folder please now", None),
])
def test_parse(text, expected):
    assert parse(text) == expected


def test_greeting_language_and_reply():
    assert greeting_language("Báwo ni") == "yo" and greeting_language("sannu") == "ha"
    assert greeting_language("kedu") == "ig" and greeting_language("how far") == "pcm"
    assert reply({"action": "greet"}, "yo").startswith("Báwo ni!")
    assert reply({"action": "move", "where": "top-left"}, "en") == "Okay, moving to the top left."


def test_clean_rejects_odd_ai_output():
    assert clean({"action": "dance"}) is None and clean("stay") is None
    assert clean({"action": "move", "where": "moon"}) == {"action": "move", "where": "away"}



@pytest.mark.parametrize("text,value", [
    ("i want to hear your voice oya talk to me", "on"),
    ("Vico abeg make I hear your voice", "on"),
    ("read your answers out loud", "on"),
    ("I no need your voice again", "off"),
    ("just reply me in text", "off"),
])
def test_voice_switch_in_loose_wording(text, value):
    from app.agent.control import loose

    assert (parse(text) or loose(text)) == {"action": "voice", "value": value}


@pytest.mark.parametrize("text", ["I want to talk to my friend on WhatsApp, open it", "call mum", "talk to customer care",
                                  "say hello to John on Telegram", "make a folder called voice notes"])
def test_talking_as_part_of_a_task_is_never_a_voice_switch(text):
    from app.agent.control import loose

    assert parse(text) is None and loose(text) is None
