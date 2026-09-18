"""Generate the radio script with OpenAI, and say plainly why it did not.

The caller falls back to Gemini whenever this returns no text, so every failure
path here ends in a short, closed ``error_category`` instead of an exception.
Those categories are written to the public manifest, which is how fallbacks are
counted later; they never carry response bodies, prompts, or key material.

Plain HTTP is used on purpose: it keeps the dependency list unchanged and the
usage payload visible, the same way scripts/llm_canary.py talks to the API.
"""

from __future__ import annotations

import os
import time

import requests

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_SCRIPT_MODEL = "gpt-5.6-terra"
DEFAULT_MAX_OUTPUT_TOKENS = 16000
TIMEOUT = (10, 180)
RETRY_DELAYS = (5, 15, 30)
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}

# Closed vocabulary. episode_history.PUBLIC_CHECK_STRINGS must list every value.
ERROR_CATEGORIES = (
    "openai_unconfigured",
    "openai_quota",
    "openai_auth",
    "openai_bad_request",
    "openai_transient_exhausted",
    "openai_incomplete",
    "openai_empty_output",
    "openai_error",
)


def openai_script_model() -> str:
    return (os.getenv("OPENAI_SCRIPT_MODEL") or "").strip() or DEFAULT_OPENAI_SCRIPT_MODEL


def _max_output_tokens() -> int:
    try:
        value = int(os.getenv("OPENAI_SCRIPT_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS))
    except ValueError:
        return DEFAULT_MAX_OUTPUT_TOKENS
    return value if value > 0 else DEFAULT_MAX_OUTPUT_TOKENS


def _text_from_response(payload: dict) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    chunks = []
    for item in payload.get("output", []) or []:
        for part in item.get("content", []) or []:
            if part.get("type") in {"output_text", "text"} and part.get("text"):
                chunks.append(part["text"])
    return "\n".join(chunks)


def _is_quota_error(response: requests.Response) -> bool:
    """A 429 for an exhausted balance will not recover by waiting."""
    try:
        error = (response.json() or {}).get("error") or {}
    except ValueError:
        return False
    return error.get("code") == "insufficient_quota" or error.get("type") == "insufficient_quota"


def _category_for_status(status: int) -> str:
    if status in {401, 403}:
        return "openai_auth"
    if status in {400, 404, 409, 422}:
        return "openai_bad_request"
    return "openai_error"


def generate_with_openai(
    system_instruction: str,
    prompt: str,
    *,
    sleep=time.sleep,
    post=requests.post,
) -> tuple[str | None, dict]:
    """Return ``(text, info)``. ``text`` is ``None`` when the caller should fall back."""
    model = openai_script_model()
    info: dict = {"provider": "openai", "model": model, "attempts": 0}

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key or api_key.startswith("YOUR_"):
        info["error_category"] = "openai_unconfigured"
        return None, info

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "instructions": system_instruction,
        "input": prompt,
        "max_output_tokens": _max_output_tokens(),
    }

    max_attempts = len(RETRY_DELAYS) + 1
    for attempt in range(1, max_attempts + 1):
        info["attempts"] = attempt
        started = time.monotonic()
        category = None
        status = None
        try:
            response = post(OPENAI_RESPONSES_URL, headers=headers, json=body, timeout=TIMEOUT)
            status = response.status_code
        except (requests.Timeout, requests.ConnectionError):
            category = "transient"
        except requests.RequestException:
            info["error_category"] = "openai_error"
            return None, info

        if category is None and status == 200:
            payload = response.json()
            usage = payload.get("usage") or {}
            info.update({
                "latency_ms": int((time.monotonic() - started) * 1000),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "reasoning_tokens": (usage.get("output_tokens_details") or {}).get("reasoning_tokens"),
                "total_tokens": usage.get("total_tokens"),
            })
            if payload.get("status") not in (None, "completed"):
                # 途中で切れた台本は音声にすると事故になるので、使わずにフォールバックする。
                info["error_category"] = "openai_incomplete"
                return None, info
            text = _text_from_response(payload).strip()
            if not text:
                info["error_category"] = "openai_empty_output"
                return None, info
            return text, info

        if category is None:
            if status == 429 and _is_quota_error(response):
                info["error_category"] = "openai_quota"
                return None, info
            if status in TRANSIENT_STATUS_CODES:
                category = "transient"
            else:
                info["error_category"] = _category_for_status(status)
                info["http_status"] = status
                return None, info

        if attempt < max_attempts:
            delay = RETRY_DELAYS[attempt - 1]
            print(
                f"[OpenAI Retry] 一時的なエラー"
                + (f"(HTTP {status})" if status else "(timeout/接続)")
                + f"のため {delay}秒後に再試行します ({attempt}/{max_attempts})。",
                flush=True,
            )
            sleep(delay)

    info["error_category"] = "openai_transient_exhausted"
    return None, info
