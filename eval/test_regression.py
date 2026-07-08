"""Regression eval runner for Seneschal (plan §20)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import yaml

from seneschal.common.schemas import MessageClass, RequestBudgetEnvelope, SubtaskBrief
from seneschal.correspondence.store import CorrespondenceStore
from seneschal.dispatcher.daemon import Dispatcher
from seneschal.dispatcher.redaction import Redactor
from seneschal.ingest.service import IngestAllowlists, IngestClassifier


from seneschal.trace.logger import TraceLogger


class _NoopTrace(TraceLogger):
    def __init__(self) -> None:
        pass

    def emit(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return None


MANIFEST = Path(__file__).parent / "regression" / "manifest.yaml"


def load_cases() -> list[dict]:
    data = yaml.safe_load(MANIFEST.read_text())
    return data.get("cases", [])


def run_ingest_case(case: dict) -> None:
    allowlists = IngestAllowlists(email_senders={"owner@example.com"})
    classifier = IngestClassifier(allowlists, trace=_NoopTrace())
    inp = case["input"]
    result = classifier.classify_email(
        inp["sender"], inp["dkim_pass"], inp["spf_pass"], inp["dmarc_pass"]
    )
    expected = MessageClass(case["expect"]["message_class"])
    assert result.message_class == expected, case["id"]


def run_redaction_case(case: dict) -> None:
    redactor = Redactor()
    inp = case["input"]
    out = redactor.redact(inp["context"], correlation_id="eval")
    assert out.blocked == case["expect"]["blocked"], case["id"]


def run_budget_case(case: dict) -> None:
    dispatcher = Dispatcher()
    envelope = RequestBudgetEnvelope(max_subtasks=case["input"]["max_subtasks"])
    request_id = f"eval-budget-{uuid4()}"
    for i in range(case["input"]["submit_count"]):
        brief = SubtaskBrief(
            request_id=request_id,
            goal=f"task {i}",
            context="eval",
            tools_allowed=[],
            success_criteria="n/a",
            output_contract="any",
        )
        if i < case["input"]["max_subtasks"]:
            dispatcher.submit(brief, envelope=envelope if i == 0 else None)
        else:
            try:
                dispatcher.submit(brief)
                raise AssertionError(f"{case['id']} should have failed")
            except RuntimeError as exc:
                assert case["expect"]["error"] in str(exc)


def run_correspondence_case(case: dict) -> None:
    store = CorrespondenceStore(Path("/tmp/seneschal-eval-correspondence.db"))
    ok, _ = store.can_send(case["input"]["thread_id"])
    assert ok == case["expect"]["can_send"], case["id"]


def test_regression_manifest_cases() -> None:
    for case in load_cases():
        suite = case.get("suite", "")
        if suite == "ingest_classification":
            run_ingest_case(case)
        elif suite == "redaction":
            run_redaction_case(case)
        elif suite == "budget_overrun":
            run_budget_case(case)
        elif suite == "correspondence_policy":
            run_correspondence_case(case)
        # injection_probes validated structurally in ingest/orchestrator integration later
