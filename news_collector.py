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
WEEKLY_LAB_NEWS_MAX_AGE_DAYS = 10
MAX_NEWS_PER_BROADCAST = 2

# Weekly Lab is deliberately independent from the user's Notion review terms.
# Rank recent stories by whether they teach a reusable skill for an everyday
# vibe-coding workflow, then require the primary story to come from a trusted
# first-party feed.  These are selection hints, not facts injected into the
# generated script.
WEEKLY_LAB_PRACTICAL_PATTERNS = (
    re.compile(
        r"\b(agent(?:ic|s)?|coding|developer|api|sdk|mcp|cli|pwa|devops|"
        r"rag|retrieval|llm|prompt(?:ing)?|model(?:s)?|"
        r"ci/cd|github|git|cloudflare|database|sqlite|sql|cache|precache|"
        r"security|authentication|authorization|permission|deploy(?:ment)?|"
        r"workflow|automation|testing|test)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(エージェント|コーディング|開発者|開発環境|実装|RAG|検索拡張|LLM|"
        r"プロンプト|モデル|API|認証|認可|権限|"
        r"デプロイ|セキュリティ|データベース|キャッシュ|ワークフロー|自動化|"
        r"テスト|監査|障害対応|ロールバック)"
    ),
)

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
    """Raised when Weekly Lab lacks a safe, practical official basis."""


def validate_lab_sources(news_items):
    """Accept one official source; optional corroboration must remain trusted and unique."""

    if not news_items:
        raise LabSourceError("weekly lab requires at least one source")
    urls = set()
    trusted_roles = []
    for item in news_items:
        source_config = SOURCE_CONFIG.get(item.get("source"))
        if not source_config:
            raise LabSourceError("weekly lab source is not trusted")
        canonical_urls = safe_public_news_urls([item.get("link")])
        if len(canonical_urls) != 1:
            raise LabSourceError("weekly lab requires a public HTTPS source URL")
        canonical = canonical_urls[0]
        if canonical in urls:
            raise LabSourceError("weekly lab source URLs must be distinct")
        urls.add(canonical)
        if not str(item.get("title", "")).strip() or not str(item.get("content", "")).strip():
            raise LabSourceError("weekly lab source must include a title and content")
        trusted_roles.append(source_config.get("evidence_role", "untrusted"))
    if "official" not in trusted_roles:
        raise LabSourceError("weekly lab requires an official source")
    return True


def _weekly_lab_relevance_score(news):
    """Score reusable implementation value without another model/API call."""

    title = str(news.get("title", ""))
    content = str(news.get("content", ""))[:5000]
    score = 0
    for pattern in WEEKLY_LAB_PRACTICAL_PATTERNS:
        score += min(len(pattern.findall(title)), 3) * 3
        score += min(len(pattern.findall(content)), 5)
    return score


def _weekly_lab_title_tokens(news):
    title = str(news.get("title", "")).casefold()
    tokens = set(re.findall(r"[a-z0-9][a-z0-9.+-]{2,}", title))
    return tokens - {
        "the", "and", "for", "with", "from", "new", "update", "using", "into",
        "this", "that", "your", "latest", "release", "announcing", "google",
        "official", "agent", "agents", "agentic", "model", "models", "api", "sdk",
    }


def _weekly_lab_items_related(primary, candidate):
    primary_terms = set(primary.get("matched_words", []))
    candidate_terms = set(candidate.get("matched_words", []))
    if primary_terms and candidate_terms and primary_terms & candidate_terms:
        return True
    return bool(_weekly_lab_title_tokens(primary) & _weekly_lab_title_tokens(candidate))


def select_news_for_lab(news_items, recent_manifests, *, now=None, max_items=3):
    """Select one practical weekly theme with an official source as its basis.

    Notion matching is intentionally not a prerequisite.  A second source is
    included only when its title or explicit matched terms support the same
    topic, so the longer episode never pads itself with an unrelated story.
    """

    if not 1 <= max_items <= 4:
        raise ValueError("lab max_items must be between 1 and 4")
    now = now or datetime.now(timezone.utc)
    recent_source_counts = _recent_source_counts(recent_manifests)
    candidates = []
    seen_urls = set()
    for index, item in enumerate(news_items):
        source_config = SOURCE_CONFIG.get(item.get("source"))
        canonical_urls = safe_public_news_urls([item.get("link")])
        if not source_config or len(canonical_urls) != 1:
            continue
        if not str(item.get("title", "")).strip() or not str(item.get("content", "")).strip():
            continue
        canonical = canonical_urls[0]
        if canonical in seen_urls:
            continue
        seen_urls.add(canonical)
        score = _weekly_lab_relevance_score(item)
        if score <= 0:
            continue
        published_at = _published_at_or_none(item)
        if published_at and published_at < now - timedelta(days=WEEKLY_LAB_NEWS_MAX_AGE_DAYS):
            continue
        candidate = item.copy()
        candidate["lane"] = candidate.get("lane", source_config.get("lane", "world"))
        candidate["evidence_role"] = source_config.get("evidence_role", "untrusted")
        candidate["_matched_for_review"] = bool(candidate.get("matched_words"))
        candidate["_candidate_index"] = index
        candidate["_weekly_lab_score"] = score
        candidate["_weekly_lab_published_at"] = published_at
        candidates.append(candidate)

    def sort_key(candidate):
        published_at = candidate.get("_weekly_lab_published_at")
        freshness = -published_at.timestamp() if published_at else float("inf")
        return (
            -candidate["_weekly_lab_score"],
            freshness,
            recent_source_counts[candidate.get("source", "")],
            candidate["_candidate_index"],
        )

    official_candidates = [
        item for item in candidates if item.get("evidence_role") == "official"
    ]
    if not official_candidates:
        raise LabSourceError(
            "Weekly Lab requires one recent practical topic from an official source"
        )

    primary = min(official_candidates, key=sort_key)
    primary["_selection_reason"] = "official_basis"
    selected = [primary]
    selected_sources = {primary.get("source")}
    related = [
        item
        for item in candidates
        if item is not primary and _weekly_lab_items_related(primary, item)
    ]
    for candidate in sorted(
        related,
        key=lambda item: (
            0 if item.get("source") not in selected_sources else 1,
            *sort_key(item),
        ),
    ):
        candidate["_selection_reason"] = "corroborating_source"
        selected.append(candidate)
        selected_sources.add(candidate.get("source"))
        if len(selected) >= max_items:
            break

    validate_lab_sources(selected)
    audit_selection = [
        {
            "source": item.get("source", ""),
            "lane": item.get("lane", "world"),
            "matched_notion_terms": item["_matched_for_review"],
            "reason": item["_selection_reason"],
        }
        for item in selected
    ]
    return selected, {
        "candidate_counts_by_source": dict(sorted(Counter(
            item.get("source", "") for item in candidates
        ).items())),
        "anchor_present": any(item["_matched_for_review"] for item in selected),
        "selected_sources": [item.get("source", "") for item in selected],
        "selected": audit_selection,
        "evidence_roles": [item.get("evidence_role", "reporting") for item in selected],
        "official_basis_present": True,
    }

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
