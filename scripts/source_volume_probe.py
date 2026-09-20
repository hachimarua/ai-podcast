#!/usr/bin/env python3
"""Measure how much source text each feed actually gives us, and what the article page would add.

This is a measurement tool, not a step of the pipeline.  Nothing here is imported
by main.py, no episode is published, no manifest or RSS is written, and no API key
is read.  It only performs public read-only GETs.

The question it answers: the script writer is asked for 1,550-1,750 characters on a
weekday and 3,000-3,500 on Sunday, but ``news_collector.fetch_feed_entries`` only
ever reads the RSS entry -- the article page is never fetched.  So we do not know
whether fetching it is blocked (paywall, robots, bot filter) or simply absent.

For each whitelisted feed this reports, per entry:

  * ``rss_chars``      -- exactly the text news_collector would put in the prompt
  * ``article_chars``  -- main-body text extracted from the article page
  * ``gain``           -- article_chars / rss_chars
  * ``paywall``        -- paywall/registration markers found on the page
  * ``robots``         -- whether robots.txt allows this path for our user agent

Run it in CI, where outbound access to the feeds is available:

    python scripts/source_volume_probe.py --out source_probe

Writes ``<out>.json`` (full detail) and prints a summary table to stdout.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from news_collector import SOURCE_CONFIG, clean_html  # noqa: E402

# The pipeline identifies itself as a feed reader.  Keep the same identity here so
# the measurement reflects what the pipeline would actually be served.
USER_AGENT = "AI-Learning-Radio/1.0 (+RSS reader)"
TIMEOUT = (10, 30)
POLITE_DELAY_SECONDS = 1.0

# Markers that mean "the body you just extracted is a teaser, not the article".
PAYWALL_MARKERS = (
    "有料会員限定",
    "有料会員",
    "会員限定",
    "この記事は有料",
    "続きを読むには",
    "ログインして続き",
    "無料会員登録",
    "定期購読",
    "subscribe to continue",
    "subscriber-only",
    "this article is for subscribers",
    "create a free account to continue",
    "sign in to read",
)

# Containers that never hold article prose.
STRIP_TAGS = (
    "script", "style", "noscript", "nav", "header", "footer", "aside",
    "form", "iframe", "figure", "figcaption", "svg", "button",
)


def extract_main_text(html: str) -> str:
    """Pull the article body out of a page with a structure-first heuristic.

    Prefers a semantic container, then falls back to whichever block holds the
    most paragraph text.  Deliberately simple: the point is to measure order of
    magnitude, not to build a production extractor.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(STRIP_TAGS):
        tag.decompose()

    def paragraph_text(node) -> str:
        paragraphs = [p.get_text(" ", strip=True) for p in node.find_all("p")]
        joined = "\n".join(text for text in paragraphs if text)
        return re.sub(r"[ \t]+", " ", joined).strip()

    for selector in ("article", "main", "[itemprop='articleBody']", ".entry-content"):
        node = soup.select_one(selector)
        if node:
            text = paragraph_text(node)
            if len(text) >= 200:
                return text

    best = ""
    for node in soup.find_all(["div", "section"]):
        text = paragraph_text(node)
        if len(text) > len(best):
            best = text
    return best or re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def find_paywall_markers(html: str) -> list[str]:
    lowered = html.casefold()
    return [marker for marker in PAYWALL_MARKERS if marker.casefold() in lowered]


def robots_allows(session: requests.Session, url: str, cache: dict) -> bool | None:
    """Return True/False per robots.txt, or None when robots.txt is unreadable."""
    parts = urlparse(url)
    root = f"{parts.scheme}://{parts.netloc}"
    if root not in cache:
        parser = urllib.robotparser.RobotFileParser()
        try:
            response = session.get(urljoin(root, "/robots.txt"), timeout=TIMEOUT)
            if response.status_code == 200:
                parser.parse(response.text.splitlines())
                cache[root] = parser
            else:
                cache[root] = None
        except requests.RequestException:
            cache[root] = None
    parser = cache[root]
    if parser is None:
        return None
    return parser.can_fetch(USER_AGENT, url)


def probe_entry(session: requests.Session, entry, robots_cache: dict) -> dict:
    """Measure one feed entry: what RSS gave us, and what the page would give us."""
    summary_html = entry.get("summary", "") or entry.get("description", "")
    content_list = entry.get("content", []) or []
    content_html = content_list[0].value if content_list else summary_html
    rss_text = clean_html(content_html)

    result = {
        "title": entry.get("title", "")[:120],
        "link": entry.get("link", ""),
        "rss_chars": len(rss_text),
        "rss_field": "content" if content_list else "summary",
        "article_chars": None,
        "http_status": None,
        "final_url": None,
        "paywall_markers": [],
        "robots_allowed": None,
        "error": None,
    }

    link = result["link"]
    if not link.startswith("https://"):
        result["error"] = "no https link"
        return result

    result["robots_allowed"] = robots_allows(session, link, robots_cache)

    try:
        response = session.get(link, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException as exc:
        result["error"] = type(exc).__name__
        return result

    result["http_status"] = response.status_code
    result["final_url"] = response.url
    if response.status_code != 200:
        return result

    html = response.text
    result["article_chars"] = len(extract_main_text(html))
    result["paywall_markers"] = find_paywall_markers(html)
    return result


def probe_feed(session: requests.Session, name: str, url: str, limit: int,
               robots_cache: dict) -> dict:
    print(f"[probe] {name}", flush=True)
    out = {"source": name, "feed_url": url, "entries": [], "error": None}
    try:
        response = session.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except requests.RequestException as exc:
        out["error"] = f"feed fetch failed: {type(exc).__name__}"
        return out

    if not feed.entries:
        out["error"] = "feed returned no entries"
        return out

    for entry in feed.entries[:limit]:
        out["entries"].append(probe_entry(session, entry, robots_cache))
        time.sleep(POLITE_DELAY_SECONDS)
    return out


def summarize(feed_result: dict) -> dict:
    entries = feed_result["entries"]
    rss = [e["rss_chars"] for e in entries if e["rss_chars"]]
    article = [e["article_chars"] for e in entries if e["article_chars"]]
    statuses = sorted({e["http_status"] for e in entries if e["http_status"]})
    paywalled = sum(1 for e in entries if e["paywall_markers"])
    blocked = sum(1 for e in entries if e["robots_allowed"] is False)
    median_rss = int(statistics.median(rss)) if rss else 0
    median_article = int(statistics.median(article)) if article else 0
    return {
        "source": feed_result["source"],
        "entries": len(entries),
        "median_rss_chars": median_rss,
        "median_article_chars": median_article,
        "gain": round(median_article / median_rss, 1) if median_rss and median_article else None,
        "http_statuses": statuses,
        "paywalled_entries": paywalled,
        "robots_disallowed_entries": blocked,
        "error": feed_result["error"],
    }


def print_table(summaries: list[dict]) -> None:
    head = f"{'source':40}{'RSS':>8}{'記事本文':>10}{'倍率':>7}{'HTTP':>12}{'有料':>6}{'robots×':>9}"
    print("\n" + head)
    print("-" * len(head))
    for s in summaries:
        if s["error"]:
            print(f"{s['source'][:38]:40}{'-':>8}{'-':>10}{'-':>7}  {s['error']}")
            continue
        gain = f"{s['gain']}x" if s["gain"] else "-"
        statuses = ",".join(str(code) for code in s["http_statuses"]) or "-"
        print(
            f"{s['source'][:38]:40}{s['median_rss_chars']:>8}{s['median_article_chars']:>10}"
            f"{gain:>7}{statuses:>12}{s['paywalled_entries']:>6}{s['robots_disallowed_entries']:>9}"
        )


def print_budget(summaries: list[dict]) -> None:
    """Put the measured supply next to what the prompt asks the model to write."""
    usable = [s for s in summaries if not s["error"] and s["median_rss_chars"]]
    if not usable:
        return
    rss_median = statistics.median(s["median_rss_chars"] for s in usable)
    article_values = [s["median_article_chars"] for s in usable if s["median_article_chars"]]
    article_median = statistics.median(article_values) if article_values else 0

    print("\n素材と要求量")
    print("-" * 58)
    for label, items, target in (("Daily Brief", 3, 1750), ("AI実装ラボ", 4, 3500)):
        supply_rss = int(rss_median * items)
        supply_article = int(article_median * items)
        print(
            f"{label:14} 素材{items}件  RSSのみ {supply_rss:>6}字 "
            f"(要求の{supply_rss / target:>4.1f}倍)   本文あり {supply_article:>6}字 "
            f"({supply_article / target:>4.1f}倍)   台本要求 {target}字"
        )
    print("\n  倍率が 1 を下回る = 台本より素材のほうが短い = water を足さないと書けない状態")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5,
                        help="entries measured per feed (default 5, matching the pipeline)")
    parser.add_argument("--out", default="source_probe", help="output path without extension")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    robots_cache: dict = {}

    results = [
        probe_feed(session, name, config["url"], args.limit, robots_cache)
        for name, config in SOURCE_CONFIG.items()
    ]
    summaries = [summarize(result) for result in results]

    print_table(summaries)
    print_budget(summaries)

    out_path = Path(f"{args.out}.json")
    out_path.write_text(
        json.dumps({"summaries": summaries, "detail": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n詳細を書き出しました: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
