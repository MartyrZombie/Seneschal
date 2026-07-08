"""Subtask dispatcher — deterministic daemon, budgets, validation (plan §8)."""

from __future__ import annotations

import argparse
import asyncio
import time
from typing import Literal

import httpx

from seneschal.common.config import HarnessSettings, load_settings
from seneschal.common.schemas import (
    BudgetUsed,
    ModelTier,
    RequestBudgetEnvelope,
    ResultType,
    RouteKind,
    SubtaskBrief,
    SubtaskResult,
    SubtaskResultPayload,
    SubtaskState,
    SubtaskStatus,
    TraceEventType,
)
from seneschal.dispatcher.redaction import Redactor
from seneschal.dispatcher.store import DispatcherStore
from seneschal.trace.logger import get_trace_logger


class SubtaskRunner:
    """Runs a single sub-agent against llama.cpp or OpenRouter."""

    def __init__(self, settings: HarnessSettings) -> None:
        self.settings = settings

    async def run(self, brief: SubtaskBrief, route: RouteKind) -> SubtaskResult:
        start = time.monotonic()
        if route == "openrouter":
            return await self._run_openrouter(brief, start)
        return await self._run_local(brief, start)

    async def _run_local(self, brief: SubtaskBrief, start: float) -> SubtaskResult:
        url = (
            self.settings.orchestrator_model_url
            if brief.model_tier == ModelTier.LARGE
            else self.settings.small_model_url
        )
        model = (
            self.settings.orchestrator_model_name
            if brief.model_tier == ModelTier.LARGE
            else self.settings.small_model_name
        )
        prompt = (
            f"Goal: {brief.goal}\n\nContext:\n{brief.context}\n\n"
            f"Success criteria: {brief.success_criteria}\n"
            f"Output contract: {brief.output_contract}\n"
            "Respond with JSON matching the subtask result schema."
        )
        async with httpx.AsyncClient(timeout=brief.budget.max_wall_seconds) as client:
            resp = await client.post(
                f"{url}/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": min(brief.budget.max_tokens, 4096),
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        elapsed = time.monotonic() - start
        return SubtaskResult(
            subtask_id=brief.subtask_id,
            status=SubtaskStatus.SUCCESS,
            result=SubtaskResultPayload(type=ResultType.TEXT, content=content),
            budget_used=BudgetUsed(turns=1, tokens=len(content.split()) * 2, wall_seconds=elapsed),
        )

    async def _run_openrouter(self, brief: SubtaskBrief, start: float) -> SubtaskResult:
        # Credentials live in dispatcher service account env, never agent user
        api_key = ""  # wired from sops/age at deploy time
        async with httpx.AsyncClient(timeout=brief.budget.max_wall_seconds) as client:
            resp = await client.post(
                f"{self.settings.openrouter_api_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "anthropic/claude-sonnet-4",
                    "messages": [{"role": "user", "content": brief.context}],
                    "provider": {"zdr": True, "data_collection": "deny"},
                },
            )
            if resp.status_code >= 400:
                return SubtaskResult(
                    subtask_id=brief.subtask_id,
                    status=SubtaskStatus.FAILURE,
                    notes=resp.text,
                    budget_used=BudgetUsed(wall_seconds=time.monotonic() - start),
                )
            content = resp.json()["choices"][0]["message"]["content"]
        return SubtaskResult(
            subtask_id=brief.subtask_id,
            status=SubtaskStatus.SUCCESS,
            result=SubtaskResultPayload(type=ResultType.TEXT, content=content),
            budget_used=BudgetUsed(turns=1, tokens=len(content.split()) * 2, wall_seconds=time.monotonic() - start),
        )


class Dispatcher:
    def __init__(self, settings: HarnessSettings | None = None) -> None:
        self.settings = settings or load_settings()
        db_path = self.settings.data_dir / "dispatcher.db"
        self.store = DispatcherStore(db_path)
        self.runner = SubtaskRunner(self.settings)
        self.redactor = Redactor()
        self.trace = get_trace_logger()

    def submit(
        self,
        brief: SubtaskBrief,
        route: RouteKind = "local",
        envelope: RequestBudgetEnvelope | None = None,
    ) -> str:
        self.store.ensure_envelope(brief.request_id, envelope)
        if self.store.envelope_exceeded(brief.request_id):
            raise RuntimeError("request budget envelope exceeded")
        self.store.reserve_subtask_slot(brief.request_id)

        if route == "openrouter":
            redacted = self.redactor.redact(brief.context, brief.request_id)
            if redacted.blocked:
                raise RuntimeError("redaction blocked external dispatch")
            brief = brief.model_copy(update={"context": redacted.text})

        self.store.enqueue(brief, route=route)
        self.trace.emit(
            brief.request_id,
            TraceEventType.DISPATCH,
            "dispatcher",
            "enqueued",
            subtask_id=brief.subtask_id,
            route=route,
        )
        return brief.subtask_id

    def validate_result(self, brief: SubtaskBrief, result: SubtaskResult) -> bool:
        if result.status != SubtaskStatus.SUCCESS or result.result is None:
            return result.status in (SubtaskStatus.FAILURE, SubtaskStatus.NEEDS_DECOMPOSITION)
        # Minimal contract check — expand per output_contract schema in production
        return result.result.type.value in brief.output_contract or brief.output_contract == "any"

    async def process_one(self) -> bool:
        subtask_id = self.store.next_queued()
        if not subtask_id:
            return False

        row = self.store.get_route_and_brief(subtask_id)
        assert row is not None
        route: RouteKind = row[0]  # type: ignore[assignment]
        brief = row[1]

        self.store.transition(subtask_id, SubtaskState.RUNNING)
        try:
            result = await self.runner.run(brief, route)
        except Exception as exc:
            result = SubtaskResult(
                subtask_id=subtask_id,
                status=SubtaskStatus.FAILURE,
                notes=str(exc),
            )

        self.store.transition(subtask_id, SubtaskState.RETURNED, result)

        if result.status == SubtaskStatus.FAILURE:
            retries = self.store.increment_retry(subtask_id)
            if retries <= 1:
                brief = brief.model_copy(
                    update={"context": brief.context + f"\n\nPrior error: {result.notes}"}
                )
                self.store.enqueue(brief, route=route)
            else:
                self.store.transition(subtask_id, SubtaskState.FAILED, result)
                return True

        if self.validate_result(brief, result):
            self.store.transition(subtask_id, SubtaskState.VALIDATED, result)
            self.store.transition(subtask_id, SubtaskState.DELIVERED, result)
            tokens = result.budget_used.tokens if result.budget_used else 0
            spend = 0.05 if route == "openrouter" else 0.0
            self.store.record_usage(brief.request_id, tokens, spend, increment_count=False)
            self.trace.emit(
                brief.request_id,
                TraceEventType.SUBTASK,
                "dispatcher",
                "delivered",
                subtask_id=subtask_id,
                status=result.status.value,
            )
        return True

    async def run_loop(self, poll_interval: float = 1.0) -> None:
        while True:
            worked = await self.process_one()
            if not worked:
                await asyncio.sleep(poll_interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seneschal subtask dispatcher")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    dispatcher = Dispatcher()
    if args.once:
        asyncio.run(dispatcher.process_one())
    else:
        asyncio.run(dispatcher.run_loop())


if __name__ == "__main__":
    main()
