"""Daily episode idempotency and deduplication guard."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def get_jst_today_date() -> str:
    """Return today's date in JST format (YYYY-MM-DD)."""
    return datetime.now(JST).strftime("%Y-%m-%d")


def is_today_episode_published(
    manifests_dir: Path | str = "episode_manifests",
    target_date: str | None = None,
    episodes_dir: Path | str = "episodes",
    feed_path: Path | str = "podcast.xml",
) -> bool:
    """Check if an episode for the target JST date has already been published.

    Strict verification requirements:
    1. A valid manifest exists with publish_status == 'published' for target_date.
    2. The associated MP3 file strictly exists in episodes_dir and is non-empty (>0 bytes).
    3. The RSS feed XML file strictly exists, is readable, and contains the episode_id.

    All three artifacts must be present and verified. Partial failures (e.g., manifest only,
    or audio synthesized but not archived/indexed in RSS) will return False so the pipeline
    can safely heal and finish publishing.
    """
    if target_date is None:
        target_date = get_jst_today_date()

    manifest_path = Path(manifests_dir)
    episodes_path = Path(episodes_dir)
    feed_file = Path(feed_path)

    if not manifest_path.is_dir() or not episodes_path.is_dir() or not feed_file.is_file():
        return False

    if feed_file.stat().st_size == 0:
        return False

    try:
        feed_content = feed_file.read_text(encoding="utf-8")
    except OSError:
        return False

    for json_file in manifest_path.glob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if (
                data.get("broadcast_date") == target_date
                and data.get("publish_status") == "published"
            ):
                episode_id = data.get("episode_id") or json_file.stem

                # 2. Strict MP3 existence and non-empty check
                mp3_path = episodes_path / f"{episode_id}.mp3"
                if not (mp3_path.is_file() and mp3_path.stat().st_size > 0):
                    continue

                # 3. Strict RSS feed inclusion check
                if episode_id not in feed_content:
                    continue

                return True
        except (OSError, json.JSONDecodeError):
            continue

    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check daily podcast idempotency.")
    parser.add_argument(
        "--manifests-dir",
        default="episode_manifests",
        help="Path to episode manifests directory",
    )
    parser.add_argument(
        "--episodes-dir",
        default="episodes",
        help="Path to episodes directory",
    )
    parser.add_argument(
        "--feed-path",
        default="podcast.xml",
        help="Path to podcast RSS feed XML file",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Target broadcast date in YYYY-MM-DD (defaults to JST today)",
    )
    parser.add_argument(
        "--github-output",
        default=os.environ.get("GITHUB_OUTPUT"),
        help="Path to GITHUB_OUTPUT file for GitHub Actions",
    )

    args = parser.parse_args(argv)
    target_date = args.date or get_jst_today_date()
    already_published = is_today_episode_published(
        manifests_dir=args.manifests_dir,
        target_date=target_date,
        episodes_dir=args.episodes_dir,
        feed_path=args.feed_path,
    )

    skip_value = "true" if already_published else "false"

    if already_published:
        print(f"[Idempotency Guard] Episode for {target_date} is already published. Skipping.")
    else:
        print(f"[Idempotency Guard] No published episode found for {target_date}. Ready to run.")

    if args.github_output:
        try:
            with open(args.github_output, "a", encoding="utf-8") as f:
                f.write(f"skip={skip_value}\n")
                f.write(f"target_date={target_date}\n")
        except OSError as e:
            print(f"[Warning] Failed to write to GITHUB_OUTPUT: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
