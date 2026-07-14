"""Validated, public-safe editorial profile for podcast script generation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


PROFILE_PATH = Path(__file__).resolve().parent / "config" / "editorial_profile.json"


EXPERIENCE_BANDS = {
    "workflow_builder_operator": "AIを使って仕組みを設計・検証・運用している実践者",
}

WORKING_MODES = {
    "multi_model_use": "複数のAIを目的に応じて使い分けている",
    "coding_agent_collaboration": "AIコーディングエージェントと共同で開発・検証している",
    "api_workflow_automation": "APIを含むワークフロー自動化を実践している",
    "knowledge_base_operations": "知識ベースを継続的に整理・再利用している",
    "github_delivery": "GitHubを使った変更管理と配信を実践している",
    "serverless_operations": "サーバーレス基盤を使った小規模システムを運用している",
    "mobile_voice_workflows": "音声入力やモバイル起点のワークフローを活用している",
}

AVAILABLE_TOOLS = {
    "chatgpt_and_codex": "ChatGPTとCodex",
    "claude": "Claude",
    "gemini": "Gemini",
    "notebooklm": "NotebookLM",
    "obsidian": "Obsidian",
    "notion": "Notion",
    "github": "GitHub",
    "cloudflare": "Cloudflare",
    "apple_shortcuts": "Appleショートカット",
}

MASTERED_BASICS = {
    "chat_q_and_a": "AIへの基本的な質問と対話",
    "summarization_rewrite": "要約と文章の書き換え",
    "basic_prompt_structure": "目的・条件・出力形式を指定する基本的なプロンプト設計",
    "generic_tool_comparison": "主要AIツールの一般的な比較",
    "basic_workspace_setup": "プロジェクトやワークスペースの基本設定",
    "basic_no_code_automation": "単純なノーコード自動化",
}

INTEREST_DOMAINS = {
    "ai_agents_and_coding": "AIエージェントとAI支援開発",
    "workflow_automation": "実務ワークフローの自動化",
    "knowledge_management_and_rag": "知識管理、検索、RAGによる再利用",
    "reliability_qa": "AIシステムの安全性、再現性、品質評価",
    "deployment_operations": "継続的な配信と運用改善",
    "voice_first_workflows": "音声を入口にした低負荷な操作",
}

EDITORIAL_PREFERENCES = {
    "implementation_first": "一般論より、具体的な実装方法を優先する",
    "evidence_required": "操作や主張には確認可能な根拠を求める",
    "constraints_required": "期待結果だけでなく制約と適用しない条件も示す",
    "avoid_beginner_tips": "既に習得済みの初歩的Tipsを繰り返さない",
    "no_personal_profile_narration": "プロフィール情報を人物紹介として読み上げない",
}


class EditorialProfileError(ValueError):
    """Raised when the committed editorial profile is missing or unsafe."""


class EditorialProfile(BaseModel):
    """Closed-schema profile containing allowlisted enum values only."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    profile_version: str
    approval_status: Literal["pending", "approved"]
    experience_band: Literal[tuple(EXPERIENCE_BANDS)]
    working_modes: list[Literal[tuple(WORKING_MODES)]] = Field(min_length=1, max_length=8)
    available_tools: list[Literal[tuple(AVAILABLE_TOOLS)]] = Field(min_length=1, max_length=10)
    mastered_basics: list[Literal[tuple(MASTERED_BASICS)]] = Field(min_length=1, max_length=8)
    interest_domains: list[Literal[tuple(INTEREST_DOMAINS)]] = Field(min_length=1, max_length=8)
    editorial_preferences: list[Literal[tuple(EDITORIAL_PREFERENCES)]] = Field(
        min_length=1, max_length=8
    )

    @field_validator("profile_version")
    @classmethod
    def validate_profile_version(cls, value: str) -> str:
        if not re.fullmatch(r"editorial-v[1-9][0-9]*", value):
            raise ValueError("profile_version must use the editorial-vN format")
        return value

    @field_validator(
        "working_modes",
        "available_tools",
        "mastered_basics",
        "interest_domains",
        "editorial_preferences",
    )
    @classmethod
    def reject_duplicates(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("profile enum lists must not contain duplicates")
        return values


def load_editorial_profile() -> EditorialProfile:
    """Load the fixed repository profile and reject missing or malformed data."""

    path = PROFILE_PATH
    if path.is_symlink() or path.parent.is_symlink():
        raise EditorialProfileError("editorial profile path must not use symbolic links")
    if not path.is_file():
        raise EditorialProfileError("editorial profile must be a regular committed file")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return EditorialProfile.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise EditorialProfileError("editorial profile is missing, malformed, or unsafe") from exc


def render_editorial_profile(profile: EditorialProfile) -> str:
    """Render only fixed phrases selected by allowlisted enum values."""

    lines = [
        "【番組用編集プロフィール】",
        f"- 想定聴取者: {EXPERIENCE_BANDS[profile.experience_band]}",
        "- 実践済みの作業:",
    ]
    lines.extend(f"  - {WORKING_MODES[value]}" for value in profile.working_modes)
    lines.append("- 利用可能なツール:")
    lines.extend(f"  - {AVAILABLE_TOOLS[value]}" for value in profile.available_tools)
    lines.append("- 既に習得済みの初歩項目（Tipsとして再提案しない）:")
    lines.extend(f"  - {MASTERED_BASICS[value]}" for value in profile.mastered_basics)
    lines.append("- 関心領域:")
    lines.extend(f"  - {INTEREST_DOMAINS[value]}" for value in profile.interest_domains)
    lines.append("- 編集方針:")
    lines.extend(f"  - {EDITORIAL_PREFERENCES[value]}" for value in profile.editorial_preferences)
    lines.append(
        "このプロフィールは編集判断だけに使い、人物紹介として読み上げたり、"
        "記載のない個人属性を推測したりしないでください。"
    )
    return "\n".join(lines)


def get_approved_profile_instruction(profile: EditorialProfile | None = None) -> str:
    """Return the rendered profile only after explicit human approval."""

    if profile is None:
        profile = load_editorial_profile()
    if profile.approval_status != "approved":
        return ""
    return render_editorial_profile(profile)


def get_approved_profile_version() -> str | None:
    profile = load_editorial_profile()
    if profile.approval_status != "approved":
        return None
    return profile.profile_version
