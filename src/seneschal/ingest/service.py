"""Ingest layer — deterministic channel auth and command/content classification (plan §5)."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from seneschal.common.config import HarnessSettings, load_settings
from seneschal.common.schemas import (
    Classification,
    InboundMessage,
    MessageClass,
    MessageSource,
    TraceEventType,
    new_request_id,
)
from seneschal.trace.logger import TraceLogger, get_trace_logger


@dataclass
class IngestAllowlists:
    principal_id: str = "owner"
    email_senders: set[str] = field(default_factory=set)
    sms_numbers: set[str] = field(default_factory=set)
    voice_callers: set[str] = field(default_factory=set)
    api_keys: dict[str, str] = field(default_factory=dict)
    sms_command_prefix: str | None = None


def load_allowlists(path: Path) -> IngestAllowlists:
    if not path.exists():
        return IngestAllowlists()
    data = yaml.safe_load(path.read_text()) or {}
    return IngestAllowlists(
        principal_id=data.get("principal_id", "owner"),
        email_senders=set(data.get("email_senders", [])),
        sms_numbers=set(data.get("sms_numbers", [])),
        voice_callers=set(data.get("voice_callers", [])),
        api_keys=data.get("api_keys", {}),
        sms_command_prefix=data.get("sms_command_prefix"),
    )


class IngestClassifier:
    """Classifies every inbound message as command or content before the orchestrator."""

    def __init__(
        self,
        allowlists: IngestAllowlists,
        trace: TraceLogger | None = None,
    ) -> None:
        self.allowlists = allowlists
        self.trace = trace or get_trace_logger()

    def classify_desktop(self, api_key: str) -> Classification:
        principal = self.allowlists.api_keys.get(api_key)
        if principal:
            return Classification(
                message_class=MessageClass.COMMAND,
                source=MessageSource.DESKTOP,
                principal_id=principal,
                authenticated=True,
                provenance_tags=["channel:desktop", "auth:api_key"],
            )
        return Classification(
            message_class=MessageClass.CONTENT,
            source=MessageSource.DESKTOP,
            principal_id=self.allowlists.principal_id,
            authenticated=False,
            provenance_tags=["channel:desktop", "auth:failed"],
        )

    def classify_email(
        self,
        sender: str,
        dkim_pass: bool,
        spf_pass: bool,
        dmarc_pass: bool,
    ) -> Classification:
        auth_ok = dkim_pass and spf_pass and dmarc_pass
        on_allowlist = sender.lower() in {s.lower() for s in self.allowlists.email_senders}
        is_command = auth_ok and on_allowlist
        return Classification(
            message_class=MessageClass.COMMAND if is_command else MessageClass.CONTENT,
            source=MessageSource.EMAIL,
            principal_id=self.allowlists.principal_id,
            correspondent_id=sender if not is_command else None,
            authenticated=is_command,
            provenance_tags=[
                "channel:email",
                f"auth:dkim={'pass' if dkim_pass else 'fail'}",
                f"auth:spf={'pass' if spf_pass else 'fail'}",
                f"auth:dmarc={'pass' if dmarc_pass else 'fail'}",
            ],
        )

    def classify_sms(self, from_number: str, body: str) -> Classification:
        on_allowlist = from_number in self.allowlists.sms_numbers
        prefix_ok = True
        if self.allowlists.sms_command_prefix:
            prefix_ok = body.startswith(self.allowlists.sms_command_prefix)
        is_command = on_allowlist and prefix_ok
        return Classification(
            message_class=MessageClass.COMMAND if is_command else MessageClass.CONTENT,
            source=MessageSource.SMS,
            principal_id=self.allowlists.principal_id,
            correspondent_id=from_number if not is_command else None,
            authenticated=is_command,
            provenance_tags=["channel:sms"],
        )

    def classify_scheduler(self) -> Classification:
        return Classification(
            message_class=MessageClass.COMMAND,
            source=MessageSource.SCHEDULER,
            principal_id=self.allowlists.principal_id,
            authenticated=True,
            provenance_tags=["channel:scheduler", "source:scheduler"],
        )

    def build_message(
        self,
        classification: Classification,
        body: str,
        *,
        request_id: str | None = None,
        thread_id: str | None = None,
        attachments: list[str] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> InboundMessage:
        msg = InboundMessage(
            request_id=request_id or new_request_id(),
            classification=classification,
            channel=classification.source,
            body=body,
            thread_id=thread_id,
            attachments=attachments or [],
            raw_metadata=raw_metadata or {},
        )
        self.trace.emit(
            msg.request_id,
            TraceEventType.INGEST,
            "ingest",
            "classified",
            message_class=classification.message_class.value,
            source=classification.source.value,
            authenticated=classification.authenticated,
        )
        return msg


class IngestService:
    """Entry point for channel adapters to submit normalized inbound messages."""

    def __init__(self, settings: HarnessSettings | None = None) -> None:
        self.settings = settings or load_settings()
        allowlist_path = self.settings.config_dir / "ingest_allowlists.yaml"
        self.classifier = IngestClassifier(load_allowlists(allowlist_path))

    def accept(self, message: InboundMessage) -> Path | None:
        """Write command-class messages to orchestrator inbox; log unmatched content."""
        inbox = self.settings.agent_home / "inbox"
        if message.classification.message_class == MessageClass.COMMAND:
            channel_dir = inbox / message.channel.value
            channel_dir.mkdir(parents=True, exist_ok=True)
            out = channel_dir / f"{message.request_id}.json"
            out.write_text(message.model_dump_json(indent=2))
            return out
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Seneschal ingest layer smoke test")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--body", required=True)
    args = parser.parse_args()

    service = IngestService()
    classification = service.classifier.classify_desktop(args.api_key)
    msg = service.classifier.build_message(classification, args.body)
    path = service.accept(msg)
    print(msg.model_dump_json(indent=2))
    if path:
        print(f"Wrote command to {path}")


if __name__ == "__main__":
    main()
