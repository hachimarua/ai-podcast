"""Gemini-based podcast QA that runs in non-blocking shadow mode."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from episode_history import public_qa_summary, safe_public_text
from gemini_models import (
    DEFAULT_AUDIO_QA_MODEL,
    normalize_gemini_model,
    uses_legacy_sampling_parameters,
)


SAFE_IMPROVEMENT_BY_CATEGORY = {
    "pronunciation": "発音ルールを確認する",
    "speaker": "話者切替ルールを確認する",
    "bgm": "BGM音量設定を確認する",
    "silence": "無音区間の生成条件を確認する",
    "clipping": "音量ピーク設定を確認する",
    "pacing": "読み上げ速度と間を確認する",
    "repetition": "台本の重複検査を確認する",
    "format": "番組形式の生成条件を確認する",
    "other": "音声品質を人間が確認する",
}


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, prefix=".public-qa-"
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def sanitize_public_proposal(proposal: dict) -> dict:
    """Sanitize proposal fields while preserving structured evidence and suggested changes."""
    issues = []
    raw_issues = proposal.get("evidence", [])
    if isinstance(raw_issues, list):
        for raw_issue in raw_issues:
            if not isinstance(raw_issue, dict):
                continue
            category = raw_issue.get("category")
            severity = raw_issue.get("severity")
            timestamp = raw_issue.get("timestamp")
            if category not in {
                "pronunciation",
                "speaker",
                "bgm",
                "silence",
                "clipping",
                "pacing",
                "repetition",
                "format",
                "other",
            }:
                continue
            if severity not in {"info", "warning", "critical"}:
                continue
            if not isinstance(timestamp, str) or not re.fullmatch(r"unknown|\d{2}:\d{2}", timestamp):
                timestamp = "unknown"

            issue_dict = {
                "category": category,
                "severity": severity,
                "timestamp": timestamp,
            }
            evidence_text = raw_issue.get("evidence")
            if isinstance(evidence_text, str) and evidence_text.strip():
                safe_ev = safe_public_text(evidence_text, fallback="", max_length=300)
                if safe_ev:
                    issue_dict["evidence"] = safe_ev
            issues.append(issue_dict)

    suggested_changes = []
    raw_suggestions = proposal.get("suggested_changes", [])
    if isinstance(raw_suggestions, list):
        for item in raw_suggestions:
            if isinstance(item, str) and item.strip():
                safe_item = safe_public_text(item, fallback="", max_length=200)
                if safe_item:
                    suggested_changes.append(safe_item)
    if not suggested_changes and issues:
        suggested_changes = list(dict.fromkeys(
            SAFE_IMPROVEMENT_BY_CATEGORY[issue["category"]]
            for issue in issues
        ))

    summary = safe_public_text(
        proposal.get("summary", ""),
        fallback="音声品質の確認が必要です。",
        max_length=200,
    )

    overall_score = proposal.get("overall_score")
    if not (isinstance(overall_score, int) and 1 <= overall_score <= 5):
        overall_score = None

    updated = dict(proposal)
    updated["summary"] = summary
    updated["overall_score"] = overall_score
    updated["evidence"] = issues[:10]
    updated["suggested_changes"] = suggested_changes[:10]
    return updated


def sanitize_public_report_tree(reports_dir: str | os.PathLike[str]) -> None:
    """Migrate previously committed QA reports onto the current public boundary."""
    root = Path(reports_dir)
    for path in sorted((root / "pending").glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            _write_json_atomic(path, sanitize_public_proposal(payload))
    for path in sorted((root / "evaluations").glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            _write_json_atomic(path, public_qa_summary(payload) or {})


class AudioIssue(BaseModel):
    category: Literal[
        "pronunciation",
        "speaker",
        "bgm",
        "silence",
        "clipping",
        "pacing",
        "repetition",
        "format",
        "other",
    ]
    severity: Literal["info", "warning", "critical"]
    timestamp: str = Field(description="問題が始まるMM:SS。特定不能ならunknown。")
    evidence: str = Field(description="実際に聞こえた問題の簡潔な説明。")
    suggested_change: str = Field(description="次回生成へ適用できる具体的な改善案。")


class AudioQAAnalysis(BaseModel):
    summary: str
    overall_score: int = Field(ge=1, le=5)
    speech_clarity_score: int = Field(ge=1, le=5)
    dialogue_naturalness_score: int = Field(ge=1, le=5)
    bgm_balance_score: int = Field(ge=1, le=5)
    pacing_score: int = Field(ge=1, le=5)
    has_internal_repetition: bool
    requires_human_review: bool
    issues: list[AudioIssue]


QA_PROMPT = """
この日本語AI学習ラジオを、公開後の品質監査担当として最後まで聞いてください。

評価対象:
- ケンジとアミの音声が明瞭で、話者の切り替えが不自然でないか
- 誤読、記号の読み上げ、文の途中切れ、同じ文の不自然な反復がないか
- BGMが声を覆っていないか、急な音量変化やクリッピングがないか
- 間、テンポ、会話の応酬が通勤中に聞きやすいか
- 番組内で同じ説明を何度も繰り返していないか

音声から確認できない事実は推測しないでください。問題を挙げる場合はMM:SSの時刻と、
実際に聞こえた根拠を付けてください。単なる好みはinfoとし、人間の確認が必要な問題だけ
requires_human_reviewをtrueにしてください。
""".strip()


def analyze_audio(client, model: str, audio_path: str | os.PathLike[str]) -> AudioQAAnalysis:
    uploaded = client.files.upload(file=str(audio_path))
    try:
        config_kwargs = {
            "response_mime_type": "application/json",
            "response_schema": AudioQAAnalysis,
        }
        if uses_legacy_sampling_parameters(model):
            config_kwargs["temperature"] = 0.0
        response = client.models.generate_content(
            model=model,
            contents=[uploaded, QA_PROMPT],
            config=types.GenerateContentConfig(**config_kwargs),
        )
        if response.parsed:
            return response.parsed
        return AudioQAAnalysis.model_validate(json.loads(response.text))
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception as exc:
            print(f"[Warning] Temporary Gemini QA file cleanup failed: {type(exc).__name__}")


def run_shadow_audio_qa(
    audio_path: str | os.PathLike[str], model: str | None = None
) -> dict:
    """Return a bounded QA result. Errors are recorded but never block publishing."""
    load_dotenv()
    selected_model = normalize_gemini_model(
        model or os.getenv("GEMINI_AUDIO_QA_MODEL"), default=DEFAULT_AUDIO_QA_MODEL
    )
    if os.getenv("ENABLE_GEMINI_AUDIO_QA", "true").lower() != "true":
        return {"status": "disabled", "model": selected_model, "issues": []}

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or "YOUR_GEMINI" in api_key:
        return {
            "status": "unavailable",
            "model": selected_model,
            "error_type": "missing_api_key",
            "issues": [],
        }

    try:
        analysis = analyze_audio(genai.Client(api_key=api_key), selected_model, audio_path)
        return {
            "status": "completed",
            "model": selected_model,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            **analysis.model_dump(),
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "model": selected_model,
            "error_type": type(exc).__name__,
            "issues": [],
        }


def needs_improvement_proposal(qa_result: dict) -> bool:
    if qa_result.get("status") != "completed":
        return False
    if qa_result.get("requires_human_review"):
        return True
    return any(
        issue.get("severity") in {"warning", "critical"}
        for issue in qa_result.get("issues", [])
    )


def write_improvement_proposal(
    *,
    qa_result: dict,
    episode_id: str,
    broadcast_date: str,
    reports_dir: str | os.PathLike[str],
) -> Path | None:
    if not needs_improvement_proposal(qa_result):
        return None

    directory = Path(reports_dir) / "pending"
    directory.mkdir(parents=True, exist_ok=True)
    proposal_id = f"qa-{episode_id}"
    severity_order = {"info": 0, "warning": 1, "critical": 2}
    raw_issues = qa_result.get("issues", [])
    severity = max(
        (
            issue.get("severity", "info")
            for issue in raw_issues
            if isinstance(issue, dict) and issue.get("severity") in severity_order
        ),
        key=lambda value: severity_order.get(value, 0),
        default="warning",
    )
    raw_suggested = [
        issue.get("suggested_change")
        for issue in raw_issues
        if isinstance(issue, dict) and issue.get("suggested_change")
    ]
    proposal = sanitize_public_proposal({
        "schema_version": 1,
        "proposal_id": proposal_id,
        "episode_id": episode_id,
        "broadcast_date": broadcast_date,
        "severity": severity,
        "category": "audio_quality",
        "summary": qa_result.get("summary", "音声品質の確認が必要です。"),
        "overall_score": qa_result.get("overall_score"),
        "evidence": raw_issues,
        "suggested_changes": raw_suggested,
        "safe_auto_apply": False,
        "status": "pending",
        "decision_reason": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "decided_at": None,
    })
    destination = directory / f"{proposal_id}.json"
    _write_json_atomic(destination, proposal)
    return destination


def write_public_evaluation(
    qa_result: dict, episode_id: str, reports_dir: str | os.PathLike[str]
) -> Path:
    """Persist only closed QA fields in the public report tree."""
    directory = Path(reports_dir) / "evaluations"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{episode_id}.json"
    payload = public_qa_summary(qa_result) or {}
    _write_json_atomic(destination, payload)
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio")
    parser.add_argument("--episode-id", required=True)
    parser.add_argument("--broadcast-date", required=True)
    parser.add_argument("--reports-dir", default="quality_reports")
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    result = run_shadow_audio_qa(args.audio, model=args.model)
    proposal = write_improvement_proposal(
        qa_result=result,
        episode_id=args.episode_id,
        broadcast_date=args.broadcast_date,
        reports_dir=args.reports_dir,
    )
    write_public_evaluation(result, args.episode_id, args.reports_dir)
    print(f"Gemini audio QA status: {result.get('status')}")
    print(f"Improvement proposal: {proposal or 'none'}")


if __name__ == "__main__":
    main()
