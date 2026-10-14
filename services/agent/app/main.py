"""Sidecar entry point.

Started by the Tauri shell with VICO_TOKEN set. Binds to 127.0.0.1 on a free port and
prints `VICO_READY port=<port>` once listening. Exits when stdin closes (the parent
app went away), so a crashed shell never leaves the sidecar running.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading

import uvicorn

from app.api import create_app
from app.config import data_dir
from app.security.redaction import redact_text

HOST = "127.0.0.1"


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def _configure_logging() -> None:
    handler = logging.FileHandler(data_dir() / "vico-agent.log", encoding="utf-8")
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(RedactingFormatter("%(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler, stream])
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _free_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((HOST, 0))
    return sock


def _watch_parent(server: uvicorn.Server) -> None:
    """Stop when the parent closes our stdin."""
    try:
        while sys.stdin.read(1):
            pass
    except (OSError, ValueError):
        pass
    server.should_exit = True


def main() -> None:
    token = os.environ.pop("VICO_TOKEN", "")
    if len(token) < 16:
        print("VICO_TOKEN must be set by the Vico app", file=sys.stderr)
        sys.exit(2)
    _configure_logging()
    sock = _free_socket()
    port = sock.getsockname()[1]
    config = uvicorn.Config(create_app(token), log_config=None, access_log=False, lifespan="on")
    server = uvicorn.Server(config)

    original_startup = server.startup

    async def startup(sockets=None):
        await original_startup(sockets=sockets)
        print(f"VICO_READY port={port}", flush=True)

    server.startup = startup  # type: ignore[method-assign]
    if os.environ.get("VICO_WATCH_STDIN", "1") == "1":
        threading.Thread(target=_watch_parent, args=(server,), daemon=True).start()
    server.run(sockets=[sock])


if __name__ == "__main__":
    main()
