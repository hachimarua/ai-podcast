"""One-time bootstrap of recent episode manifests from already-public MP3 files."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from mutagen.mp3 import MP3
from pydantic import BaseModel, Field

from episode_history import build_manifest, write_manifest_atomic


class LegacyEpisodeAnalysis(BaseModel):
    primary_topic: str = Field(description="放送で最も長く扱われた主要テーマ。簡潔な日本語。")
    transcript: str = Field(description="話者名を含む日本語の全文文字起こし。")


EPISODE_PATTERN = re.compile(r"podcast_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.mp3$")


def broadcast_date_from_filename(filename: str) -> str:
    match = EPISODE_PATTERN.match(filename)
    if not match:
        raise ValueError(f"Unsupported episode filename: {filename}")
    year, month, day, *_ = match.groups()
    return f"{year}-{month}-{day}"


def analyze_episode(client, model: str, audio_path: Path) -> LegacyEpisodeAnalysis:
    uploaded = client.files.upload(file=str(audio_path))
    try:
        response = client.models.generate_content(
            model=model,
            contents=[
                uploaded,
                (
                    "この公開済みAI学習ラジオを日本語で文字起こししてください。"
                    "ケンジとアミを可能な範囲で識別し、放送で最も長く扱われた主要テーマを"
                    "一つだけ抽出してください。音声にない事実は追加しないでください。"
                ),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=LegacyEpisodeAnalysis,
                temperature=0.0,
            ),
        )
        if response.parsed:
            return response.parsed
        return LegacyEpisodeAnalysis.model_validate(json.loads(response.text))
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception as exc:
            print(f"[Warning] Temporary Gemini file cleanup failed: {type(exc).__name__}")


def bootstrap(limit: int, model: str) -> list[Path]:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or "YOUR_GEMINI" in api_key:
        raise RuntimeError("GEMINI_API_KEY is required for legacy audio bootstrap")

    base_dir = Path(__file__).resolve().parent
    episodes_dir = base_dir / "episodes"
    manifests_dir = base_dir / "episode_manifests"
    episodes = sorted(episodes_dir.glob("podcast_*.mp3"), reverse=True)[:limit]
    client = genai.Client(api_key=api_key)
    created = []

    for audio_path in episodes:
        episode_id = audio_path.stem
        destination = manifests_dir / f"{episode_id}.json"
        if destination.exists():
            print(f"Skipping existing manifest: {destination.name}")
            continue

        print(f"Analyzing legacy episode: {audio_path.name}")
        analysis = analyze_episode(client, model, audio_path)
        duration_seconds = int(MP3(audio_path).info.length)
        manifest = build_manifest(
            episode_id=episode_id,
            broadcast_date=broadcast_date_from_filename(audio_path.name),
            selected_terms=[],
            primary_topic=analysis.primary_topic,
            news_urls=[],
            script=analysis.transcript,
            audio_path=str(audio_path),
            duration_seconds=duration_seconds,
            deterministic_checks={
                "legacy_bootstrap": True,
                "source": "gemini_audio_transcription",
            },
            publish_status="legacy_imported",
        )
        created.append(write_manifest_atomic(manifest, manifests_dir))
        print(f"Created: {destination.name}")

    return created


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument(
        "--model", default=os.getenv("GEMINI_AUDIO_QA_MODEL", "gemini-2.5-flash")
    )
    args = parser.parse_args()
    created = bootstrap(args.limit, args.model)
    print(f"Bootstrap complete: {len(created)} manifest(s) created")


if __name__ == "__main__":
    main()
