"""Outbound redaction for external sub-agent routes (plan §8)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from seneschal.common.schemas import TraceEventType
from seneschal.trace.logger import TraceLogger, get_trace_logger

# High-entropy / known-secret patterns (simplified trufflehog-style rules)
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(api[_-]?key|secret|password)\s*[:=]\s*\S+"),
    re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),
]

PATH_PATTERN = re.compile(r"(/home/|/etc/|/var/)[^\s\"']+")
HOSTNAME_PATTERN = re.compile(r"\b[a-z0-9][-a-z0-9]*\.(local|internal|lan)\b", re.I)


@dataclass
class RedactionResult:
    text: str
    hits: list[str] = field(default_factory=list)
    blocked: bool = False


class Redactor:
    """Rules-first redaction; uncertainty blocks external dispatch."""

    def __init__(
        self,
        denylist: list[str] | None = None,
        trace: TraceLogger | None = None,
    ) -> None:
        self.denylist = denylist or []
        self.trace = trace or get_trace_logger()

    def redact(self, text: str, correlation_id: str) -> RedactionResult:
        hits: list[str] = []
        result = text

        for pattern in SECRET_PATTERNS:
            if pattern.search(result):
                hits.append(f"secret_pattern:{pattern.pattern[:32]}")
                result = pattern.sub("[REDACTED:SECRET]", result)

        for term in self.denylist:
            if term and term in result:
                hits.append(f"denylist:{term[:16]}")
                result = result.replace(term, "[REDACTED:PII]")

        if PATH_PATTERN.search(result):
            hits.append("path_scrub")
            result = PATH_PATTERN.sub("[REDACTED:PATH]", result)

        if HOSTNAME_PATTERN.search(result):
            hits.append("hostname_scrub")
            result = HOSTNAME_PATTERN.sub("[REDACTED:HOST]", result)

        for hit in hits:
            self.trace.emit(
                correlation_id,
                TraceEventType.REDACTION,
                "dispatcher",
                "redaction_hit",
                rule=hit,
            )

        # Fail-closed: if secret patterns matched pre-redaction, block external route
        blocked = any(h.startswith("secret_pattern:") for h in hits)
        return RedactionResult(text=result, hits=hits, blocked=blocked)
