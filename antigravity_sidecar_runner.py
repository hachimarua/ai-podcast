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
    load_state,
    notify_daily_report,
    notify_pending,
)
from daily_schedule import claim_daily_run, finish_daily_run, poll_delay

# 当日の判定が確定していない状態。生成がGitHub側の遅延で判定時刻に間に合わ
# なかった日と、スリープ復帰直後でoriginを読めず判定を保留した日の両方が入る。
UNSETTLED_VERDICTS = frozenset({"生成結果未確認", "監査未完了"})
# 未確定の日だけ、日中に間隔をあけて確認し直す。確定済みの日はローカルの
# state を読むだけで終わり、ネットワークには出ない。
RECHECK_INTERVAL_SECONDS = 1800
RECHECK_UNTIL = (21, 0)


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


def latest_same_day_report(state_path: Path, now: datetime) -> dict | None:
    """当日分の判定のうち、いちばん新しいものを返す。

    生成が遅れた日は `missing:<日付>` と実エピソードの両方が残るので、
    古いほうの「生成結果未確認」を当日の結論として読まないようにする。
    """
    today = now.date().isoformat()
    daily_reports = load_state(state_path).get("daily_reports", {})
    latest: tuple[str, dict] | None = None
    for key, prior in daily_reports.items():
        if not isinstance(prior, dict):
            continue
        report_date = prior.get("report_date") or (
            key.split(":", 1)[1] if key.startswith("missing:") else None
        )
        if report_date != today:
            continue
        stamp = str(prior.get("notified_at") or "")
        if latest is None or stamp >= latest[0]:
            latest = (stamp, prior)
    return latest[1] if latest else None


def same_day_audit_is_unsettled(state_path: Path, now: datetime) -> bool:
    """当日の監査結果が、まだ確定していないかどうか。

    判定がひとつも書かれていない日（originを読めず保留した日を含む）も
    未確定として扱う。保留を放置すると、その日は誰も監査しないまま終わる。
    """
    report = latest_same_day_report(state_path, now)
    if report is None:
        return True
    return report.get("verdict") in UNSETTLED_VERDICTS


def recheck_same_day_audit(
    workspace: Path,
    state_path: Path | None = None,
    *,
    now: datetime | None = None,
    daily_check_time: tuple[int, int] | None = None,
) -> int:
    """当日の判定が未確定なら、その日のうちにもう一度監査する。

    判定時刻より前と、夜になってからは走らせない。確定済みなら state を
    読むだけで返すので、通常日に追加のネットワーク処理は発生しない。
    """
    state_path = state_path or default_state_path()
    now = now or datetime.now().astimezone()
    if now >= now.replace(hour=RECHECK_UNTIL[0], minute=RECHECK_UNTIL[1],
                          second=0, microsecond=0):
        return 0
    if daily_check_time is not None:
        hour, minute = daily_check_time
        if now < now.replace(hour=hour, minute=minute, second=0, microsecond=0):
            return 0
    if not same_day_audit_is_unsettled(state_path, now):
        return 0
    return notify_daily_report(workspace, state_path, report_date=now.date().isoformat())


def recheck_same_day_audit_on_startup(
    workspace: Path,
    state_path: Path | None = None,
) -> int:
    """On restart only, re-audit a same-day result that was previously missing or incomplete."""
    state_path = state_path or default_state_path()
    today = datetime.now().astimezone().date().isoformat()
    daily_reports = load_state(state_path).get("daily_reports", {})
    for key, prior in daily_reports.items():
        if not isinstance(prior, dict):
            continue
        report_date = prior.get("report_date") or (
            key.split(":", 1)[1] if key.startswith("missing:") else None
        )
        if report_date == today:
            if prior.get("verdict") in UNSETTLED_VERDICTS:
                return notify_daily_report(workspace, state_path, report_date=today)
    return 0


def recheck_missing_generation_on_startup(
    workspace: Path,
    state_path: Path | None = None,
) -> int:
    """Backward compatibility alias for same-day startup audit rechecks."""
    return recheck_same_day_audit_on_startup(workspace, state_path)


def run_loop(
    workspace: Path,
    interval_seconds: int,
    *,
    daily_check_time: tuple[int, int] | None = None,
    schedule_state_path: Path | None = None,
) -> None:
    print(f"AI radio review sidecar started: {workspace}", flush=True)
    if daily_check_time:
        hour, minute = daily_check_time
        schedule_state_path = schedule_state_path or default_state_path().with_name(
            "ai-radio-schedule-state.json"
        )
        print(f"Wall-clock scheduler armed for {hour:02d}:{minute:02d}", flush=True)
        try:
            recovered = recheck_same_day_audit(
                workspace, daily_check_time=daily_check_time
            )
            if recovered:
                print("Same-day recovery audit report created", flush=True)
        except NotifierError as exc:
            print(f"Same-day recovery audit deferred: {exc}", flush=True)
        except Exception as exc:
            print(f"Same-day recovery audit failed safely: {type(exc).__name__}", flush=True)
        previous_tick = None
        last_recheck_at = datetime.now().astimezone()
        while True:
            now = datetime.now().astimezone()
            daily_run = claim_daily_run(
                schedule_state_path,
                "ai-radio-review",
                daily_check_time,
                now,
                previous_tick=previous_tick,
            )
            if daily_run is not None:
                try:
                    run_checks(workspace)
                    finish_daily_run(
                        schedule_state_path,
                        daily_run,
                        success=True,
                        completed_at=datetime.now().astimezone(),
                    )
                    print(
                        f"Daily review complete: trigger={daily_run.trigger} "
                        f"delay_seconds={daily_run.delay_seconds}",
                        flush=True,
                    )
                except Exception as exc:
                    finish_daily_run(
                        schedule_state_path,
                        daily_run,
                        success=False,
                        completed_at=datetime.now().astimezone(),
                        error_type=type(exc).__name__,
                    )
                    print(f"Review sidecar failed safely: {type(exc).__name__}", flush=True)
                last_recheck_at = now
            elif (now - last_recheck_at).total_seconds() >= RECHECK_INTERVAL_SECONDS:
                # 判定時刻に生成が間に合わなかった日と、originを読めず保留した日を、
                # その日のうちに回収する。確定済みの日はここで何もしない。
                try:
                    recovered = recheck_same_day_audit(
                        workspace, now=now, daily_check_time=daily_check_time
                    )
                    if recovered:
                        print("Same-day recheck audit report created", flush=True)
                except NotifierError as exc:
                    print(f"Same-day recheck deferred: {exc}", flush=True)
                except Exception as exc:
                    print(f"Same-day recheck failed safely: {type(exc).__name__}", flush=True)
                last_recheck_at = now
            previous_tick = now
            time.sleep(poll_delay(daily_check_time, now))

    while True:
        run_checks(workspace)
        time.sleep(interval_seconds)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=int, default=86400)
    parser.add_argument("--schedule-state-path", type=Path, default=None)
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
        schedule_state_path=args.schedule_state_path,
    )


if __name__ == "__main__":
    main()
