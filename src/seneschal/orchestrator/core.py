"""Orchestrator core — plans, delegates, synthesizes (plan §7)."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from seneschal.common.config import HarnessSettings, load_settings
from seneschal.common.schemas import (
    InboundMessage,
    MessageClass,
    ModelTier,
    SubtaskBrief,
    SubtaskStatus,
    TraceEventType,
    new_request_id,
)
from seneschal.dispatcher.daemon import Dispatcher
from seneschal.memory.working import WorkingMemory
from seneschal.orchestrator.prompts import ORCHESTRATOR_SYSTEM_PROMPT
from seneschal.skills.loader import SkillIndex
from seneschal.trace.logger import get_trace_logger


class Orchestrator:
    def __init__(self, settings: HarnessSettings | None = None) -> None:
        self.settings = settings or load_settings()
        self.dispatcher = Dispatcher(self.settings)
        self.working = WorkingMemory()
        self.skills = SkillIndex(self.settings.agent_home / "skills")
        self.trace = get_trace_logger()

    def _load_index(self) -> str:
        index_path = self.settings.agent_home / "INDEX.md"
        if index_path.exists():
            return index_path.read_text()
        return "# Agent index\n"

    async def handle_command(self, message: InboundMessage) -> str:
        if message.classification.message_class != MessageClass.COMMAND:
            return "Ignored: message is content-class, not a command."

        self.trace.emit(
            message.request_id,
            TraceEventType.ORCHESTRATOR,
            "orchestrator",
            "command_received",
            channel=message.channel.value,
        )

        self.working.set("current_request", message.model_dump())
        skill_metadata = self.skills.metadata_block()

        # Phase 1: single sub-agent dispatch for scaffold
        brief = SubtaskBrief(
            request_id=message.request_id,
            goal=message.body,
            context=(
                f"[provenance:command channel={message.channel.value}]\n"
                f"{self._load_index()}\n\nSkills:\n{skill_metadata}"
            ),
            tools_allowed=["read_file"],
            model_tier=ModelTier.LARGE,
            success_criteria="Answer the user's command clearly and completely.",
            output_contract="text",
        )
        subtask_id = self.dispatcher.submit(brief)
        self.trace.emit(
            message.request_id,
            TraceEventType.ORCHESTRATOR,
            "orchestrator",
            "subtask_dispatched",
            subtask_id=subtask_id,
        )

        # Wait for dispatcher (simplified poll for scaffold)
        for _ in range(120):
            await asyncio.sleep(1)
            delivery = self.dispatcher.store.get_delivery(subtask_id)
            if not delivery:
                continue
            state, result = delivery
            if state == "delivered" and result:
                if result.status == SubtaskStatus.SUCCESS and result.result:
                    return self._synthesize(message.body, str(result.result.content))
            if state == "failed":
                return "Subtask failed after retries. Check trace log."

        return "Subtask timed out waiting for dispatcher."

    def _synthesize(self, command: str, subtask_output: str) -> str:
        """Synthesize sub-agent output into a coherent answer (stub — model call in production)."""
        return subtask_output

    async def poll_inbox(self) -> None:
        inbox = self.settings.agent_home / "inbox"
        for channel_dir in inbox.iterdir() if inbox.exists() else []:
            if not channel_dir.is_dir():
                continue
            for msg_file in channel_dir.glob("*.json"):
                message = InboundMessage.model_validate_json(msg_file.read_text())
                response = await self.handle_command(message)
                out_dir = self.settings.agent_home / "outbox" / channel_dir.name
                out_dir.mkdir(parents=True, exist_ok=True)
                out_file = out_dir / f"{message.request_id}.txt"
                out_file.write_text(response)
                msg_file.unlink()


async def run_once(settings: HarnessSettings | None = None) -> None:
    orch = Orchestrator(settings)
    await orch.poll_inbox()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seneschal orchestrator")
    parser.add_argument("--poll", action="store_true", help="Poll inbox once")
    parser.add_argument("--body", help="Process a single command body (dev)")
    args = parser.parse_args()

    if args.body:
        from seneschal.common.schemas import Classification, MessageSource

        settings = load_settings()
        orch = Orchestrator(settings)
        msg = InboundMessage(
            request_id=new_request_id(),
            classification=Classification(
                message_class=MessageClass.COMMAND,
                source=MessageSource.DESKTOP,
                principal_id=settings.principal_id,
                authenticated=True,
            ),
            channel=MessageSource.DESKTOP,
            body=args.body,
        )
        print(asyncio.run(orch.handle_command(msg)))
    elif args.poll:
        asyncio.run(run_once())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
