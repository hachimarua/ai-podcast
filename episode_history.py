"""Privacy-conscious episode history and duplicate detection."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


SCHEMA_VERSION = 1
PIPELINE_VERSION = "phase8"
MINHASH_SIZE = 64
NGRAM_SIZE = 3
TOPIC_SIMILARITY_THRESHOLD = 0.30
PUBLIC_NEWS_SOURCES = {
    "TechCrunch AI", "Google AI Blog", "Hugging Face Blog",
    "arXiv cs.AI (Artificial Intelligence)", "ITmedia AI+", "AI Watch",
}
PUBLIC_CHECK_KEYS = {
    "recent_episode_count", "initial_script_similarity", "final_script_similarity",
    "duplicate_threshold", "used_news_only_fallback", "news_selection",
    "audio_quality", "script_length", "scheduled_format", "format_fallback_reason",
    "format_config_version", "candidate_counts_by_source", "selected_sources",
    "selected", "japan_freshness_days", "anchor_present", "evidence_roles",
    "official_basis_present", "source", "lane", "matched_notion_terms", "reason",
    "passed", "issues", "duration_seconds", "mean_volume_db", "max_volume_db",
    "long_silence_seconds", "long_silence_ratio", "file_size_bytes", "thresholds",
    "min_duration_seconds", "max_duration_seconds", "min_mean_volume_db",
    "max_mean_volume_db", "max_peak_volume_db", "max_long_silence_ratio",
    "silence_noise_db", "silence_min_seconds", "character_count", "hard_min",
    "hard_max", "target_min", "target_max", "legacy_bootstrap",
    "degradations", "stage", "action",
}
PUBLIC_CHECK_STRINGS = PUBLIC_NEWS_SOURCES | {
    "daily", "lab", "world", "japan", "research", "official", "reporting",
    "notion_match", "least_recent_source", "fresh_japan_lane", "different_source",
    "candidate_fallback", "official_basis", "corroborating_source",
    "insufficient_multi_source_official_basis", "insufficient_weekly_lab_topic",
    "gemini_audio_transcription",
    "duration_too_short", "duration_too_long", "mean_volume_too_quiet",
    "mean_volume_too_loud", "peak_too_high", "too_much_long_silence",
    # 配信を優先して品質ゲートを一段落としたときの記録。自由文は載せず列挙値だけを通す。
    "dialogue_style_gate", "script_length_gate", "retry_generation_failed",
    "retry_still_formulaic", "retry_too_similar", "retry_length_rejected",
    "retry_budget_exhausted",
    "published_initial_script", "published_style_retry_script",
}


def safe_public_text(value: str, *, fallback: str, max_length: int) -> str:
    """Bound a public title/summary to one line and reject private-path shapes."""

    text = re.sub(r"\s+", " ", str(value or "")).strip()
    denied = (
        r"/Users/",
        r"file://",
        r"localhost",
        r"127\.0\.0\.1",
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        r"(?i)(api[_-]?key|secret|token)=",
    )
    if not text or any(re.search(pattern, text) for pattern in denied):
        text = fallback
    return text[:max_length].rstrip()


def public_qa_summary(qa: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep only closed, non-narrative QA fields in the public manifest."""

    if not isinstance(qa, dict):
        return None
    result = {}
    status = qa.get("status")
    if status in {"completed", "disabled", "unavailable"}:
        result["status"] = status
    score_fields = (
        "overall_score",
        "speech_clarity_score",
        "dialogue_naturalness_score",
        "bgm_balance_score",
        "pacing_score",
    )
    for key in score_fields:
        value = qa.get(key)
        if type(value) is int and 1 <= value <= 5:
            result[key] = value
    for key in ("has_internal_repetition", "requires_human_review"):
        value = qa.get(key)
        if type(value) is bool:
            result[key] = value
    issues = []
    for issue in qa.get("issues", []):
        if not isinstance(issue, dict):
            continue
        category = issue.get("category")
        severity = issue.get("severity")
        timestamp = issue.get("timestamp")
        if category not in {
            "pronunciation", "speaker", "bgm", "silence", "clipping",
            "pacing", "repetition", "format", "other",
        }:
            continue
        if severity not in {"info", "warning", "critical"}:
            continue
        if not isinstance(timestamp, str) or not re.fullmatch(r"unknown|\d{2}:\d{2}", timestamp):
            timestamp = "unknown"
        issues.append({"category": category, "severity": severity, "timestamp": timestamp})
    result["issues"] = issues[:20]
    return result


def safe_public_news_urls(urls: list[str]) -> list[str]:
    """Keep public HTTPS targets while dropping credentials, query data, and fragments."""

    safe = set()
    for value in urls:
        try:
            parsed = urlsplit(str(value))
            host = (parsed.hostname or "").lower()
            if parsed.scheme != "https" or not host or parsed.username or parsed.password:
                continue
            if host == "localhost" or host.endswith(".local"):
                continue
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                address = None
            if address and (address.is_private or address.is_loopback or address.is_link_local):
                continue
            cleaned = urlunsplit(("https", parsed.netloc, parsed.path, "", ""))
            if len(cleaned) <= 600:
                safe.add(cleaned)
        except (TypeError, ValueError):
            continue
    return sorted(safe)


def public_deterministic_checks(checks: dict[str, Any] | None) -> dict[str, Any]:
    """Project deterministic audit data onto a fail-closed public schema."""

    def clean(value, key=None):
        if key == "candidate_counts_by_source" and isinstance(value, dict):
            return {
                source: count
                for source, count in value.items()
                if source in PUBLIC_NEWS_SOURCES
                and type(count) is int
                and 0 <= count <= 10000
            }
        if isinstance(value, dict):
            return {
                child_key: cleaned
                for child_key, child_value in value.items()
                if child_key in PUBLIC_CHECK_KEYS
                and (cleaned := clean(child_value, child_key)) is not None
            }
        if isinstance(value, list):
            return [cleaned for item in value if (cleaned := clean(item, key)) is not None][:100]
        if type(value) is bool:
            return value
        if type(value) is int:
            return value if -1_000_000_000 <= value <= 1_000_000_000 else None
        if type(value) is float:
            return value if math.isfinite(value) and abs(value) <= 1_000_000_000 else None
        if value is None and key == "format_fallback_reason":
            return None
        if isinstance(value, str):
            if value in PUBLIC_CHECK_STRINGS or re.fullmatch(r"formats-v[1-9][0-9]*", value):
                return value
        return None

    if not isinstance(checks, dict):
        return {}
    cleaned = clean(checks)
    return cleaned if isinstance(cleaned, dict) else {}


def stable_term_key(page_id: str) -> str:
    """Return a non-reversible key instead of publishing a Notion page ID."""
    return hashlib.sha256(page_id.encode("utf-8")).hexdigest()[:24]


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_script(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[^0-9a-zぁ-んァ-ヶ一-龠々ー]+", "", normalized)


def script_minhash(text: str, size: int = MINHASH_SIZE) -> list[int]:
    """Create a compact signature suitable for approximate Jaccard comparison."""
    normalized = normalize_script(text)
    if not normalized:
        return []
    if len(normalized) < NGRAM_SIZE:
        ngrams = {normalized}
    else:
        ngrams = {
            normalized[index:index + NGRAM_SIZE]
            for index in range(len(normalized) - NGRAM_SIZE + 1)
        }

    signature = []
    for seed in range(size):
        minimum = min(
            int.from_bytes(
                hashlib.blake2b(
                    f"{seed}:{ngram}".encode("utf-8"), digest_size=8
                ).digest(),
                "big",
            )
            for ngram in ngrams
        )
        signature.append(minimum)
    return signature


def signature_similarity(left: list[int], right: list[int]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    equal = sum(a == b for a, b in zip(left, right))
    return equal / len(left)


def topic_similarity(left: str, right: str) -> float:
    """Compare short topic labels with character bigram Jaccard similarity."""
    normalized_left = normalize_script(left)
    normalized_right = normalize_script(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0

    def bigrams(value: str) -> set[str]:
        if len(value) < 2:
            return {value}
        return {value[index:index + 2] for index in range(len(value) - 1)}

    left_bigrams = bigrams(normalized_left)
    right_bigrams = bigrams(normalized_right)
    union = left_bigrams | right_bigrams
    return len(left_bigrams & right_bigrams) / len(union) if union else 0.0


def max_topic_similarity(topic: str, manifests: list[dict[str, Any]]) -> float:
    return max(
        (
            topic_similarity(topic, manifest.get("primary_topic", ""))
            for manifest in manifests
        ),
        default=0.0,
    )


def max_recent_similarity(script: str, manifests: list[dict[str, Any]]) -> float:
    signature = script_minhash(script)
    similarities = [
        signature_similarity(signature, manifest.get("script_minhash", []))
        for manifest in manifests
    ]
    return max(similarities, default=0.0)


def exclude_recent_news(
    news_items: list[dict[str, Any]], manifests: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    recent_urls = {
        canonical
        for manifest in manifests
        for url in manifest.get("news_urls", [])
        if (canonical_urls := safe_public_news_urls([url]))
        for canonical in canonical_urls
    }
    filtered = []
    for item in news_items:
        raw_url = item.get("link")
        canonical_urls = safe_public_news_urls([raw_url]) if raw_url else []
        if not canonical_urls or canonical_urls[0] not in recent_urls:
            filtered.append(item)
    return filtered, len(news_items) - len(filtered)


def load_recent_manifests(
    manifests_dir: str | os.PathLike[str], limit: int = 3
) -> list[dict[str, Any]]:
    directory = Path(manifests_dir)
    if not directory.exists():
        return []

    manifests = []
    for path in directory.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("schema_version") != SCHEMA_VERSION:
            continue
        manifests.append(data)

    manifests.sort(
        key=lambda item: (item.get("broadcast_date", ""), item.get("generated_at", "")),
        reverse=True,
    )
    return manifests[:limit]


def write_manifest_atomic(
    manifest: dict[str, Any], manifests_dir: str | os.PathLike[str]
) -> Path:
    directory = Path(manifests_dir)
    directory.mkdir(parents=True, exist_ok=True)
    episode_id = manifest["episode_id"]
    destination = directory / f"{episode_id}.json"

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=directory, delete=False, prefix=".manifest-"
    ) as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary_path = Path(handle.name)
    os.replace(temporary_path, destination)
    return destination


def build_manifest(
    *,
    episode_id: str,
    broadcast_date: str,
    selected_terms: list[dict[str, Any]],
    primary_topic: str,
    news_urls: list[str],
    script: str,
    audio_path: str,
    duration_seconds: int,
    deterministic_checks: dict[str, Any],
    publish_status: str,
    gemini_qa_summary: dict[str, Any] | None = None,
    episode_format: str | None = None,
    editorial_profile_version: str | None = None,
    public_topic: str | None = None,
) -> dict[str, Any]:
    if episode_format is not None and episode_format not in {"daily", "lab"}:
        raise ValueError("episode_format must be daily or lab")
    if editorial_profile_version is not None and not re.fullmatch(
        r"editorial-v[1-9][0-9]*", editorial_profile_version
    ):
        raise ValueError("invalid editorial_profile_version")

    safe_topic = safe_public_text(
        primary_topic, fallback="最新AIニュース", max_length=200
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "episode_id": episode_id,
        "broadcast_date": broadcast_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selected_term_keys": [
            stable_term_key(str(term["id"])) for term in selected_terms
        ],
        # The topic is already spoken in the public episode. Notion body text is never stored.
        "primary_topic": safe_topic,
        "topic_fingerprint": hashlib.sha256(
            normalize_script(safe_topic).encode("utf-8")
        ).hexdigest()[:24],
        "news_urls": safe_public_news_urls(news_urls),
        "script_sha256": hashlib.sha256(script.encode("utf-8")).hexdigest(),
        "script_minhash": script_minhash(script),
        "audio_sha256": sha256_file(audio_path),
        "duration_seconds": duration_seconds,
        "deterministic_checks": public_deterministic_checks(deterministic_checks),
        "gemini_qa_summary": public_qa_summary(gemini_qa_summary),
        "publish_status": publish_status,
    }
    if episode_format is not None:
        manifest["episode_format"] = episode_format
    if editorial_profile_version is not None:
        manifest["editorial_profile_version"] = editorial_profile_version
    if public_topic is not None:
        manifest["public_topic"] = safe_public_text(
            public_topic, fallback="最新AIニュース", max_length=160
        )
    return manifest


def recently_reviewed(last_reviewed: str | None, *, today=None, days: int = 3) -> bool:
    if not last_reviewed:
        return False
    if today is None:
        today = datetime.now(timezone(timedelta(hours=9))).date()
    try:
        reviewed_date = datetime.fromisoformat(last_reviewed).date()
    except (TypeError, ValueError):
        return False
    return reviewed_date >= today - timedelta(days=days)
