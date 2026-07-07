"""CLI to query unified trace logs."""

from __future__ import annotations

import argparse
import json

from seneschal.common.config import load_settings
from seneschal.trace.logger import query_by_correlation_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Query Seneschal trace logs")
    parser.add_argument("correlation_id", help="request_id / correlation_id to filter")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON lines")
    args = parser.parse_args()

    settings = load_settings()
    events = query_by_correlation_id(settings.resolved_trace_log(), args.correlation_id)
    if args.json:
        for event in events:
            print(event.model_dump_json())
    else:
        for event in events:
            print(f"[{event.timestamp.isoformat()}] {event.event_type.value}/{event.component}: {event.message}")


if __name__ == "__main__":
    main()
