"""Application configuration loaded from environment and config files."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class HarnessSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SENESCHAL_",
        env_file=".env",
        extra="ignore",
    )

    agent_home: Path = Path("/home/agent")
    principal_id: str = "owner"
    data_dir: Path = Path("./data")

    # Service sockets
    broker_socket: Path = Path("/run/seneschal/broker.sock")
    dispatcher_socket: Path = Path("/run/seneschal/dispatcher.sock")

    # Model endpoints (llama.cpp OpenAI-compatible)
    orchestrator_model_url: str = "http://127.0.0.1:8080/v1"
    orchestrator_model_name: str = "qwen3-30b-a3b"
    small_model_url: str = "http://127.0.0.1:8081/v1"
    small_model_name: str = "qwen3-4b"

    # OpenRouter (dispatcher account only — plan §13)
    openrouter_api_url: str = "https://openrouter.ai/api/v1"
    openrouter_spend_cap_usd: float = 10.0

    # Trace
    trace_log_path: Path | None = None

    # Shim (desktop client channel — plan §18)
    shim_host: str = "127.0.0.1"
    shim_port: int = 8400
    shim_api_keys: list[str] = Field(default_factory=list)
    config_dir: Path = Path("config")

    # Memory
    semantic_db_path: Path | None = None
    episodic_dir: Path | None = None
    embedder_model: str = "bge-m3"

    def resolved_semantic_db(self) -> Path:
        return self.semantic_db_path or (self.agent_home / "memory" / "semantic.db")

    def resolved_trace_log(self) -> Path:
        return self.trace_log_path or (self.data_dir / "trace.jsonl")


    def resolved_episodic_dir(self) -> Path:
        return self.episodic_dir or (self.agent_home / "memory" / "episodic")


def load_settings() -> HarnessSettings:
    return HarnessSettings()
