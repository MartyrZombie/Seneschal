"""Email channel adapter stub (plan §18 — build step 11)."""

from __future__ import annotations

from seneschal.ingest.service import IngestService


class EmailChannel:
    def __init__(self) -> None:
        self.ingest = IngestService()

    def handle_inbound(
        self,
        sender: str,
        body: str,
        *,
        dkim_pass: bool,
        spf_pass: bool,
        dmarc_pass: bool,
        thread_id: str | None = None,
    ) -> None:
        classification = self.ingest.classifier.classify_email(
            sender, dkim_pass, spf_pass, dmarc_pass
        )
        message = self.ingest.classifier.build_message(
            classification, body, thread_id=thread_id
        )
        self.ingest.accept(message)
