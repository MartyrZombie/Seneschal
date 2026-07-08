"""Semantic/profile memory — durable distilled facts in SQLite (plan §9)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from seneschal.common.config import HarnessSettings, load_settings


class SemanticMemory:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS facts (
        id TEXT PRIMARY KEY,
        principal_id TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        created_at TEXT NOT NULL,
        archived_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_facts_principal_key ON facts(principal_id, key);
    """

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.executescript(self.SCHEMA)
        self.conn.commit()

    def upsert(self, principal_id: str, key: str, value: str) -> str:
        """New fact wins; old fact archived with timestamp."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE facts SET archived_at = ? WHERE principal_id = ? AND key = ? AND archived_at IS NULL",
            (now, principal_id, key),
        )
        fact_id = str(uuid4())
        self.conn.execute(
            "INSERT INTO facts (id, principal_id, key, value, created_at) VALUES (?, ?, ?, ?, ?)",
            (fact_id, principal_id, key, value, now),
        )
        self.conn.commit()
        return fact_id

    def get(self, principal_id: str, key: str) -> str | None:
        row = self.conn.execute(
            """
            SELECT value FROM facts
            WHERE principal_id = ? AND key = ? AND archived_at IS NULL
            ORDER BY created_at DESC LIMIT 1
            """,
            (principal_id, key),
        ).fetchone()
        return row[0] if row else None

    def forget_topic(self, topic: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            """
            UPDATE facts SET archived_at = ?
            WHERE archived_at IS NULL AND (key LIKE ? OR value LIKE ?)
            """,
            (now, f"%{topic}%", f"%{topic}%"),
        )
        self.conn.commit()
        return cursor.rowcount


def get_semantic_memory(settings: HarnessSettings | None = None) -> SemanticMemory:
    cfg = settings or load_settings()
    return SemanticMemory(cfg.resolved_semantic_db())
