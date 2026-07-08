"""Core data contracts shared across all harness components (plan §6–§8)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def new_request_id() -> str:
    return str(uuid.uuid4())


def new_subtask_id() -> str:
    return str(uuid.uuid4())


PrincipalId = str
CorrespondentId = str | None
RequestId = str
SubtaskId = str
CorrelationId = RequestId


class MessageClass(str, Enum):
    """Inbound classification — only COMMAND can instruct the agent (plan §5)."""

    COMMAND = "command"
    CONTENT = "content"


class MessageSource(str, Enum):
    DESKTOP = "desktop"
    EMAIL = "email"
    SMS = "sms"
    VOICE = "voice"
    SCHEDULER = "scheduler"
    TWILIO_WEBHOOK = "twilio_webhook"


class Classification(BaseModel):
    message_class: MessageClass
    source: MessageSource
    principal_id: PrincipalId
    correspondent_id: CorrespondentId = None
    authenticated: bool = False
    provenance_tags: list[str] = Field(default_factory=list)


class InboundMessage(BaseModel):
    """Normalized message after ingest classification."""

    request_id: RequestId = Field(default_factory=new_request_id)
    classification: Classification
    channel: MessageSource
    body: str
    attachments: list[str] = Field(default_factory=list)
    thread_id: str | None = None
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class Budget(BaseModel):
    max_turns: int = 8
    max_tokens: int = 20_000
    max_wall_seconds: int = 300


class BudgetUsed(BaseModel):
    turns: int = 0
    tokens: int = 0
    wall_seconds: float = 0.0


class ModelTier(str, Enum):
    LARGE = "large"
    SMALL = "small"


class SubtaskStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    NEEDS_DECOMPOSITION = "needs_decomposition"


class ResultType(str, Enum):
    TEXT = "text"
    JSON = "json"
    FILE_REF = "file_ref"


class SubtaskBrief(BaseModel):
    """Orchestrator → sub-agent contract (plan §8)."""

    subtask_id: SubtaskId = Field(default_factory=new_subtask_id)
    request_id: RequestId
    goal: str
    context: str
    tools_allowed: list[str]
    model_tier: ModelTier = ModelTier.SMALL
    success_criteria: str
    output_contract: str
    budget: Budget = Field(default_factory=Budget)


class SubtaskResultPayload(BaseModel):
    type: ResultType
    content: str | dict[str, Any]


class SubtaskResult(BaseModel):
    """Sub-agent → orchestrator contract (plan §8)."""

    subtask_id: SubtaskId
    status: SubtaskStatus
    result: SubtaskResultPayload | None = None
    notes: str = ""
    budget_used: BudgetUsed = Field(default_factory=BudgetUsed)


class SubtaskState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    RETURNED = "returned"
    VALIDATED = "validated"
    DELIVERED = "delivered"
    FAILED = "failed"


class TraceEventType(str, Enum):
    INGEST = "ingest"
    ORCHESTRATOR = "orchestrator"
    DISPATCH = "dispatch"
    SUBTASK = "subtask"
    BROKER = "broker"
    REDACTION = "redaction"
    MCP = "mcp"
    EGRESS = "egress"
    MEMORY = "memory"
    SCHEDULER = "scheduler"


class TraceEvent(BaseModel):
    """Unified trace log entry (plan §17)."""

    correlation_id: CorrelationId
    event_type: TraceEventType
    component: str
    message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict[str, Any] = Field(default_factory=dict)


class BrokerAction(str, Enum):
    SEND_TEXT = "send_text"
    PLACE_CALL = "place_call"
    SEND_EMAIL = "send_email"


class BrokerRequest(BaseModel):
    action: BrokerAction
    idempotency_key: str
    principal_id: PrincipalId
    payload: dict[str, Any]


class BrokerResponse(BaseModel):
    ok: bool
    action: BrokerAction
    idempotency_key: str
    message: str = ""
    external_id: str | None = None
    denied_reason: str | None = None


class RequestBudgetEnvelope(BaseModel):
    """Per-request caps enforced by the dispatcher (plan §8)."""

    max_subtasks: int = 20
    max_total_tokens: int = 200_000
    max_external_spend_usd: float = 5.0


RouteKind = Literal["local", "openrouter"]
