"""File tools. Every path goes through PathPolicy; every result is checked on disk."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import time
from pathlib import Path

from app.agent.schemas import (
    CreateFolderArgs,
    DeletePathArgs,
    FindFilesArgs,
    ListFolderArgs,
    MovePathArgs,
    OpenFileArgs,
    ReadTextArgs,
    SaveNoteArgs,
    SummarizeDocumentArgs,
)
from app.config import READ_TEXT_MAX_BYTES
from app.contracts import ErrorCode, VicoError
from app.security.paths import is_executable, is_text_file, sanitize_filename
from app.tools.base import Inspection, Risk, ToolContext, ToolResult, ToolSpec, fail

PAGE_SIZE = 50
SKIP_DIRS = {"node_modules", ".git", "__pycache__", "$recycle.bin", "appdata", ".cache", ".venv",
             "venv", "system volume information", "library"}
FIND_MAX_VISITS = 30_000
FIND_TIME_LIMIT_S = 6.0


def _untrusted(label: str, body: str) -> str:
    return f"<untrusted_content source=\"{label}\">\n{body}\n</untrusted_content>"


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"


# --- list_folder -------------------------------------------------------------------------
async def inspect_list(ctx: ToolContext, a: ListFolderArgs) -> Inspection:
    p = ctx.paths.resolve(a.path)
    return Inspection(effect=f"List the contents of {ctx.paths.display(p)}", targets=[str(p)])


async def list_folder(ctx: ToolContext, a: ListFolderArgs) -> ToolResult:
    folder = ctx.paths.resolve(a.path)
    if not folder.is_dir():
        return fail(f"{ctx.paths.display(folder)} is not a folder.")

    def scan() -> list[dict]:
        items = []
        with os.scandir(folder) as it:
            for entry in it:
                try:
                    is_dir = entry.is_dir()
                    size = 0 if is_dir else entry.stat().st_size
                except OSError:
                    continue
                items.append({"name": entry.name, "type": "folder" if is_dir else "file", "size": size})
        items.sort(key=lambda i: (i["type"] != "folder", str(i["name"]).casefold()))
        return items

    items = await asyncio.to_thread(scan)
    start = (a.page - 1) * PAGE_SIZE
    page = items[start:start + PAGE_SIZE]
    lines = [f"[{i['type']}] {i['name']}" + ("" if i["type"] == "folder" else f" ({_size(i['size'])})")
             for i in page]
    more = len(items) > start + PAGE_SIZE
    shown = f"{len(page)} of {len(items)} items"
    return ToolResult(
        ok=True,
        message=f"{ctx.paths.display(folder)}: {shown}",
        verified=True,
        verification="Read the folder listing from disk.",
        data={"path": str(folder), "items": page, "total": len(items), "page": a.page, "has_more": more},
        observation=_untrusted("folder listing", "\n".join(lines) or "(empty)")
        + (f"\n{shown}; ask for page {a.page + 1} to see more." if more else ""),
    )


# --- find_files --------------------------------------------------------------------------
async def inspect_find(ctx: ToolContext, a: FindFilesArgs) -> Inspection:
    p = ctx.paths.resolve(a.path)
    return Inspection(effect=f"Search for '{a.query}' in file names under {ctx.paths.display(p)}",
                      targets=[str(p)])


async def find_files(ctx: ToolContext, a: FindFilesArgs) -> ToolResult:
    root = ctx.paths.resolve(a.path)
    if not root.is_dir():
        return fail(f"{ctx.paths.display(root)} is not a folder.")
    terms = a.query.casefold().split()

    def walk() -> tuple[list[Path], bool]:
        found: list[Path] = []
        visits = 0
        deadline = time.monotonic() + FIND_TIME_LIMIT_S
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d.casefold() not in SKIP_DIRS and not d.startswith(".")]
            for name in dirnames + filenames:
                visits += 1
                if all(t in name.casefold() for t in terms):
                    found.append(Path(dirpath) / name)
                    if len(found) >= a.max_results:
                        return found, True
            if visits > FIND_MAX_VISITS or time.monotonic() > deadline or ctx.cancel.is_set():
                return found, True
        return found, False

    found, truncated = await asyncio.to_thread(walk)
    shown = [ctx.paths.display(p) for p in found]
    note = " (search stopped early; narrow the folder for more)" if truncated else ""
    return ToolResult(
        ok=True,
        message=f"Found {len(found)} match(es) for '{a.query}'{note}.",
        verified=True,
        verification="Matched names on disk.",
        data={"matches": [{"path": str(p), "display": d, "is_dir": p.is_dir()} for p, d in zip(found, shown, strict=True)]},
        observation=_untrusted("search results", "\n".join(shown) or "(no matches)") + note,
    )


# --- read_text ---------------------------------------------------------------------------
def _read_text_file(ctx: ToolContext, raw: str, max_chars: int) -> tuple[Path, str, bool]:
    path = ctx.paths.resolve(raw)
    if not path.is_file():
        raise VicoError(ErrorCode.NOT_FOUND, f"{ctx.paths.display(path)} is not a file.", status=404)
    if not is_text_file(path):
        raise VicoError(ErrorCode.UNSUPPORTED,
                        f"Vico can only read plain text files, not {path.suffix or 'this type'}.")
    size = path.stat().st_size
    if size > READ_TEXT_MAX_BYTES:
        raise VicoError(
            ErrorCode.VALIDATION_ERROR,
            f"{path.name} is {_size(size)}; the limit is {_size(READ_TEXT_MAX_BYTES)}. "
            "Choose a smaller file or excerpt.",
        )
    text = path.read_bytes().decode("utf-8", errors="replace")
    return path, text[:max_chars], len(text) > max_chars


async def inspect_read(ctx: ToolContext, a: ReadTextArgs) -> Inspection:
    p = ctx.paths.resolve(a.path)
    return Inspection(effect=f"Read the text of {ctx.paths.display(p)} so Vico can use it in this task",
                      targets=[str(p)])


async def read_text(ctx: ToolContext, a: ReadTextArgs) -> ToolResult:
    try:
        path, text, cut = await asyncio.to_thread(_read_text_file, ctx, a.path, a.max_chars)
    except VicoError as exc:
        return fail(exc.message)
    return ToolResult(
        ok=True,
        message=f"Read {len(text)} characters from {path.name}" + (" (truncated)." if cut else "."),
        verified=True,
        verification="Read from disk.",
        data={"path": str(path), "text": text, "truncated": cut},
        observation=_untrusted(path.name, text),
    )


# --- create_folder -----------------------------------------------------------------------
async def inspect_create(ctx: ToolContext, a: CreateFolderArgs) -> Inspection:
    p = ctx.paths.resolve_for_write(a.path)
    return Inspection(effect=f"Create the folder {ctx.paths.display(p)}", targets=[str(p)])


async def create_folder(ctx: ToolContext, a: CreateFolderArgs) -> ToolResult:
    path = ctx.paths.resolve_for_write(a.path)
    shown = ctx.paths.display(path)
    if path.is_dir():
        return ToolResult(ok=True, message=f"{shown} already exists.", verified=True,
                          verification="Folder exists on disk.", data={"path": str(path), "created": False},
                          observation=f"Folder already existed: {shown}")
    if path.exists():
        return fail(f"A file named {path.name} already exists there.")
    await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
    ok = path.is_dir()
    return ToolResult(ok=ok, message=f"Created {shown}." if ok else f"Could not create {shown}.",
                      verified=ok, verification="Folder exists on disk." if ok else "Folder not found after create.",
                      data={"path": str(path), "created": ok}, observation=f"Created folder {shown}")


# --- save_note ---------------------------------------------------------------------------
def _note_path(ctx: ToolContext, a: SaveNoteArgs) -> Path:
    folder = ctx.paths.resolve_for_write(a.folder)
    name = sanitize_filename(a.title) + f".{a.format}"
    return ctx.paths.resolve_for_write(str(folder / name))


async def inspect_note(ctx: ToolContext, a: SaveNoteArgs) -> Inspection:
    p = _note_path(ctx, a)
    preview = a.content[:120] + ("..." if len(a.content) > 120 else "")
    return Inspection(effect=f"Save a note to {ctx.paths.display(p)} containing: \"{preview}\"",
                      targets=[str(p)])


async def save_note(ctx: ToolContext, a: SaveNoteArgs) -> ToolResult:
    path = _note_path(ctx, a)
    shown = ctx.paths.display(path)
    if path.exists():
        return fail(f"{shown} already exists. Vico does not overwrite notes; use a different title.")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = a.content.encode("utf-8")
    await asyncio.to_thread(path.write_bytes, data)
    ok = path.is_file() and hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(data).digest()
    return ToolResult(ok=ok, message=f"Saved {shown}." if ok else f"Could not verify {shown}.", verified=ok,
                      verification="File content matches what was written." if ok else "Content mismatch.",
                      data={"path": str(path)}, observation=f"Saved note {shown}")


# --- move_path ---------------------------------------------------------------------------
def _move_paths(ctx: ToolContext, a: MovePathArgs) -> tuple[Path, Path]:
    src = ctx.paths.resolve_for_write(a.source)
    dst = ctx.paths.resolve_for_write(a.destination)
    if dst.is_dir():
        dst = ctx.paths.resolve_for_write(str(dst / src.name))
    return src, dst


async def inspect_move(ctx: ToolContext, a: MovePathArgs) -> Inspection:
    src, dst = _move_paths(ctx, a)
    return Inspection(effect=f"Move {ctx.paths.display(src)} to {ctx.paths.display(dst)}",
                      targets=[str(src), str(dst)])


async def move_path(ctx: ToolContext, a: MovePathArgs) -> ToolResult:
    src, dst = _move_paths(ctx, a)
    if not src.exists():
        return fail(f"{ctx.paths.display(src)} does not exist.")
    if dst.exists():
        return fail(f"{ctx.paths.display(dst)} already exists. Vico will not overwrite it.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(shutil.move, str(src), str(dst))
    ok = dst.exists() and not src.exists()
    msg = f"Moved to {ctx.paths.display(dst)}."
    return ToolResult(ok=ok, message=msg if ok else "Move could not be verified.", verified=ok,
                      verification="Destination exists and source is gone." if ok else "Unexpected state.",
                      data={"source": str(src), "destination": str(dst)}, observation=msg)


# --- delete_path -------------------------------------------------------------------------
async def inspect_delete(ctx: ToolContext, a: DeletePathArgs) -> Inspection:
    p = ctx.paths.resolve_for_write(a.path)
    kind = "folder and everything in it" if p.is_dir() else "file"
    return Inspection(effect=f"Delete the {kind} {ctx.paths.display(p)} (moved to the Recycle Bin/Trash)",
                      targets=[str(p)])


async def delete_path(ctx: ToolContext, a: DeletePathArgs) -> ToolResult:
    from send2trash import send2trash

    path = ctx.paths.resolve_for_write(a.path)
    shown = ctx.paths.display(path)
    if not path.exists():
        return fail(f"{shown} does not exist.")
    await asyncio.to_thread(send2trash, str(path))
    ok = not path.exists()
    return ToolResult(ok=ok, message=f"Moved {shown} to the Recycle Bin." if ok else f"{shown} is still there.",
                      verified=ok, verification="Path no longer exists." if ok else "Path still exists.",
                      data={"path": str(path)}, observation=f"Deleted {shown} (recoverable from the Recycle Bin)")


# --- open_file ---------------------------------------------------------------------------
def _open_target(ctx: ToolContext, raw: str) -> Path:
    path = ctx.paths.resolve(raw)
    if not path.exists():
        raise VicoError(ErrorCode.NOT_FOUND, f"{ctx.paths.display(path)} does not exist.", status=404)
    if path.is_file() and is_executable(path):
        raise VicoError(ErrorCode.POLICY_DENIED,
                        f"{path.name} is a program or script. Use open_app or run_command instead.", status=403)
    return path


async def inspect_open(ctx: ToolContext, a: OpenFileArgs) -> Inspection:
    p = _open_target(ctx, a.path)
    return Inspection(effect=f"Open {ctx.paths.display(p)} with its default app", targets=[str(p)])


async def open_file(ctx: ToolContext, a: OpenFileArgs) -> ToolResult:
    path = _open_target(ctx, a.path)
    try:
        before = {w.title for w in ctx.platform.list_windows()}
    except VicoError:
        before = None
    await asyncio.to_thread(ctx.platform.open_path, path)
    title = None
    if before is not None:
        title = await asyncio.to_thread(ctx.platform.wait_for_window, path.stem, before)
    shown = ctx.paths.display(path)
    if title:
        return ToolResult(ok=True, message=f"Opened {shown}.", verified=True,
                          verification=f"Window appeared: {title}", data={"path": str(path), "window": title},
                          observation=f"Opened {shown} in window '{title}'")
    return ToolResult(ok=True, message=f"Asked the system to open {shown}.", verified=False,
                      verification="The system accepted the request, but no matching window was seen.",
                      data={"path": str(path)}, observation=f"Requested opening {shown}; window not confirmed")


# --- summarize_document ------------------------------------------------------------------
async def inspect_summarize(ctx: ToolContext, a: SummarizeDocumentArgs) -> Inspection:
    p = ctx.paths.resolve(a.path)
    return Inspection(
        effect=f"Upload up to {a.max_chars} characters of {ctx.paths.display(p)} to the cloud provider "
               "and summarize it",
        targets=[str(p)], content_upload=True,
    )


async def summarize_document(ctx: ToolContext, a: SummarizeDocumentArgs) -> ToolResult:
    if ctx.summarizer is None:
        return fail("No cloud provider is set up for summaries.")
    try:
        path, text, cut = await asyncio.to_thread(_read_text_file, ctx, a.path, a.max_chars)
    except VicoError as exc:
        return fail(exc.message)
    summary = await ctx.summarizer(text, ctx.language)
    return ToolResult(ok=True, message=summary, verified=True,
                      verification=f"Summarized {len(text)} characters{' (truncated)' if cut else ''}.",
                      data={"path": str(path), "summary": summary},
                      observation=_untrusted(f"summary of {path.name}", summary))


def specs() -> list[ToolSpec]:
    return [
        ToolSpec("list_folder", "List files and folders in a folder (paginated).", ListFolderArgs,
                 Risk.AUTO, list_folder, inspect_list, "files"),
        ToolSpec("find_files", "Find files or folders whose names contain the query words.", FindFilesArgs,
                 Risk.AUTO, find_files, inspect_find, "files"),
        ToolSpec("read_text", "Read a plain text file (max 100 KB).", ReadTextArgs,
                 Risk.STANDARD, read_text, inspect_read, "files"),
        ToolSpec("create_folder", "Create a folder (no error if it exists).", CreateFolderArgs,
                 Risk.STANDARD, create_folder, inspect_create, "files"),
        ToolSpec("save_note", "Save a new .txt or .md note. Never overwrites.", SaveNoteArgs,
                 Risk.STANDARD, save_note, inspect_note, "files"),
        ToolSpec("move_path", "Move or rename a file or folder. Never overwrites.", MovePathArgs,
                 Risk.STANDARD, move_path, inspect_move, "files"),
        ToolSpec("delete_path", "Delete a file or folder to the Recycle Bin/Trash.", DeletePathArgs,
                 Risk.CONFIRM, delete_path, inspect_delete, "files"),
        ToolSpec("open_file", "Open a document, image, media file or folder with its default app.",
                 OpenFileArgs, Risk.STANDARD, open_file, inspect_open, "files"),
        ToolSpec("summarize_document", "Summarize a text file using the cloud provider.",
                 SummarizeDocumentArgs, Risk.CONFIRM, summarize_document, inspect_summarize, "files",
                 offline=False),
    ]
