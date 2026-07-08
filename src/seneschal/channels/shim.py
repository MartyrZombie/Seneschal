"""OpenAI-compatible shim for desktop clients — Chatbox/Jan (plan §18)."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from seneschal.common.config import HarnessSettings, load_settings
from seneschal.common.schemas import MessageClass, new_request_id
from seneschal.ingest.service import IngestClassifier, IngestService, load_allowlists
from seneschal.orchestrator.core import Orchestrator


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "seneschal"
    messages: list[ChatMessage]
    stream: bool = False


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatMessage | None = None
    delta: dict[str, str] | None = None
    finish_reason: str | None = None


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = "seneschal"
    choices: list[ChatCompletionChoice]


def create_app(settings: HarnessSettings | None = None) -> FastAPI:
    cfg = settings or load_settings()
    app = FastAPI(title="Seneschal OpenAI Shim", version="0.1.0")
    allowlists = load_allowlists(cfg.config_dir / "ingest_allowlists.yaml")
    if not allowlists.api_keys and cfg.shim_api_keys:
        allowlists.api_keys = {k: cfg.principal_id for k in cfg.shim_api_keys}
    classifier = IngestClassifier(allowlists)
    ingest = IngestService(cfg)
    ingest.classifier = classifier
    orchestrator = Orchestrator(cfg)

    def authenticate(authorization: str | None) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing API key")
        api_key = authorization.removeprefix("Bearer ").strip()
        classification = classifier.classify_desktop(api_key)
        if classification.message_class != MessageClass.COMMAND:
            raise HTTPException(status_code=403, detail="Invalid API key")

    @app.get("/v1/models")
    async def list_models() -> dict:
        return {
            "object": "list",
            "data": [{"id": "seneschal", "object": "model", "owned_by": "seneschal"}],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(
        request: ChatCompletionRequest,
        authorization: str | None = Header(default=None),
    ) -> ChatCompletionResponse | StreamingResponse:
        authenticate(authorization)
        user_messages = [m for m in request.messages if m.role == "user"]
        if not user_messages:
            raise HTTPException(status_code=400, detail="No user message")
        body = user_messages[-1].content

        classification = classifier.classify_desktop(
            authorization.removeprefix("Bearer ").strip()  # type: ignore[union-attr]
        )
        message = classifier.build_message(classification, body, request_id=new_request_id())
        ingest.accept(message)

        if request.stream:
            return StreamingResponse(
                _stream_response(orchestrator, message),
                media_type="text/event-stream",
            )

        content = await orchestrator.handle_command(message)
        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
            choices=[
                ChatCompletionChoice(
                    message=ChatMessage(role="assistant", content=content),
                    finish_reason="stop",
                )
            ],
        )

    return app


async def _stream_response(orchestrator: Orchestrator, message) -> AsyncIterator[str]:
    yield _sse_chunk("Dispatching subtask…")
    await asyncio.sleep(0.1)
    yield _sse_chunk("Synthesizing…")
    content = await orchestrator.handle_command(message)
    yield _sse_chunk(content, finish=True)


def _sse_chunk(content: str, finish: bool = False) -> str:
    payload = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion.chunk",
        "choices": [
            {
                "index": 0,
                "delta": {"content": content},
                "finish_reason": "stop" if finish else None,
            }
        ],
    }
    return f"data: {json.dumps(payload)}\n\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Seneschal OpenAI-compatible shim")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    settings = load_settings()
    host = args.host or settings.shim_host
    port = args.port or settings.shim_port
    uvicorn.run(create_app(settings), host=host, port=port)


if __name__ == "__main__":
    main()
