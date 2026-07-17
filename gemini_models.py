"""Shared Gemini model selection helpers."""

from __future__ import annotations


DEFAULT_GEMINI_MODEL = "gemini-3.1-pro-preview"
DEFAULT_GEMINI_FALLBACK_MODEL = "gemini-2.5-flash"

MODEL_ALIASES = {
    "gemini-3.1-pro": DEFAULT_GEMINI_MODEL,
}


def normalize_gemini_model(model: str | None, default: str = DEFAULT_GEMINI_MODEL) -> str:
    selected = (model or "").strip()
    if not selected:
        return default
    return MODEL_ALIASES.get(selected, selected)
