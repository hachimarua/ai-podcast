import feedparser
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta
import time

# 信頼できるAI情報源のホワイトリストRSSフィード
WHITELIST_FEEDS = {
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "Google AI Blog": "https://blog.google/technology/ai/rss/",
    "Hugging Face Blog": "https://huggingface.co/blog/feed.xml",
    "arXiv cs.AI (Artificial Intelligence)": "https://arxiv.org/rss/cs.AI",
    # ※一部RSSフィードはスクレイピング制限やURL変更の可能性があるため、必要に応じてユーザーが調整可能
}

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
        # タイムアウトを設定したリクエスト
        feed = feedparser.parse(feed_url)
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
                "title": clean_title,
                "link": entry.get("link", ""),
                "published": published_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "content": clean_text
            })
        return entries
    except Exception as e:
        print(f"[Error] Failed to fetch feed {feed_name}: {e}")
        return []

def collect_latest_news(max_entries_per_feed=5):
    """ホワイトリストの全フィードから最新ニュースを収集"""
    all_news = []
    for name, url in WHITELIST_FEEDS.items():
        entries = fetch_feed_entries(name, url, max_entries_per_feed)
        all_news.extend(entries)
    return all_news

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
            news_copy["matched_words"] = list(set(matched_words))
            matched_news.append(news_copy)
        else:
            unmatched_news.append(news)
            
    return matched_news, unmatched_news

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
