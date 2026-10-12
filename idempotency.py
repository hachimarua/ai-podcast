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

    Verifies that:
    1. A manifest exists with publish_status == 'published' for target_date.
    2. The associated MP3 file exists in episodes_dir and is non-empty (if episodes_dir exists).
    3. The episode is listed in the RSS feed (if feed_path exists).
    """
    if target_date is None:
        target_date = get_jst_today_date()

    manifest_path = Path(manifests_dir)
    if not manifest_path.exists():
        return False

    episodes_path = Path(episodes_dir)
    feed_file = Path(feed_path)

    for json_file in manifest_path.glob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if (
                data.get("broadcast_date") == target_date
                and data.get("publish_status") == "published"
            ):
                episode_id = data.get("episode_id") or json_file.stem
                # Check MP3 existence if episodes directory exists
                if episodes_path.exists():
                    mp3_path = episodes_path / f"{episode_id}.mp3"
                    if not (mp3_path.is_file() and mp3_path.stat().st_size > 0):
                        continue

                # Check RSS feed inclusion if feed file exists
                if feed_file.is_file() and feed_file.stat().st_size > 0:
                    try:
                        content = feed_file.read_text(encoding="utf-8")
                        if episode_id not in content:
                            continue
                    except OSError:
                        pass

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
