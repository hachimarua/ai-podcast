#!/usr/bin/env python3
"""Find out why the research lane goes quiet, by asking arXiv the same question several ways.

``arXiv cs.AI`` is missing from the candidate pool on six of the last fourteen
episodes, on weekdays as well as weekends, and the source probe saw the feed
return zero entries twice in a row on 2026-09-20. That is either a feed that is
empty at announcement boundaries or an endpoint that no longer serves us.

This asks each candidate endpoint for the same category and reports what comes
back: HTTP status, content type, entry count, and how the parser reacted. It
publishes nothing and needs no API key.

    python scripts/arxiv_feed_check.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import feedparser
import requests

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from news_collector import SOURCE_CONFIG  # noqa: E402

USER_AGENT = "AI-Learning-Radio/1.0 (+RSS reader)"
TIMEOUT = (10, 30)

CANDIDATES = (
    ("現行（news_collector）", SOURCE_CONFIG["arXiv cs.AI (Artificial Intelligence)"]["url"]),
    ("rss.arxiv.org", "https://rss.arxiv.org/rss/cs.AI"),
    ("rss.arxiv.org/atom", "https://rss.arxiv.org/atom/cs.AI"),
    ("export.arxiv.org API", "https://export.arxiv.org/api/query"
                             "?search_query=cat:cs.AI&sortBy=submittedDate"
                             "&sortOrder=descending&max_results=5"),
)


def check(label: str, url: str, session: requests.Session) -> None:
    print(f"\n=== {label} ===")
    print(f"  {url}")
    try:
        response = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException as exc:
        print(f"  取得失敗: {type(exc).__name__}")
        return

    print(f"  HTTP {response.status_code}  {response.headers.get('Content-Type', '?')}")
    if response.url != url:
        print(f"  リダイレクト先: {response.url}")
    print(f"  本文 {len(response.content)} bytes")
    if response.status_code != 200:
        return

    feed = feedparser.parse(response.content)
    print(f"  エントリ {len(feed.entries)} 件  bozo={bool(feed.bozo)}"
          + (f" ({type(feed.bozo_exception).__name__})" if feed.bozo else ""))
    for entry in feed.entries[:3]:
        summary = entry.get("summary", "") or entry.get("description", "")
        published = entry.get("published", "?")
        print(f"    - 要約{len(summary):>5}字  {published[:31]}  {entry.get('title', '')[:48]}")


def main() -> int:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    for label, url in CANDIDATES:
        check(label, url, session)
        time.sleep(1.0)
    print(
        "\n判定の目安: 現行だけが0件で他が0件でないならエンドポイントの問題、"
        "全部0件なら公表の谷（週末・祝日）なので時間をおいて再確認する。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
