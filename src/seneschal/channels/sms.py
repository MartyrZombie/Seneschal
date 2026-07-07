"""SMS channel adapter stub via Twilio webhooks (plan §18)."""

from __future__ import annotations

import hmac
import hashlib
from urllib.parse import urlencode

from seneschal.ingest.service import IngestService


def validate_twilio_signature(
    auth_token: str,
    url: str,
    params: dict[str, str],
    signature: str,
) -> bool:
    """Validate X-Twilio-Signature on every webhook request (plan §5)."""
    sorted_params = "".join(f"{k}{v}" for k, v in sorted(params.items()))
    expected = hmac.new(
        auth_token.encode(),
        (url + sorted_params).encode(),
        hashlib.sha1,
    ).digest()
    import base64

    return hmac.compare_digest(base64.b64encode(expected).decode(), signature)


class SmsChannel:
    def __init__(self) -> None:
        self.ingest = IngestService()

    def handle_inbound(self, from_number: str, body: str, thread_id: str | None = None) -> None:
        classification = self.ingest.classifier.classify_sms(from_number, body)
        message = self.ingest.classifier.build_message(
            classification, body, thread_id=thread_id
        )
        self.ingest.accept(message)
