"""Persistent Antigravity sidecar loop for podcast review notifications."""

from __future__ import annotations

import argparse
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from antigravity_review_notifier import (
    NotifierError,
    default_state_path,
    notify_daily_report,
    notify_pending,
)


def run_obsidian_intake(workspace: Path) -> str:
    """Run intake in an isolated child process; the notifier never reads .env."""
    python = workspace / "venv" / "bin" / "python"
    script = workspace / "obsidian_inbox_adapter.py"
    result = subprocess.run(
        [str(python), str(script)],
        cwd=workspace,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Obsidian intake exited with code {result.returncode}")
    return result.stdout.strip()


def parse_daily_check_time(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use HH:MM, for example 06:30") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise argparse.ArgumentTypeError("Daily check time must be between 00:00 and 23:59")
    return hour, minute


def seconds_until_next_daily_check(
    daily_check_time: tuple[int, int],
    *,
    now: datetime | None = None,
) -> int:
    now = now or datetime.now()
    hour, minute = daily_check_time
    next_check = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_check <= now:
        next_check += timedelta(days=1)
    return max(300, int((next_check - now).total_seconds()))


def run_checks(workspace: Path) -> None:
    try:
        summary = run_obsidian_intake(workspace)
        print(summary or "Obsidian intake complete", flush=True)
    except Exception as exc:
        print(f"Obsidian intake deferred safely: {type(exc).__name__}", flush=True)
    try:
        count = notify_daily_report(workspace, default_state_path())
        print(f"Daily audit report check complete: {count} created", flush=True)
    except NotifierError as exc:
        print(f"Daily audit report check deferred: {exc}", flush=True)
    except Exception as exc:
        print(f"Daily audit report check failed safely: {type(exc).__name__}", flush=True)
    try:
        count = notify_pending(workspace, default_state_path())
        print(f"Review notification check complete: {count} created", flush=True)
    except NotifierError as exc:
        print(f"Review notification check deferred: {exc}", flush=True)
    except Exception as exc:
        print(f"Review notification check failed safely: {type(exc).__name__}", flush=True)


def run_loop(
    workspace: Path,
    interval_seconds: int,
    *,
    daily_check_time: tuple[int, int] | None = None,
) -> None:
    print(f"AI radio review sidecar started: {workspace}", flush=True)
    while True:
        run_checks(workspace)
        if daily_check_time:
            sleep_seconds = seconds_until_next_daily_check(daily_check_time)
            hour, minute = daily_check_time
            print(f"Next review notification check scheduled for {hour:02d}:{minute:02d}", flush=True)
        else:
            sleep_seconds = interval_seconds
        time.sleep(sleep_seconds)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=int, default=86400)
    parser.add_argument(
        "--daily-check-time",
        type=parse_daily_check_time,
        default=None,
        help="Local daily HH:MM check time. Runs once at startup, then at this time.",
    )
    args = parser.parse_args()
    run_loop(
        args.workspace,
        max(300, args.interval_seconds),
        daily_check_time=args.daily_check_time,
    )


if __name__ == "__main__":
    main()
