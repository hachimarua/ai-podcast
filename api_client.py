"""Small, fail-closed HTTP helpers for external APIs."""

from __future__ import annotations

import time
from typing import Any

import requests


DEFAULT_TIMEOUT = (5, 30)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ExternalServiceError(RuntimeError):
    """Raised when an external dependency cannot return a valid response."""


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    safe_to_retry: bool = False,
    max_attempts: int = 3,
    **kwargs: Any,
) -> dict[str, Any]:
    """Request JSON with bounded retries and redacted error messages.

    ``safe_to_retry`` must only be enabled for reads or idempotent updates. It is
    intentionally disabled for create operations to avoid duplicate Notion pages.
    """

    attempts = max_attempts if safe_to_retry else 1
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)

    for attempt in range(1, attempts + 1):
        try:
            response = session.request(method, url, **kwargs)
        except requests.RequestException as exc:
            if attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 4))
                continue
            raise ExternalServiceError(
                f"External request failed: {method.upper()} {url} ({type(exc).__name__})"
            ) from exc

        if 200 <= response.status_code < 300:
            try:
                payload = response.json()
            except ValueError as exc:
                raise ExternalServiceError(
                    f"External service returned invalid JSON: {method.upper()} {url}"
                ) from exc
            if not isinstance(payload, dict):
                raise ExternalServiceError(
                    f"External service returned unexpected JSON: {method.upper()} {url}"
                )
            return payload

        if response.status_code in RETRYABLE_STATUS_CODES and attempt < attempts:
            retry_after = response.headers.get("Retry-After")
            try:
                delay = min(float(retry_after), 10) if retry_after else min(2 ** (attempt - 1), 4)
            except ValueError:
                delay = min(2 ** (attempt - 1), 4)
            time.sleep(delay)
            continue

        raise ExternalServiceError(
            f"External service returned HTTP {response.status_code}: {method.upper()} {url}"
        )

    raise ExternalServiceError(f"External request exhausted retries: {method.upper()} {url}")


def request_bytes(
    session: requests.Session,
    method: str,
    url: str,
    *,
    max_attempts: int = 3,
    **kwargs: Any,
) -> bytes:
    """Fetch bytes for a read-only resource with bounded retries."""

    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    for attempt in range(1, max_attempts + 1):
        try:
            response = session.request(method, url, **kwargs)
        except requests.RequestException as exc:
            if attempt < max_attempts:
                time.sleep(min(2 ** (attempt - 1), 4))
                continue
            raise ExternalServiceError(
                f"External download failed: {method.upper()} {url} ({type(exc).__name__})"
            ) from exc

        if 200 <= response.status_code < 300:
            return response.content
        if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_attempts:
            time.sleep(min(2 ** (attempt - 1), 4))
            continue
        raise ExternalServiceError(
            f"External download returned HTTP {response.status_code}: {method.upper()} {url}"
        )

    raise ExternalServiceError(f"External download exhausted retries: {method.upper()} {url}")
