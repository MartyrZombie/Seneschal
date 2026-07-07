"""Third-party correspondence policy helpers (plan §6)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


@dataclass
class ThreadPolicy:
    thread_id: str
    principal_id: str
    correspondent_id: str
    authorized: bool
    messages_sent: int = 0
    last_activity: datetime | None = None
    expires_after_days_idle: int = 30
    rate_cap_per_day: int = 20


class CorrespondenceStore:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS threads (
        thread_id TEXT PRIMARY KEY,
        principal_id TEXT NOT NULL,
        correspondent_id TEXT NOT NULL,
        authorized INTEGER NOT NULL DEFAULT 0,
        messages_sent INTEGER NOT NULL DEFAULT 0,
        last_activity TEXT,
        created_at TEXT NOT NULL
    );
    """

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.executescript(self.SCHEMA)
        self.conn.commit()

    def authorize_thread(
        self, principal_id: str, correspondent_id: str, thread_id: str | None = None
    ) -> ThreadPolicy:
        tid = thread_id or str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO threads
            (thread_id, principal_id, correspondent_id, authorized, last_activity, created_at)
            VALUES (?, ?, ?, 1, ?, COALESCE((SELECT created_at FROM threads WHERE thread_id = ?), ?))
            """,
            (tid, principal_id, correspondent_id, now, tid, now),
        )
        self.conn.commit()
        return ThreadPolicy(
            thread_id=tid,
            principal_id=principal_id,
            correspondent_id=correspondent_id,
            authorized=True,
            last_activity=datetime.now(timezone.utc),
        )

    def can_send(self, thread_id: str) -> tuple[bool, str]:
        row = self.conn.execute(
            "SELECT authorized, messages_sent, last_activity, correspondent_id FROM threads WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        if not row:
            return False, "thread not found"
        if not row[0]:
            return False, "thread not authorized"
        if row[1] >= 20:
            return False, "daily rate cap exceeded"
        if row[2]:
            last = datetime.fromisoformat(row[2])
            if datetime.now(timezone.utc) - last > timedelta(days=30):
                return False, "thread expired"
        return True, "ok"

    def record_send(self, thread_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE threads SET messages_sent = messages_sent + 1, last_activity = ? WHERE thread_id = ?",
            (now, thread_id),
        )
        self.conn.commit()
