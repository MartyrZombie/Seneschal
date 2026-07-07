"""Scheduler CLI."""

from __future__ import annotations

import argparse

from seneschal.scheduler.injector import SchedulerInjector


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject scheduler command")
    parser.add_argument("--task", required=True)
    parser.add_argument("--body", required=True)
    args = parser.parse_args()
    injector = SchedulerInjector()
    path = injector.inject(args.body, args.task)
    print(f"Injected scheduler command to {path}")


if __name__ == "__main__":
    main()
