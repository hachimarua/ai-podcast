"""Persistent Antigravity sidecar loop for podcast review notifications."""

from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path

from antigravity_review_notifier import NotifierError, default_state_path, notify_pending


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


def run_loop(workspace: Path, interval_seconds: int) -> None:
    print(f"AI radio review sidecar started: {workspace}", flush=True)
    while True:
        try:
            summary = run_obsidian_intake(workspace)
            print(summary or "Obsidian intake complete", flush=True)
        except Exception as exc:
            print(f"Obsidian intake deferred safely: {type(exc).__name__}", flush=True)
        try:
            count = notify_pending(workspace, default_state_path())
            print(f"Review notification check complete: {count} created", flush=True)
        except NotifierError as exc:
            print(f"Review notification check deferred: {exc}", flush=True)
        except Exception as exc:
            print(f"Review notification check failed safely: {type(exc).__name__}", flush=True)
        time.sleep(interval_seconds)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=int, default=900)
    args = parser.parse_args()
    run_loop(args.workspace, max(300, args.interval_seconds))


if __name__ == "__main__":
    main()
