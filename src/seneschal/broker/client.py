"""Broker client for agent-side code — talks to broker via Unix socket."""

from __future__ import annotations

import socket

from seneschal.common.config import load_settings
from seneschal.common.schemas import BrokerRequest, BrokerResponse


def call_broker(request: BrokerRequest) -> BrokerResponse:
    settings = load_settings()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(str(settings.broker_socket))
        sock.sendall(request.model_dump_json().encode())
        data = sock.recv(65536).decode()
    return BrokerResponse.model_validate_json(data)
