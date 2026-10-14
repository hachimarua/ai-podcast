"""Generate the radio script with SB Intuitions Sarashina, and say plainly why it did not.

Sarashina is the primary script writer from 2026-10-15 (free beta API). The caller
falls back to OpenAI (then Gemini) whenever this returns no text, so every failure
path ends in a short, closed ``error_category`` instead of an exception. Those
categories go to the public manifest; they never carry response bodies, prompts,
or key material.

API facts this relies on (docs.sarashina.ai, checked 2026-10-14):
- POST https://api.sarashina.ai/v1/chat/completions, ``Authorization: Bearer``
- output length is ``max_completion_tokens`` (1..8000); ``max_tokens`` and other
  undocumented fields return 400 "Invalid JSON or disallowed fields"
- sarashina3-mini allows 6 requests per fixed 60-second window, and a 429 carries
  no Retry-After header, so the waits below are long and few
- no reasoning parameter exists
"""

from __future__ import annotations

import os
import time

import requests

SARASHINA_CHAT_URL = "https://api.sarashina.ai/v1/chat/completions"
DEFAULT_SARASHINA_SCRIPT_MODEL = "sarashina3-mini"
MAX_COMPLETION_TOKENS = 8000
TIMEOUT = (10, 120)
# 毎分6回の固定窓。すぐ投げ直すと制限が延びることがあるので、窓をまたぐ長さで待つ。
RETRY_DELAYS = (20, 40)
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}

# Closed vocabulary. episode_history.PUBLIC_CHECK_STRINGS must list every value.
ERROR_CATEGORIES = (
    "sarashina_unconfigured",
    "sarashina_auth",
    "sarashina_unavailable",
    "sarashina_bad_request",
    "sarashina_transient_exhausted",
    "sarashina_incomplete",
    "sarashina_empty_output",
    "sarashina_error",
)


def sarashina_script_model() -> str:
    return (os.getenv("SARASHINA_SCRIPT_MODEL") or "").strip() or DEFAULT_SARASHINA_SCRIPT_MODEL


def _category_for_status(status: int) -> str:
    if status in {401, 403}:
        return "sarashina_auth"
    if status in {404, 410}:
        # ベータ終了やモデル名の廃止。待っても戻らない。
        return "sarashina_unavailable"
    if status in {400, 409, 422}:
        return "sarashina_bad_request"
    return "sarashina_error"


def generate_with_sarashina(
    system_instruction: str,
    prompt: str,
    *,
    sleep=time.sleep,
    post=requests.post,
) -> tuple[str | None, dict]:
    """Return ``(text, info)``. ``text`` is ``None`` when the caller should fall back."""
    model = sarashina_script_model()
    info: dict = {"provider": "sarashina", "model": model, "attempts": 0}

    api_key = os.getenv("SARASHINA_API_KEY", "")
    if not api_key or api_key.startswith("YOUR_"):
        info["error_category"] = "sarashina_unconfigured"
        return None, info

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt},
        ],
    }

    max_attempts = len(RETRY_DELAYS) + 1
    for attempt in range(1, max_attempts + 1):
        info["attempts"] = attempt
        started = time.monotonic()
        status = None
        try:
            response = post(SARASHINA_CHAT_URL, headers=headers, json=body, timeout=TIMEOUT)
            status = response.status_code
        except (requests.Timeout, requests.ConnectionError):
            pass
        except requests.RequestException:
            info["error_category"] = "sarashina_error"
            return None, info

        if status == 200:
            try:
                payload = response.json()
                choice = (payload.get("choices") or [{}])[0]
            except (ValueError, AttributeError, IndexError):
                info["error_category"] = "sarashina_error"
                return None, info
            usage = payload.get("usage") or {}
            info.update({
                "latency_ms": int((time.monotonic() - started) * 1000),
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            })
            if choice.get("finish_reason") not in (None, "stop"):
                # 途中で切れた台本は音声にすると事故になるので、使わずにフォールバックする。
                info["error_category"] = "sarashina_incomplete"
                return None, info
            text = str((choice.get("message") or {}).get("content") or "").strip()
            if not text:
                info["error_category"] = "sarashina_empty_output"
                return None, info
            return text, info

        if status is not None and status not in TRANSIENT_STATUS_CODES:
            info["error_category"] = _category_for_status(status)
            info["http_status"] = status
            return None, info

        if attempt < max_attempts:
            delay = RETRY_DELAYS[attempt - 1]
            print(
                "[Sarashina Retry] 一時的なエラー"
                + (f"(HTTP {status})" if status else "(timeout/接続)")
                + f"のため {delay}秒後に再試行します ({attempt}/{max_attempts})。",
                flush=True,
            )
            sleep(delay)

    info["error_category"] = "sarashina_transient_exhausted"
    return None, info
