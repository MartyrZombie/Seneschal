"""Unified structured trace logging with correlation IDs (plan §17)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from seneschal.common.config import HarnessSettings, load_settings
from seneschal.common.schemas import CorrelationId, TraceEvent, TraceEventType


class TraceLogger:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        correlation_id: CorrelationId,
        event_type: TraceEventType,
        component: str,
        message: str,
        **details: Any,
    ) -> TraceEvent:
        event = TraceEvent(
            correlation_id=correlation_id,
            event_type=event_type,
            component=component,
            message=message,
            details=details,
        )
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")
        return event

    @contextmanager
    def span(
        self,
        correlation_id: CorrelationId,
        event_type: TraceEventType,
        component: str,
        message: str,
        **details: Any,
    ) -> Iterator[TraceEvent]:
        start = datetime.now(timezone.utc)
        self.emit(correlation_id, event_type, component, f"{message}:start", **details)
        try:
            yield self.emit(correlation_id, event_type, component, message, **details)
        except Exception as exc:
            self.emit(
                correlation_id,
                event_type,
                component,
                f"{message}:error",
                error=str(exc),
                **details,
            )
            raise
        finally:
            elapsed = (datetime.now(timezone.utc) - start).total_seconds()
            self.emit(
                correlation_id,
                event_type,
                component,
                f"{message}:end",
                elapsed_seconds=elapsed,
                **details,
            )


def get_trace_logger(settings: HarnessSettings | None = None) -> TraceLogger:
    cfg = settings or load_settings()
    return TraceLogger(cfg.resolved_trace_log())


def query_by_correlation_id(log_path: Path, correlation_id: str) -> list[TraceEvent]:
    if not log_path.exists():
        return []
    events: list[TraceEvent] = []
    with log_path.open(encoding="utf-8") as f:
        for line in f:
            if correlation_id not in line:
                continue
            events.append(TraceEvent.model_validate_json(line))
    return events
