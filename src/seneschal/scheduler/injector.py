"""Scheduler — systemd timer injects synthetic commands (plan §16)."""

from __future__ import annotations

import json
from pathlib import Path

from seneschal.common.config import HarnessSettings, load_settings
from seneschal.common.schemas import new_request_id
from seneschal.ingest.service import IngestService


class SchedulerInjector:
    def __init__(self, settings: HarnessSettings | None = None) -> None:
        self.settings = settings or load_settings()
        self.ingest = IngestService(self.settings)

    def inject(self, body: str, task_name: str) -> Path:
        classification = self.ingest.classifier.classify_scheduler()
        message = self.ingest.classifier.build_message(
            classification,
            body,
            request_id=new_request_id(),
            raw_metadata={"task_name": task_name, "source": "scheduler"},
        )
        out_dir = self.settings.agent_home / "inbox" / "scheduler"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{message.request_id}.json"
        out.write_text(message.model_dump_json(indent=2))
        return out

    def list_tasks(self) -> list[dict]:
        tasks_dir = self.settings.data_dir / "scheduler"
        if not tasks_dir.exists():
            return []
        return [json.loads(p.read_text()) for p in tasks_dir.glob("*.json")]
