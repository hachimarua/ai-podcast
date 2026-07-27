"""Suspend-safe daily wall-clock scheduling with persisted deduplication."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


POLL_SECONDS = 30
RUN_LEASE_SECONDS = 10 * 60
ON_TIME_GRACE_SECONDS = 60


@dataclass(frozen=True)
class DailyRun:
    job_id: str
    run_date: str
    scheduled_for: datetime
    started_at: datetime
    trigger: str
    delay_seconds: int


def load_schedule_state(path: Path) -> dict:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_schedule_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def scheduled_for_today(check_time: tuple[int, int], now: datetime) -> datetime:
    hour, minute = check_time
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def poll_delay(
    check_time: tuple[int, int],
    now: datetime,
    *,
    poll_seconds: int = POLL_SECONDS,
) -> float:
    remaining = (scheduled_for_today(check_time, now) - now).total_seconds()
    if remaining > 0:
        return max(0.1, min(float(poll_seconds), remaining))
    return float(poll_seconds)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _trigger_for(
    now: datetime,
    scheduled_for: datetime,
    previous_tick: datetime | None,
) -> str:
    delay_seconds = max(0, int((now - scheduled_for).total_seconds()))
    if delay_seconds <= ON_TIME_GRACE_SECONDS:
        return "scheduled"
    if previous_tick is None:
        return "startup_catchup"
    if (now - previous_tick).total_seconds() > POLL_SECONDS * 2:
        return "wake_catchup"
    return "catchup"


def claim_daily_run(
    state_path: Path,
    job_id: str,
    check_time: tuple[int, int],
    now: datetime,
    *,
    previous_tick: datetime | None = None,
) -> DailyRun | None:
    scheduled_for = scheduled_for_today(check_time, now)
    if now < scheduled_for:
        return None

    run_date = scheduled_for.date().isoformat()
    state = load_schedule_state(state_path)
    jobs = state.setdefault("jobs", {})
    entry = jobs.get(job_id, {})
    if entry.get("run_date") == run_date:
        if entry.get("status") in {"success", "failed"}:
            return None
        if entry.get("status") == "running":
            started_at = _parse_datetime(entry.get("started_at"))
            if started_at is not None and now - started_at < timedelta(seconds=RUN_LEASE_SECONDS):
                return None

    delay_seconds = max(0, int((now - scheduled_for).total_seconds()))
    trigger = _trigger_for(now, scheduled_for, previous_tick)
    run = DailyRun(
        job_id=job_id,
        run_date=run_date,
        scheduled_for=scheduled_for,
        started_at=now,
        trigger=trigger,
        delay_seconds=delay_seconds,
    )
    jobs[job_id] = {
        **entry,
        "delay_seconds": delay_seconds,
        "run_date": run_date,
        "scheduled_for": scheduled_for.isoformat(),
        "started_at": now.isoformat(),
        "status": "running",
        "trigger": trigger,
    }
    state["version"] = 1
    save_schedule_state(state_path, state)
    return run


def finish_daily_run(
    state_path: Path,
    run: DailyRun,
    *,
    success: bool,
    completed_at: datetime,
    error_type: str = "",
) -> None:
    state = load_schedule_state(state_path)
    jobs = state.setdefault("jobs", {})
    entry = jobs.setdefault(run.job_id, {})
    if entry.get("run_date") != run.run_date:
        return
    entry["completed_at"] = completed_at.isoformat()
    entry["status"] = "success" if success else "failed"
    entry["error_type"] = error_type
    entry["last_attempted_local_date"] = run.run_date
    if success:
        entry["last_completed_local_date"] = run.run_date
    state["version"] = 1
    save_schedule_state(state_path, state)
