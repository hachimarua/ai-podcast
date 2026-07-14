"""Non-public Phase 10 trial artifact handling."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from episode_history import (
    public_deterministic_checks,
    public_qa_summary,
    safe_public_news_urls,
    safe_public_text,
    sha256_file,
)


class Phase10TrialError(ValueError):
    """Raised when non-public trial settings are invalid."""


TRIAL_ANCHOR_TOKENS = {
    "ai_agents": ("agent", "agents", "aiエージェント", "ai エージェント"),
}


def phase10_trial_enabled(value: str | None = None) -> bool:
    raw = value if value is not None else os.getenv("PHASE10_TRIAL_MODE", "false")
    normalized = str(raw).strip().lower()
    if normalized not in {"true", "false"}:
        raise Phase10TrialError("PHASE10_TRIAL_MODE must be true or false")
    return normalized == "true"


def phase10_trial_anchor(value: str | None = None) -> str | None:
    raw = value if value is not None else os.getenv("PHASE10_TRIAL_ANCHOR", "")
    normalized = str(raw).strip().lower()
    if not normalized:
        return None
    if normalized not in TRIAL_ANCHOR_TOKENS:
        raise Phase10TrialError(
            "PHASE10_TRIAL_ANCHOR must be one of: "
            + ", ".join(sorted(TRIAL_ANCHOR_TOKENS))
        )
    return normalized


def match_news_for_trial_anchor(news_items: list[dict], anchor: str):
    """Match a closed non-private anchor against public news titles only."""
    if anchor not in TRIAL_ANCHOR_TOKENS:
        raise Phase10TrialError("unknown Phase 10 trial anchor")
    tokens = TRIAL_ANCHOR_TOKENS[anchor]
    matched = []
    unmatched = []
    for item in news_items:
        title = str(item.get("title", "")).casefold()
        candidate = item.copy()
        if any(token in title for token in tokens):
            candidate["matched_words"] = [anchor]
            matched.append(candidate)
        else:
            unmatched.append(candidate)
    return matched, unmatched


def trial_paths(base_dir: str | os.PathLike[str], run_now: datetime) -> dict[str, Path]:
    trial_id = run_now.strftime("trial_%Y%m%d_%H%M%S_%f")
    directory = Path(base_dir) / "phase10_trials" / trial_id
    return {
        "directory": directory,
        "script": directory / "script.txt",
        "audio": directory / "podcast.mp3",
        "report": directory / "trial_report.json",
    }


def build_trial_report(
    *,
    trial_id: str,
    generated_at: str,
    editorial_profile_version: str | None,
    format_config_version: str,
    public_topic: str,
    news_urls: list[str],
    script: str,
    audio_path: str | os.PathLike[str],
    deterministic_checks: dict,
    qa_result: dict | None,
) -> dict:
    if not trial_id.startswith("trial_"):
        raise Phase10TrialError("invalid trial id")
    return {
        "schema_version": 1,
        "trial_id": trial_id,
        "trial_status": "ready_for_listening",
        "generated_at": generated_at,
        "episode_format": "lab",
        "editorial_profile_version": editorial_profile_version,
        "format_config_version": format_config_version,
        "public_topic": safe_public_text(
            public_topic, fallback="最新AIニュース", max_length=160
        ),
        "news_urls": safe_public_news_urls(news_urls),
        "script_sha256": hashlib.sha256(script.encode("utf-8")).hexdigest(),
        "audio_sha256": sha256_file(audio_path),
        "deterministic_checks": public_deterministic_checks(deterministic_checks),
        "qa_summary": public_qa_summary(qa_result),
    }


def write_trial_report_atomic(path: str | os.PathLike[str], report: dict) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=destination.parent, delete=False, prefix=".trial-"
    ) as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, destination)
    return destination
