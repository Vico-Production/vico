import pytest

from app.agent.offline_parser import parse_offline


@pytest.mark.parametrize("text,tool,args", [
    ("create folder Demo", "create_folder", {"path": "Demo"}),
    ("Create a folder called \"Hackathon 2026\"", "create_folder", {"path": "Hackathon 2026"}),
    ("make a new folder named Demo on my desktop", "create_folder", {"path": "~/Desktop/Demo"}),
    ("find attendance", "find_files", {"query": "attendance"}),
    ("search for project notes", "find_files", {"query": "project notes"}),
    ("open notepad", "open_app", {"name": "notepad"}),
    ("open calc", "open_app", {"name": "calculator"}),
    ("open attendance_notes.txt", "open_file", {"path": "attendance_notes.txt"}),
    ("show files", "list_folder", {"path": "."}),
    ("list files in Hackathon", "list_folder", {"path": "Hackathon"}),
    ("show my files on the desktop", "list_folder", {"path": "~/Desktop"}),
    ("save note Ideas: buy more data", "save_note", {"title": "Ideas", "content": "buy more data"}),
])
def test_commands(text, tool, args):
    plan = parse_offline(text)
    assert plan is not None
    assert plan.tool == tool
    assert plan.arguments == args


@pytest.mark.parametrize("text", ["", "what is the weather", "ṣí fóldà tuntun", "delete everything"])
def test_unknown_commands_return_none(text):
    assert parse_offline(text) is None
