"""SQLite connection and migrations."""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

log = logging.getLogger(__name__)

MIGRATIONS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        language TEXT NOT NULL,
        summary TEXT NOT NULL,
        tool TEXT,
        approval TEXT NOT NULL,
        outcome TEXT NOT NULL,
        verified INTEGER NOT NULL DEFAULT 0,
        detail TEXT
    );
    """,
]


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.conn = self._open()

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        try:
            conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError:
            # A corrupt database must not stop the app from starting. Keep the old file for inspection.
            conn.close()
            backup = self.path.with_suffix(".corrupt")
            log.error("database corrupt; moving to %s", backup.name)
            self.path.replace(backup)
            conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        self._migrate(conn)
        return conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for index, script in enumerate(MIGRATIONS[version:], start=version + 1):
            conn.executescript(script)
            conn.execute(f"PRAGMA user_version = {int(index)}")

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, params)

    def close(self) -> None:
        with self._lock:
            self.conn.close()
