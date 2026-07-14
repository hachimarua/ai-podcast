import feedparser
from bs4 import BeautifulSoup
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
import time
import requests
from api_client import request_bytes
from episode_history import safe_public_news_urls

# 信頼できるAI情報源のホワイトリストRSSフィード
SOURCE_CONFIG = {
    "TechCrunch AI": {
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "lane": "world",
        "evidence_role": "reporting",
    },
    "Google AI Blog": {
        "url": "https://blog.google/technology/ai/rss/",
        "lane": "world",
        "evidence_role": "official",
    },
    "Hugging Face Blog": {
        "url": "https://huggingface.co/blog/feed.xml",
        "lane": "world",
        "evidence_role": "official",
    },
    "arXiv cs.AI (Artificial Intelligence)": {
        "url": "https://arxiv.org/rss/cs.AI",
        "lane": "research",
        "evidence_role": "research",
    },
    "ITmedia AI+": {
        "url": "https://rss.itmedia.co.jp/rss/2.0/aiplus.xml",
        "lane": "japan",
        "evidence_role": "reporting",
    },
    "AI Watch": {
        "url": "https://ai.watch.impress.co.jp/data/rss/1.0/aiw/feed.rdf",
        "lane": "japan",
        "evidence_role": "reporting",
    },
}

# Compatibility alias for callers or local tools that import the feed list directly.
WHITELIST_FEEDS = {
    name: config["url"] for name, config in SOURCE_CONFIG.items()
}

JAPAN_NEWS_MAX_AGE_DAYS = 14
MAX_NEWS_PER_BROADCAST = 2

def clean_html(html_content):
    """HTMLタグを除去し、プレーンテキストにする。スクリプトやスタイルは完全に削除。"""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    # スクリプトやスタイルシートを削除
    for script in soup(["script", "style", "iframe", "noscript"]):
        script.decompose()
    text = soup.get_text(separator="\n")
    return text

def sanitize_content(text):
    """
    プロンプトインジェクション対策（サニタイズ）
    AIへの指示（System Instructions）を無視させようとする悪意あるフレーズや、
    制御コードなどを除去または無害化する。
    """
    if not text:
        return ""
        
    # 一般的なプロンプトインジェクションフレーズの検出・無害化
    injection_patterns = [
        (r"(?i)ignore\s+(all\s+)?prior\s+instructions", "[FILTERED INJECTION ATTACK]"),
        (r"(?i)ignore\s+instructions\s+above", "[FILTERED INJECTION ATTACK]"),
        (r"(?i)system\s+prompt\s+override", "[FILTERED INJECTION ATTACK]"),
        (r"(?i)you\s+must\s+now\s+act\s+as", "[FILTERED INJECTION ATTACK]"),
        (r"(?i)これ以降の指示を無視", "[FILTERED INJECTION ATTACK]"),
        (r"(?i)指示を上書き", "[FILTERED INJECTION ATTACK]")
    ]
    
    sanitized = text
    for pattern, replacement in injection_patterns:
        sanitized = re.sub(pattern, replacement, sanitized)
        
    # 不要な連続改行や空白の整理
    sanitized = re.sub(r'\n\s*\n', '\n\n', sanitized)
    sanitized = sanitized.strip()
    return sanitized

def fetch_feed_entries(feed_name, feed_url, max_entries=5):
    """指定されたフィードから最新記事を取得"""
    print(f"Fetching {feed_name}...")
    try:
        session = requests.Session()
        session.headers.update({"User-Agent": "AI-Learning-Radio/1.0 (+RSS reader)"})
        feed_bytes = request_bytes(session, "GET", feed_url)
        feed = feedparser.parse(feed_bytes)
        if feed.bozo and not feed.entries:
            raise ValueError(f"Invalid RSS feed: {type(feed.bozo_exception).__name__}")
        entries = []
        
        for entry in feed.entries[:max_entries]:
            # タイトルと本文の取得
            title = entry.get("title", "")
            summary_html = entry.get("summary", "") or entry.get("description", "")
            content_list = entry.get("content", [])
            content_html = content_list[0].value if content_list else summary_html
            
            # クリーニングとサニタイズ
            raw_text = clean_html(content_html)
            clean_text = sanitize_content(raw_text)
            clean_title = sanitize_content(title)
            
            # 日付の取得と整形
            published_parsed = entry.get("published_parsed")
            if published_parsed:
                published_dt = datetime.fromtimestamp(time.mktime(published_parsed))
            else:
                published_dt = datetime.now()
                
            entries.append({
                "source": feed_name,
                "lane": SOURCE_CONFIG.get(feed_name, {}).get("lane", "world"),
                "evidence_role": SOURCE_CONFIG.get(feed_name, {}).get(
                    "evidence_role", "reporting"
                ),
                "title": clean_title,
                "link": entry.get("link", ""),
                "published": published_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "content": clean_text
            })
        return entries
    except Exception as e:
        print(f"[Error] Failed to fetch feed {feed_name}: {e}")
        return []

def filter_business_noise(news_list):
    """
    タイトルや本文にビジネス・融資関連のノイズワードが含まれるニュースを除外する。
    """
    # 英語のノイズワード（単語境界を考慮するため正規表現パターンを作成）
    english_noise_words = [
        r'\bseed\s+round\b', r'\bseries\s+[a-z]\b', r'\bfunding\b', r'\bvaluation\b', 
        r'\bacquisition\b', r'\bacquire\b', r'\bmerger\b', r'\bmerged\b', r'\bvc\b', 
        r'\bventure\s+capital\b', r'\bipo\b', r'\binvestment\b', r'\binvest\b', 
        r'\braise\s+money\b', r'\braised\s+(?:\$\d+|\d+\s*million|\d+\s*billion)\b'
    ]
    english_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in english_noise_words]
    
    # 日本語のノイズワード（部分一致で検出）
    japanese_noise_words = [
        "資金調達", "買収", "合併", "融資", "評価額", "子会社", "株式取得", 
        "資本業務提携", "ベンチャーキャピタル", "投資ラウンド", "出資"
    ]
    
    filtered_news = []
    removed_count = 0
    
    for news in news_list:
        text_to_check = f"{news['title']}\n{news['content']}"
        
        # 英語のパターンマッチ確認
        is_noise = False
        for pattern in english_patterns:
            if pattern.search(text_to_check):
                is_noise = True
                break
                
        # 日本語のキーワードマッチ確認
        if not is_noise:
            for word in japanese_noise_words:
                if word in text_to_check:
                    is_noise = True
                    break
                    
        if is_noise:
            removed_count += 1
            print(f" -> [Filtered Business Noise] Removed: {news['title']}")
        else:
            filtered_news.append(news)
            
    print(f"Business Noise Filtering: Removed {removed_count} entries. {len(filtered_news)} entries remaining.")
    return filtered_news

def collect_latest_news(max_entries_per_feed=5):
    """ホワイトリストの全フィードから最新ニュースを収集し、ビジネスノイズをフィルタリング"""
    all_news = []
    for name, url in WHITELIST_FEEDS.items():
        entries = fetch_feed_entries(name, url, max_entries_per_feed)
        all_news.extend(entries)
    
    # ビジネスノイズを除外
    filtered_news = filter_business_noise(all_news)
    if not filtered_news:
        raise RuntimeError("No valid news entries were collected; pipeline stopped")
    return filtered_news

def match_news_with_words(news_list, words):
    """収集したニュースとNotionから抽出した単語（words）をマッチング"""
    matched_news = []
    unmatched_news = []
    
    # 検索用の単語の正規表現パターンを作成
    # 大文字・小文字を無視し、単語境界や部分一致を許容
    patterns = {}
    for word_item in words:
        word = word_item["name"]
        # 例: "RAG (Retrieval-Augmented Generation)" のような括弧付き用語からキーワードを抽出
        # "RAG", "Retrieval-Augmented Generation" の両方をパターンに登録
        sub_words = [w.strip() for w in re.split(r'[\(\)]', word) if w.strip()]
        patterns[word] = [re.compile(rf"\b{re.escape(sw)}\b", re.IGNORECASE) for sw in sub_words]
        
    for news in news_list:
        matched_words = []
        full_text = f"{news['title']}\n{news['content']}"
        
        for original_word, regex_list in patterns.items():
            for regex in regex_list:
                if regex.search(full_text):
                    matched_words.append(original_word)
                    break # この単語のマッチ判定は終了し、次の単語へ
                    
        if matched_words:
            news_copy = news.copy()
            news_copy["matched_words"] = list(dict.fromkeys(matched_words))
            matched_news.append(news_copy)
        else:
            unmatched_news.append(news)
            
    return matched_news, unmatched_news


def _published_at_or_none(news):
    """Parse the normalized RSS timestamp without treating invalid dates as current."""
    try:
        return datetime.strptime(news.get("published", ""), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        return None


def _is_fresh_japan_candidate(news, now):
    published_at = _published_at_or_none(news)
    if published_at is None:
        return False
    return published_at >= now - timedelta(days=JAPAN_NEWS_MAX_AGE_DAYS)


def _recent_source_counts(recent_manifests):
    """Read source history from new manifests and infer the legacy TechCrunch entries."""
    counts = Counter()
    for manifest in recent_manifests:
        selection = manifest.get("deterministic_checks", {}).get("news_selection", {})
        for source in selection.get("selected_sources", []):
            if source:
                counts[source] += 1
        if selection.get("selected_sources"):
            continue
        for url in manifest.get("news_urls", []):
            if "techcrunch.com" in url:
                counts["TechCrunch AI"] += 1
    return counts


def select_news_for_broadcast(
    matched_news, unmatched_news, recent_manifests, *, now=None, max_items=MAX_NEWS_PER_BROADCAST
):
    """Select at most two source-diverse items for one five-minute broadcast.

    A matching item keeps priority.  The second slot prefers a fresh Japanese
    reporting source, otherwise a source different from the first item.  This is
    a deterministic fallback policy, not a daily quota: stale Japanese items are
    never forced into the programme.
    """
    if not 1 <= max_items <= 4:
        raise ValueError("max_items must be between 1 and 4")
    now = now or datetime.now(timezone.utc)
    recent_source_counts = _recent_source_counts(recent_manifests)
    candidates = []
    seen = set()

    for is_match, items in ((True, matched_news), (False, unmatched_news)):
        for index, item in enumerate(items):
            dedupe_key = item.get("link") or (item.get("source"), item.get("title"))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            candidate = item.copy()
            candidate["lane"] = candidate.get(
                "lane", SOURCE_CONFIG.get(candidate.get("source"), {}).get("lane", "world")
            )
            candidate["_matched_for_review"] = is_match
            candidate["_candidate_index"] = index
            candidates.append(candidate)

    def sort_key(candidate):
        return (
            0 if candidate["_matched_for_review"] else 1,
            recent_source_counts[candidate.get("source", "")],
            candidate["_candidate_index"],
        )

    ordered_candidates = sorted(candidates, key=sort_key)
    selected = []
    reasons = []

    def add(candidate, reason):
        selected.append(candidate)
        reasons.append(reason)

    def related_to_primary(candidate):
        if not selected:
            return True
        primary = selected[0]
        primary_terms = set(primary.get("matched_words", []))
        candidate_terms = set(candidate.get("matched_words", []))
        if primary_terms and candidate_terms and primary_terms & candidate_terms:
            return True

        def title_tokens(item):
            title = str(item.get("title", "")).casefold()
            tokens = set(re.findall(r"[a-z0-9][a-z0-9.+-]{2,}", title))
            return tokens - {"the", "and", "for", "with", "from", "new", "update", "ai"}

        return bool(title_tokens(primary) & title_tokens(candidate))

    if ordered_candidates:
        add(
            ordered_candidates[0],
            "notion_match" if ordered_candidates[0]["_matched_for_review"] else "least_recent_source",
        )

    while len(selected) < max_items:
        remaining = [
            item
            for item in ordered_candidates
            if item not in selected and related_to_primary(item)
        ]
        if not remaining:
            break

        selected_sources = {item.get("source") for item in selected}
        has_japan_lane = any(item.get("lane") == "japan" for item in selected)
        fresh_japan = [
            item
            for item in remaining
            if item.get("lane") == "japan" and _is_fresh_japan_candidate(item, now)
        ]
        different_source = [
            item for item in remaining if item.get("source") not in selected_sources
        ]

        if not has_japan_lane and fresh_japan:
            candidate = min(fresh_japan, key=sort_key)
            reason = "fresh_japan_lane"
        elif different_source:
            candidate = min(different_source, key=sort_key)
            reason = "different_source"
        else:
            candidate = remaining[0]
            reason = "candidate_fallback"
        add(candidate, reason)

    selection = []
    for item, reason in zip(selected, reasons):
        item["_selection_reason"] = reason
        selection.append({
            "source": item.get("source", ""),
            "lane": item.get("lane", "world"),
            "matched_notion_terms": item["_matched_for_review"],
            "reason": reason,
        })

    audit = {
        "candidate_counts_by_source": dict(sorted(Counter(
            item.get("source", "") for item in candidates
        ).items())),
        "selected_sources": [item.get("source", "") for item in selected],
        "selected": selection,
        "japan_freshness_days": JAPAN_NEWS_MAX_AGE_DAYS,
    }
    return selected, audit


class LabSourceError(RuntimeError):
    """Raised when one theme lacks multiple sources and an official basis."""


def validate_lab_sources(news_items):
    """Require a shared anchor, distinct public URLs/sources, and trusted official source."""

    if len(news_items) < 2:
        raise LabSourceError("lab requires at least two sources")
    urls = {
        canonical
        for item in news_items
        if (canonical_urls := safe_public_news_urls([item.get("link")]))
        for canonical in canonical_urls
    }
    sources = {item.get("source") for item in news_items if item.get("source")}
    if len(urls) < 2 or len(sources) < 2:
        raise LabSourceError("lab requires distinct URLs and sources")
    common_terms = None
    trusted_roles = []
    for item in news_items:
        terms = set(item.get("matched_words", []))
        common_terms = terms if common_terms is None else common_terms & terms
        trusted_roles.append(
            SOURCE_CONFIG.get(item.get("source"), {}).get("evidence_role", "untrusted")
        )
    if not common_terms:
        raise LabSourceError("lab sources must share one matched theme")
    if "official" not in trusted_roles:
        raise LabSourceError("lab requires an official source from trusted configuration")
    return True


def select_news_for_lab(matched_news, recent_manifests, *, max_items=3):
    """Select one Notion-anchored theme from distinct sources for a non-public lab run."""

    if not 2 <= max_items <= 4:
        raise ValueError("lab max_items must be between 2 and 4")
    recent_source_counts = _recent_source_counts(recent_manifests)
    grouped = {}
    term_order = []
    for index, item in enumerate(matched_news):
        for term in item.get("matched_words", []):
            if term not in grouped:
                grouped[term] = []
                term_order.append(term)
            candidate = item.copy()
            candidate["lane"] = candidate.get(
                "lane", SOURCE_CONFIG.get(candidate.get("source"), {}).get("lane", "world")
            )
            candidate["evidence_role"] = SOURCE_CONFIG.get(
                candidate.get("source"), {}
            ).get("evidence_role", "untrusted")
            candidate["_matched_for_review"] = True
            candidate["_candidate_index"] = index
            grouped[term].append(candidate)

    for term in term_order:
        candidates = grouped[term]
        deduped = []
        seen_urls = set()
        seen_sources = set()
        for candidate in sorted(
            candidates,
            key=lambda item: (
                0 if item.get("evidence_role") == "official" else 1,
                recent_source_counts[item.get("source", "")],
                item["_candidate_index"],
            ),
        ):
            url = candidate.get("link")
            source = candidate.get("source")
            if not url or url in seen_urls or source in seen_sources:
                continue
            seen_urls.add(url)
            seen_sources.add(source)
            candidate["_selection_reason"] = (
                "official_basis"
                if candidate.get("evidence_role") == "official"
                else "corroborating_source"
            )
            deduped.append(candidate)
            if len(deduped) >= max_items:
                break

        if len(deduped) < 2:
            continue
        try:
            validate_lab_sources(deduped)
        except LabSourceError:
            continue
        return deduped, {
            "anchor_present": True,
            "selected_sources": [item.get("source", "") for item in deduped],
            "evidence_roles": [item.get("evidence_role", "reporting") for item in deduped],
            "official_basis_present": True,
        }

    raise LabSourceError(
        "AI implementation lab requires one matched theme, two distinct URLs/sources, "
        "and at least one official source"
    )

# 簡易動作テスト用
if __name__ == "__main__":
    print("News Collector Test Running...")
    dummy_words = [
        {"name": "RAG (Retrieval-Augmented Generation)"},
        {"name": "MCP"},
        {"name": "Agent"}
    ]
    
    latest_news = collect_latest_news(max_entries_per_feed=3)
    print(f"Collected {len(latest_news)} total news entries.")
    
    matched, unmatched = match_news_with_words(latest_news, dummy_words)
    
    print(f"\nMatched News ({len(matched)}):")
    for m in matched[:3]:
        print(f"- [{m['source']}] {m['title']} (Matched: {m['matched_words']})")
        
    print(f"\nUnmatched News ({len(unmatched)}):")
    for u in unmatched[:3]:
        print(f"- [{u['source']}] {u['title']}")
