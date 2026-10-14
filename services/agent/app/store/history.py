"""Minimal action history. Never stores raw audio, document content, prompts or raw transcripts."""

from __future__ import annotations

from datetime import UTC, datetime

from app.contracts import StrictModel
from app.security.redaction import redact_text
from app.store.db import Database


class HistoryEntry(StrictModel):
    id: int
    created_at: str
    language: str
    summary: str
    tool: str | None
    approval: str
    outcome: str
    verified: bool
    detail: str | None


class HistoryRepository:
    def __init__(self, db: Database):
        self.db = db

    def add(
        self,
        *,
        language: str,
        summary: str,
        tool: str | None,
        approval: str,
        outcome: str,
        verified: bool,
        detail: str | None = None,
    ) -> int:
        cur = self.db.execute(
            "INSERT INTO history(created_at, language, summary, tool, approval, outcome, verified, detail) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(UTC).isoformat(timespec="seconds"),
                language,
                redact_text(summary)[:300],
                tool,
                approval,
                outcome,
                int(verified),
                redact_text(detail)[:500] if detail else None,
            ),
        )
        return int(cur.lastrowid or 0)

    def list(self, limit: int = 100) -> list[HistoryEntry]:
        rows = self.db.execute(
            "SELECT * FROM history ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),)
        ).fetchall()
        return [HistoryEntry(**{**dict(r), "verified": bool(r["verified"])}) for r in rows]

    def clear(self) -> int:
        cur = self.db.execute("DELETE FROM history")
        return cur.rowcount
