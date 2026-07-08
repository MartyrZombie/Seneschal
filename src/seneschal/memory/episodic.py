"""Episodic memory — session logs with hybrid retrieval scaffold (plan §9)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from seneschal.common.config import HarnessSettings, load_settings


class EpisodicMemory:
    """SQLite FTS5 + file-backed episodic entries. Vector index wired in build step 6."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS episodic (
        id TEXT PRIMARY KEY,
        principal_id TEXT NOT NULL,
        request_id TEXT,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS episodic_fts USING fts5(
        id UNINDEXED,
        content,
        content='episodic',
        content_rowid='rowid'
    );
  """

    def __init__(self, episodic_dir: Path) -> None:
        episodic_dir.mkdir(parents=True, exist_ok=True)
        self.dir = episodic_dir
        self.db_path = episodic_dir / "episodic.db"
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.executescript(self.SCHEMA)
        self.conn.commit()

    def append(self, principal_id: str, content: str, request_id: str | None = None) -> str:
        entry_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO episodic (id, principal_id, request_id, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (entry_id, principal_id, request_id, content, now),
        )
        self.conn.execute(
            "INSERT INTO episodic_fts (id, content) VALUES (?, ?)",
            (entry_id, content),
        )
        self.conn.commit()
        (self.dir / f"{entry_id}.json").write_text(
            json.dumps({"id": entry_id, "principal_id": principal_id, "content": content})
        )
        return entry_id

    def search(self, query: str, limit: int = 10) -> list[dict[str, str]]:
        rows = self.conn.execute(
            """
            SELECT e.id, e.content, e.created_at
            FROM episodic_fts f
            JOIN episodic e ON e.id = f.id
            WHERE episodic_fts MATCH ?
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return [{"id": r[0], "content": r[1], "created_at": r[2]} for r in rows]

    def forget_topic(self, topic: str) -> int:
        """Hard-delete entries matching topic (plan §9 forget command)."""
        rows = self.conn.execute(
            "SELECT id FROM episodic WHERE content LIKE ?", (f"%{topic}%",)
        ).fetchall()
        for (entry_id,) in rows:
            self.conn.execute("DELETE FROM episodic WHERE id = ?", (entry_id,))
            self.conn.execute("DELETE FROM episodic_fts WHERE id = ?", (entry_id,))
            path = self.dir / f"{entry_id}.json"
            if path.exists():
                path.unlink()
        self.conn.commit()
        return len(rows)


def get_episodic_memory(settings: HarnessSettings | None = None) -> EpisodicMemory:
    cfg = settings or load_settings()
    return EpisodicMemory(cfg.resolved_episodic_dir())
