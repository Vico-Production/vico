import os
import sys
from pathlib import Path

import pytest

from app.contracts import VicoError
from app.security.paths import PathPolicy, check_raw_path, is_executable, sanitize_filename


@pytest.fixture
def policy(roots):
    root, workspace = roots
    return PathPolicy(workspace, [root])


def test_relative_paths_resolve_inside_workspace(policy, roots):
    _, workspace = roots
    assert policy.resolve("Hackathon") == (workspace / "Hackathon").resolve()
    assert policy.resolve("a/b/../c") == (workspace / "a" / "c").resolve()


@pytest.mark.parametrize("raw", [
    "../../../outside",
    "..\\..\\..\\outside",
    "Hackathon/../../../../etc",
])
def test_traversal_outside_roots_is_rejected(policy, raw):
    with pytest.raises(VicoError) as exc:
        policy.resolve(raw)
    assert exc.value.code == "policy_denied"


def test_absolute_path_outside_roots_is_rejected(policy, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(VicoError):
        policy.resolve(str(outside))


@pytest.mark.parametrize("raw", [
    r"C:\Windows\System32",
    "/etc/passwd",
    r"\\server\share\file.txt",
    "//server/share",
    r"\\?\C:\Windows",
    "notes.txt:hidden",
    "CON",
    "folder/aux.txt",
    "LPT1.log",
    "trailing.",
    "space ",
    "file:///C:/Windows",
    "https://example.com",
    "bad\x00name",
    "",
    "x" * 401,
])
def test_dangerous_raw_paths_rejected(policy, raw):
    with pytest.raises(VicoError):
        policy.resolve(raw)


def test_windows_drive_paths_pass_raw_check():
    assert check_raw_path(r"C:\Users\me\Documents") == "C:/Users/me/Documents"


def test_tilde_resolves_to_home(tmp_path, monkeypatch):
    home = tmp_path / "userhome"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    policy = PathPolicy(home / "VicoDemo", [home])
    assert policy.resolve("~/Desktop/Demo") == (home / "Desktop" / "Demo").resolve()


def test_symlink_escape_is_rejected(policy, roots, tmp_path):
    _, workspace = roots
    outside = tmp_path / "secret"
    outside.mkdir()
    link = workspace / "link"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need extra privileges on this system")
    with pytest.raises(VicoError):
        policy.resolve("link/file.txt")


def test_writes_to_protected_roots_are_rejected(tmp_path):
    protected = tmp_path / "protected"
    protected.mkdir()
    policy = PathPolicy(tmp_path / "ws", [tmp_path], extra_protected=[protected])
    with pytest.raises(VicoError):
        policy.resolve_for_write(str(protected / "x.txt"))
    # reading is still allowed
    assert policy.resolve(str(protected / "x.txt"))


def test_cannot_write_an_allowed_root_itself(policy, roots):
    root, _ = roots
    with pytest.raises(VicoError):
        policy.resolve_for_write(str(root))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows system folders")
def test_windows_system_folder_is_protected():
    windir = os.environ["SystemRoot"]
    policy = PathPolicy(Path(windir).parent / "VicoDemoTest", [Path(windir).parent])
    with pytest.raises(VicoError):
        policy.resolve_for_write(str(Path(windir) / "vico.txt"))


def test_sanitize_filename_keeps_unicode_and_strips_bad_chars():
    assert sanitize_filename("Ìpàdé ọ̀la: notes?") == "Ìpàdé ọ̀la_ notes_"
    assert sanitize_filename("con") == "_con"
    assert sanitize_filename("...") == "note"
    assert sanitize_filename("a/b\\c") == "a_b_c"


def test_executable_detection():
    assert is_executable(Path("setup.EXE"))
    assert is_executable(Path("run.ps1"))
    assert not is_executable(Path("notes.txt"))
