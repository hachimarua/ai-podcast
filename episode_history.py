"""Privacy-conscious episode history and duplicate detection."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
PIPELINE_VERSION = "phase1"
MINHASH_SIZE = 64
NGRAM_SIZE = 3
TOPIC_SIMILARITY_THRESHOLD = 0.30


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
        url
        for manifest in manifests
        for url in manifest.get("news_urls", [])
        if url
    }
    filtered = [
        item for item in news_items if not item.get("link") or item.get("link") not in recent_urls
    ]
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
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "episode_id": episode_id,
        "broadcast_date": broadcast_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selected_term_keys": [
            stable_term_key(str(term["id"])) for term in selected_terms
        ],
        # The topic is already spoken in the public episode. Notion body text is never stored.
        "primary_topic": primary_topic[:200],
        "topic_fingerprint": hashlib.sha256(
            normalize_script(primary_topic).encode("utf-8")
        ).hexdigest()[:24],
        "news_urls": sorted({url for url in news_urls if url}),
        "script_sha256": hashlib.sha256(script.encode("utf-8")).hexdigest(),
        "script_minhash": script_minhash(script),
        "audio_sha256": sha256_file(audio_path),
        "duration_seconds": duration_seconds,
        "deterministic_checks": deterministic_checks,
        "gemini_qa_summary": gemini_qa_summary,
        "publish_status": publish_status,
    }


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
