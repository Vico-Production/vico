import pytest

from app.agent.schemas import (
    CreateFolderArgs,
    DeletePathArgs,
    FindFilesArgs,
    ListFolderArgs,
    MovePathArgs,
    OpenAppArgs,
    OpenFileArgs,
    ReadTextArgs,
    RunCommandArgs,
    SaveNoteArgs,
    SummarizeDocumentArgs,
    TypeTextArgs,
)
from app.contracts import VicoError
from app.tools import apps, desktop, files, system

pytestmark = pytest.mark.anyio


async def test_create_folder_creates_and_is_idempotent(ctx, roots):
    _, ws = roots
    first = await files.create_folder(ctx, CreateFolderArgs(path="Hackathon"))
    assert first.ok and first.verified and (ws / "Hackathon").is_dir()
    again = await files.create_folder(ctx, CreateFolderArgs(path="Hackathon"))
    assert again.ok and "already exists" in again.message


async def test_create_folder_fails_when_a_file_has_the_name(ctx, roots):
    _, ws = roots
    (ws / "taken").write_text("x")
    result = await files.create_folder(ctx, CreateFolderArgs(path="taken"))
    assert not result.ok


async def test_save_note_unicode_and_no_overwrite(ctx, roots):
    _, ws = roots
    args = SaveNoteArgs(title="Ìpàdé ọ̀la", content="Ẹ kú àárọ̀", folder=".")
    result = await files.save_note(ctx, args)
    assert result.ok and result.verified
    saved = ws / "Ìpàdé ọ̀la.txt"
    assert saved.read_text(encoding="utf-8") == "Ẹ kú àárọ̀"
    again = await files.save_note(ctx, args)
    assert not again.ok and "already exists" in again.message
    assert saved.read_text(encoding="utf-8") == "Ẹ kú àárọ̀"


async def test_list_folder_paginates(ctx, roots):
    _, ws = roots
    for i in range(60):
        (ws / f"f{i:02}.txt").write_text("x")
    (ws / "sub").mkdir()
    page1 = await files.list_folder(ctx, ListFolderArgs(path=".", page=1))
    assert page1.data["total"] == 61 and page1.data["has_more"]
    assert page1.data["items"][0]["name"] == "sub"
    page2 = await files.list_folder(ctx, ListFolderArgs(path=".", page=2))
    assert len(page2.data["items"]) == 11 and not page2.data["has_more"]


async def test_find_files_matches_case_insensitively(ctx, roots):
    _, ws = roots
    (ws / "Projects").mkdir()
    (ws / "Projects" / "Attendance_Notes.txt").write_text("x")
    (ws / "other.txt").write_text("x")
    result = await files.find_files(ctx, FindFilesArgs(query="attendance"))
    assert len(result.data["matches"]) == 1
    assert result.data["matches"][0]["path"].endswith("Attendance_Notes.txt")


async def test_read_text_limits(ctx, roots):
    _, ws = roots
    (ws / "small.md").write_text("# hello", encoding="utf-8")
    ok = await files.read_text(ctx, ReadTextArgs(path="small.md"))
    assert ok.ok and ok.data["text"] == "# hello"
    assert "<untrusted_content" in ok.observation
    (ws / "big.txt").write_bytes(b"a" * 120_000)
    big = await files.read_text(ctx, ReadTextArgs(path="big.txt"))
    assert not big.ok and "limit" in big.message
    (ws / "image.png").write_bytes(b"\x89PNG")
    binary = await files.read_text(ctx, ReadTextArgs(path="image.png"))
    assert not binary.ok


async def test_move_never_overwrites(ctx, roots):
    _, ws = roots
    (ws / "a.txt").write_text("a")
    (ws / "b.txt").write_text("b")
    clash = await files.move_path(ctx, MovePathArgs(source="a.txt", destination="b.txt"))
    assert not clash.ok and (ws / "b.txt").read_text() == "b"
    (ws / "dest").mkdir()
    moved = await files.move_path(ctx, MovePathArgs(source="a.txt", destination="dest"))
    assert moved.ok and moved.verified and (ws / "dest" / "a.txt").exists()


async def test_delete_goes_to_trash(ctx, roots, monkeypatch):
    _, ws = roots
    target = ws / "old.txt"
    target.write_text("x")
    trashed = []
    import send2trash

    monkeypatch.setattr(send2trash, "send2trash", lambda p: (trashed.append(p), target.unlink()))
    result = await files.delete_path(ctx, DeletePathArgs(path="old.txt"))
    assert result.ok and result.verified and trashed == [str(target.resolve())]


async def test_open_file_refuses_programs(ctx, roots):
    _, ws = roots
    (ws / "setup.exe").write_bytes(b"MZ")
    with pytest.raises(VicoError):
        await files.open_file(ctx, OpenFileArgs(path="setup.exe"))


async def test_open_file_verifies_window(ctx, roots, platform):
    _, ws = roots
    (ws / "report.txt").write_text("x")
    result = await files.open_file(ctx, OpenFileArgs(path="report.txt"))
    assert result.ok and result.verified and platform.opened


async def test_summarize_uses_provider(ctx, roots):
    _, ws = roots
    (ws / "doc.txt").write_text("Long text " * 50, encoding="utf-8")
    seen = {}

    async def summarizer(text, language):
        seen["text"] = text
        return "- short"

    ctx.summarizer = summarizer
    result = await files.summarize_document(ctx, SummarizeDocumentArgs(path="doc.txt", max_chars=200))
    assert result.ok and result.message == "- short" and len(seen["text"]) == 200


async def test_open_app_launches_known_app(ctx, platform):
    result = await apps.open_app(ctx, OpenAppArgs(name="notepad"))
    assert result.ok and result.verified and platform.launched == ["notepad"]


async def test_open_unknown_app(ctx):
    with pytest.raises(VicoError):
        await apps.open_app(ctx, OpenAppArgs(name="definitely-not-installed"))


async def test_type_text_refuses_password_fields(ctx, platform):
    platform.secret_focus = True
    result = await desktop.type_text(ctx, TypeTextArgs(text="hello"))
    assert not result.ok and platform.typed == []
    platform.secret_focus = False
    result = await desktop.type_text(ctx, TypeTextArgs(text="hello"))
    assert result.ok and platform.typed == ["hello"]


async def test_run_command_reports_exit_code(ctx, monkeypatch):
    import sys

    monkeypatch.setattr(ctx.platform, "shell_argv", lambda command, shell: [sys.executable, "-c", command])
    good = await system.run_command(ctx, RunCommandArgs(command="print('hi')"))
    assert good.ok and good.verified and "hi" in good.data["output"]
    bad = await system.run_command(ctx, RunCommandArgs(command="import sys; sys.exit(3)"))
    assert not bad.ok and bad.data["exit_code"] == 3
