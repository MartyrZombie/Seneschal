"""Capability broker — actions-not-secrets, policy-gated side effects (plan §11)."""

from __future__ import annotations

import argparse
import os
import signal
import socket
import sqlite3
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from seneschal.common.config import HarnessSettings, load_settings
from seneschal.common.schemas import BrokerAction, BrokerRequest, BrokerResponse, TraceEventType
from seneschal.trace.logger import get_trace_logger


POLICY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["version", "actions"],
    "properties": {
        "version": {"type": "integer"},
        "actions": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "enabled": {"type": "boolean"},
                    "rate_limit": {
                        "type": "object",
                        "properties": {
                            "per_hour": {"type": "integer"},
                            "per_minute_per_recipient": {"type": "integer"},
                        },
                    },
                    "recipient_allowlist": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "correspondent_allowlist": {"type": "array", "items": {"type": "string"}},
    },
}


@dataclass
class BrokerPolicy:
    version: int = 1
    actions: dict[str, dict[str, Any]] = field(default_factory=dict)
    correspondent_allowlist: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BrokerPolicy:
        return cls(
            version=data.get("version", 1),
            actions=data.get("actions", {}),
            correspondent_allowlist=data.get("correspondent_allowlist", []),
        )


class PolicyStore:
    """Hot-reloadable policy with fail-closed validation (plan §11)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._current: BrokerPolicy | None = None
        self.reload()

    def reload(self) -> None:
        if not self.path.exists():
            self._current = BrokerPolicy()
            return
        data = yaml.safe_load(self.path.read_text()) or {}
        jsonschema.validate(data, POLICY_SCHEMA)
        self._current = BrokerPolicy.from_dict(data)

    @property
    def policy(self) -> BrokerPolicy:
        assert self._current is not None
        return self._current


class IdempotencyStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency (
                key TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.commit()

    def get(self, key: str) -> BrokerResponse | None:
        row = self.conn.execute(
            "SELECT response_json FROM idempotency WHERE key = ?", (key,)
        ).fetchone()
        if row:
            return BrokerResponse.model_validate_json(row[0])
        return None

    def put(self, response: BrokerResponse) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO idempotency (key, action, response_json) VALUES (?, ?, ?)",
            (response.idempotency_key, response.action.value, response.model_dump_json()),
        )
        self.conn.commit()


class BrokerHandler:
    """Executes broker actions after policy checks. Credentials stay here only."""

    def __init__(self, policy: PolicyStore, idempotency: IdempotencyStore) -> None:
        self.policy = policy
        self.idempotency = idempotency
        self.trace = get_trace_logger()

    def handle(self, request: BrokerRequest) -> BrokerResponse:
        cached = self.idempotency.get(request.idempotency_key)
        if cached:
            return cached

        action_cfg = self.policy.policy.actions.get(request.action.value, {})
        if not action_cfg.get("enabled", False):
            response = BrokerResponse(
                ok=False,
                action=request.action,
                idempotency_key=request.idempotency_key,
                denied_reason="action disabled by policy",
            )
            self._log(request, response)
            return response

        recipient = str(request.payload.get("to", ""))
        allowlist = action_cfg.get("recipient_allowlist", [])
        if allowlist and recipient not in allowlist:
            response = BrokerResponse(
                ok=False,
                action=request.action,
                idempotency_key=request.idempotency_key,
                denied_reason=f"recipient {recipient} not on allowlist",
            )
            self._log(request, response)
            return response

        # Stub: real Twilio integration wired in build step 11
        response = BrokerResponse(
            ok=True,
            action=request.action,
            idempotency_key=request.idempotency_key,
            message="accepted (stub)",
            external_id=f"stub-{request.idempotency_key[:8]}",
        )
        self.idempotency.put(response)
        self._log(request, response)
        return response

    def _log(self, request: BrokerRequest, response: BrokerResponse) -> None:
        self.trace.emit(
            request.idempotency_key,
            TraceEventType.BROKER,
            "broker",
            "action_handled",
            action=request.action.value,
            ok=response.ok,
            denied_reason=response.denied_reason,
        )


def get_peer_credentials(conn: socket.socket) -> tuple[int, int, int]:
    """Return (pid, uid, gid) via SO_PEERCRED (Linux)."""
    SO_PEERCRED = 17
    creds = conn.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize("3i"))
    return struct.unpack("3i", creds)  # type: ignore[return-value]


class BrokerServer:
    def __init__(self, settings: HarnessSettings | None = None) -> None:
        self.settings = settings or load_settings()
        policy_path = self.settings.config_dir / "broker_policy.yaml"
        self.policy = PolicyStore(policy_path)
        db_path = self.settings.data_dir / "broker_idempotency.db"
        self.idempotency = IdempotencyStore(db_path)
        self.handler = BrokerHandler(self.policy, self.idempotency)

    def serve(self) -> None:
        sock_path = self.settings.broker_socket
        sock_path.parent.mkdir(parents=True, exist_ok=True)
        if sock_path.exists():
            sock_path.unlink()

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        os.chmod(sock_path, 0o660)
        server.listen(5)

        def on_sighup(_signum: int, _frame: object) -> None:
            try:
                self.policy.reload()
            except Exception:
                pass  # fail-closed: keep last-good policy

        signal.signal(signal.SIGHUP, on_sighup)

        while True:
            conn, _ = server.accept()
            with conn:
                _pid, uid, _gid = get_peer_credentials(conn)
                data = conn.recv(65536).decode()
                if not data:
                    continue
                request = BrokerRequest.model_validate_json(data)
                response = self.handler.handle(request)
                conn.sendall(response.model_dump_json().encode())


def main() -> None:
    parser = argparse.ArgumentParser(description="Seneschal capability broker")
    parser.add_argument("--once", action="store_true", help="Handle one request from stdin")
    args = parser.parse_args()

    server = BrokerServer()
    if args.once:
        raw = input()
        request = BrokerRequest.model_validate_json(raw)
        print(server.handler.handle(request).model_dump_json())
    else:
        server.serve()


if __name__ == "__main__":
    main()
