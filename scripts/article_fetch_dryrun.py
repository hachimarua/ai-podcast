#!/usr/bin/env python3
"""Run the real collection path against the live feeds and report what the script writer would get.

This publishes nothing and needs no API key: it stops at the point where the
prompt would be built, and prints the source text each selected item carries.
It exists so the article-body fetch can be verified against the actual sites
before a daily episode depends on it.

    python scripts/article_fetch_dryrun.py --format daily
    python scripts/article_fetch_dryrun.py --format lab
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from episode_formats import load_episode_formats  # noqa: E402
from news_collector import (  # noqa: E402
    article_fetch_summary,
    collect_latest_news,
    select_news_for_broadcast,
    select_news_for_lab,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("daily", "lab"), default="daily")
    args = parser.parse_args()

    spec = load_episode_formats().formats[args.format]

    news = collect_latest_news(episode_format=args.format)
    summary = article_fetch_summary()

    print(f"\n本文取得の内訳（{len(news)}件を採用候補として収集）")
    print("-" * 64)
    for status, count in sorted(summary["status_counts"].items()):
        print(f"  {status:20} {count:>3}件")

    if args.format == "lab":
        selected, _ = select_news_for_lab(news, [], max_items=spec.max_news_items)
    else:
        selected, _ = select_news_for_broadcast(
            [], news, [], max_items=spec.max_news_items
        )

    print(f"\n台本に渡される素材（{args.format}）")
    print("-" * 64)
    total = 0
    for item in selected:
        chars = len(str(item.get("content", "")))
        lead = item.get("rss_excerpt_chars")
        total += chars
        origin = f"RSS {lead}字 → 本文" if lead is not None else "RSSのみ"
        print(f"  {chars:>6}字  [{origin}]  {item['source']}")
        print(f"          {str(item.get('title', ''))[:60]}")

    target = spec.prompt_character_max
    print("-" * 64)
    print(f"  合計 {total}字  /  台本要求 {target}字  =  {total / target:.1f}倍")
    if total < target:
        print("\n  素材が要求を下回っています。水増しなしでは書けない状態です。")
    else:
        print("\n  素材が要求を上回っています。削る編集で書ける状態です。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
