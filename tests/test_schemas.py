"""Unit tests for core schemas and ingest classification."""

from seneschal.common.schemas import MessageClass, SubtaskBrief, SubtaskStatus
from seneschal.ingest.service import IngestAllowlists, IngestClassifier
from seneschal.trace.logger import TraceLogger


class _NoopTrace(TraceLogger):
    def __init__(self) -> None:
        pass

    def emit(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return None


def test_subtask_brief_defaults() -> None:
    brief = SubtaskBrief(
        request_id="req-1",
        goal="test",
        context="ctx",
        tools_allowed=["read_file"],
        success_criteria="done",
        output_contract="text",
    )
    assert brief.budget.max_turns == 8
    assert brief.subtask_id


def test_desktop_api_key_command() -> None:
    allowlists = IngestAllowlists(api_keys={"secret": "samson"})
    classifier = IngestClassifier(allowlists, trace=_NoopTrace())
    result = classifier.classify_desktop("secret")
    assert result.message_class == MessageClass.COMMAND


def test_desktop_invalid_key_is_content() -> None:
    allowlists = IngestAllowlists(api_keys={"secret": "samson"})
    classifier = IngestClassifier(allowlists, trace=_NoopTrace())
    result = classifier.classify_desktop("wrong")
    assert result.message_class == MessageClass.CONTENT


def test_subtask_status_enum() -> None:
    assert SubtaskStatus.NEEDS_DECOMPOSITION.value == "needs_decomposition"
