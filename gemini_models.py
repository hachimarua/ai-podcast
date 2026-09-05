"""Shared Gemini model selection helpers."""

from __future__ import annotations


DEFAULT_GEMINI_MODEL = "gemini-3.7-flash"

# 音声監査（シャドーQA）専用の既定モデル。
# 台本生成モデルとは分離し、音声監査はFlashを使う。
DEFAULT_AUDIO_QA_MODEL = "gemini-3.6-flash"

MODERN_GEMINI_FLASH_PREFIXES = ("gemini-3.6-flash", "gemini-3.7-flash")

MODEL_ALIASES = {
    "gemini-3.1-pro": DEFAULT_GEMINI_MODEL,
}


def normalize_gemini_model(model: str | None, default: str = DEFAULT_GEMINI_MODEL) -> str:
    selected = (model or "").strip()
    if not selected:
        return default
    return MODEL_ALIASES.get(selected, selected)


def uses_legacy_sampling_parameters(model: str) -> bool:
    """Return whether the model still accepts the legacy temperature setting."""
    return not model.startswith(MODERN_GEMINI_FLASH_PREFIXES)
