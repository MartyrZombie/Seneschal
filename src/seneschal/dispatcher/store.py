"""Persisted subtask queue and state machine (plan §8)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from seneschal.common.schemas import (
    RequestBudgetEnvelope,
    SubtaskBrief,
    SubtaskResult,
    SubtaskState,
)


class DispatcherStore:
  SCHEMA = """
  CREATE TABLE IF NOT EXISTS subtasks (
      subtask_id TEXT PRIMARY KEY,
      request_id TEXT NOT NULL,
      state TEXT NOT NULL,
      route TEXT NOT NULL DEFAULT 'local',
      brief_json TEXT NOT NULL,
      result_json TEXT,
      retry_count INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_subtasks_request ON subtasks(request_id);
  CREATE INDEX IF NOT EXISTS idx_subtasks_state ON subtasks(state);

  CREATE TABLE IF NOT EXISTS request_envelopes (
      request_id TEXT PRIMARY KEY,
      envelope_json TEXT NOT NULL,
      subtask_count INTEGER NOT NULL DEFAULT 0,
      tokens_used INTEGER NOT NULL DEFAULT 0,
      spend_usd REAL NOT NULL DEFAULT 0.0
  );
  """

  def __init__(self, db_path: Path) -> None:
      db_path.parent.mkdir(parents=True, exist_ok=True)
      self.conn = sqlite3.connect(str(db_path))
      self.conn.executescript(self.SCHEMA)
      self.conn.commit()

  def enqueue(self, brief: SubtaskBrief, route: str = "local") -> None:
      now = datetime.now(timezone.utc).isoformat()
      self.conn.execute(
          """
          INSERT INTO subtasks (subtask_id, request_id, state, route, brief_json, created_at, updated_at)
          VALUES (?, ?, ?, ?, ?, ?, ?)
          """,
          (
              brief.subtask_id,
              brief.request_id,
              SubtaskState.QUEUED.value,
              route,
              brief.model_dump_json(),
              now,
              now,
          ),
      )
      self.conn.commit()

  def transition(self, subtask_id: str, state: SubtaskState, result: SubtaskResult | None = None) -> None:
      now = datetime.now(timezone.utc).isoformat()
      result_json = result.model_dump_json() if result else None
      self.conn.execute(
          "UPDATE subtasks SET state = ?, result_json = ?, updated_at = ? WHERE subtask_id = ?",
          (state.value, result_json, now, subtask_id),
      )
      self.conn.commit()

  def get_brief(self, subtask_id: str) -> SubtaskBrief | None:
      row = self.conn.execute(
          "SELECT brief_json FROM subtasks WHERE subtask_id = ?", (subtask_id,)
      ).fetchone()
      if not row:
          return None
      return SubtaskBrief.model_validate_json(row[0])

  def next_queued(self) -> str | None:
      row = self.conn.execute(
          "SELECT subtask_id FROM subtasks WHERE state = ? ORDER BY created_at LIMIT 1",
          (SubtaskState.QUEUED.value,),
      ).fetchone()
      return row[0] if row else None

  def increment_retry(self, subtask_id: str) -> int:
      self.conn.execute(
          "UPDATE subtasks SET retry_count = retry_count + 1 WHERE subtask_id = ?",
          (subtask_id,),
      )
      self.conn.commit()
      row = self.conn.execute(
          "SELECT retry_count FROM subtasks WHERE subtask_id = ?", (subtask_id,)
      ).fetchone()
      return int(row[0]) if row else 0

  def get_envelope(self, request_id: str) -> RequestBudgetEnvelope:
      row = self.conn.execute(
          "SELECT envelope_json FROM request_envelopes WHERE request_id = ?", (request_id,)
      ).fetchone()
      if row:
          return RequestBudgetEnvelope.model_validate_json(row[0])
      return RequestBudgetEnvelope()

  def ensure_envelope(self, request_id: str, envelope: RequestBudgetEnvelope | None = None) -> None:
      env = envelope or RequestBudgetEnvelope()
      self.conn.execute(
          "INSERT OR IGNORE INTO request_envelopes (request_id, envelope_json) VALUES (?, ?)",
          (request_id, env.model_dump_json()),
      )
      self.conn.commit()

  def record_usage(
      self,
      request_id: str,
      tokens: int,
      spend_usd: float = 0.0,
      *,
      increment_count: bool = True,
  ) -> None:
      if increment_count:
          self.conn.execute(
              """
              UPDATE request_envelopes
              SET subtask_count = subtask_count + 1,
                  tokens_used = tokens_used + ?,
                  spend_usd = spend_usd + ?
              WHERE request_id = ?
              """,
              (tokens, spend_usd, request_id),
          )
      else:
          self.conn.execute(
              """
              UPDATE request_envelopes
              SET tokens_used = tokens_used + ?,
                  spend_usd = spend_usd + ?
              WHERE request_id = ?
              """,
              (tokens, spend_usd, request_id),
          )
      self.conn.commit()

  def get_route_and_brief(self, subtask_id: str) -> tuple[str, SubtaskBrief] | None:
      row = self.conn.execute(
          "SELECT route, brief_json FROM subtasks WHERE subtask_id = ?", (subtask_id,)
      ).fetchone()
      if not row:
          return None
      return row[0], SubtaskBrief.model_validate_json(row[1])

  def get_delivery(self, subtask_id: str) -> tuple[str, SubtaskResult | None] | None:
      row = self.conn.execute(
          "SELECT state, result_json FROM subtasks WHERE subtask_id = ?", (subtask_id,)
      ).fetchone()
      if not row:
          return None
      result = SubtaskResult.model_validate_json(row[1]) if row[1] else None
      return row[0], result

  def reserve_subtask_slot(self, request_id: str) -> None:
      self.conn.execute(
          "UPDATE request_envelopes SET subtask_count = subtask_count + 1 WHERE request_id = ?",
          (request_id,),
      )
      self.conn.commit()

  def envelope_exceeded(self, request_id: str) -> bool:
      row = self.conn.execute(
          "SELECT envelope_json, subtask_count, tokens_used, spend_usd FROM request_envelopes WHERE request_id = ?",
          (request_id,),
      ).fetchone()
      if not row:
          return False
      env = RequestBudgetEnvelope.model_validate_json(row[0])
      return (
          row[1] >= env.max_subtasks
          or row[2] >= env.max_total_tokens
          or row[3] >= env.max_external_spend_usd
      )
