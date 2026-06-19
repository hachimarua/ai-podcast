import os
import random
import json
from datetime import datetime
import requests
from dotenv import load_dotenv

# 環境変数の読み込み
load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
# データベースIDの位置に、親ページのID (35d142da197280b3ae74f921ac365125) が設定されている前提で動かします
NOTION_PARENT_PAGE_ID = os.getenv("NOTION_DATABASE_ID")

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

MOCK_FILE_PATH = os.path.join(os.path.dirname(__file__), "notion_mock_db.json")

def create_mock_data_if_not_exists():
    if not os.path.exists(MOCK_FILE_PATH):
        dummy_data = [
            {"id": "mock-1", "name": "20260511 (RAGの勉強)", "content": "RAGについて学習した。外部知識をLLMに検索・注入する技術である。", "review_count": 0, "last_reviewed": None},
            {"id": "mock-2", "name": "20260512 (MCPの勉強)", "content": "Model Context ProtocolはLLMとPC内のリソースを繋ぐ規格である。", "review_count": 0, "last_reviewed": None},
            {"id": "mock-3", "name": "20260514 (Context Window)", "content": "Context Windowが大きくなると、本1冊分のテキストを丸ごと処理できる。", "review_count": 0, "last_reviewed": None},
            {"id": "mock-4", "name": "20260515 (インジェクション対策)", "content": "プロンプトインジェクションは、悪意ある命令を入力してAIを暴走させる攻撃である。", "review_count": 0, "last_reviewed": None}
        ]
        with open(MOCK_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(dummy_data, f, indent=4, ensure_ascii=False)

def is_notion_configured():
    return NOTION_API_KEY and NOTION_PARENT_PAGE_ID and "YOUR_" not in NOTION_API_KEY

def fetch_page_text_content(page_id):
    """子ページの中身（テキストブロック）を結合して取得"""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    try:
        response = requests.get(url, headers=HEADERS)
        if response.status_code != 200:
            return ""
            
        data = response.json()
        texts = []
        review_count = 0
        last_reviewed = None
        
        # 本文ブロックをパース
        for block in data.get("results", []):
            block_type = block.get("type")
            text_element = None
            
            # テキストが含まれる代表的なブロックタイプ
            if block_type in ["paragraph", "bulleted_list_item", "numbered_list_item", "heading_1", "heading_2", "heading_3"]:
                text_element = block.get(block_type, {}).get("rich_text", [])
                
            if text_element:
                plain_text = "".join([t.get("plain_text", "") for t in text_element])
                texts.append(plain_text)
                
                # 過去の「📝 復習履歴」という追記テキストがあれば復習回数と日付をパースする
                # フォーマット例: "📝 復習履歴: 2回目 (最終: 2026-06-19)"
                match = re.search(r"📝\s*復習履歴:\s*(\d+)回目\s*\(最終:\s*([\d-]+)\)", plain_text)
                if match:
                    review_count = max(review_count, int(match.group(1)))
                    last_reviewed = match.group(2)
                    
        return "\n".join(texts), review_count, last_reviewed
    except Exception as e:
        print(f"[Warning] Failed to fetch page content: {e}")
        return "", 0, None

import re # reモジュールが必要なのでインポート

def fetch_notion_terms():
    """親ページ配下の子ページ（日記ログ）の一覧を取得"""
    if not is_notion_configured():
        create_mock_data_if_not_exists()
        with open(MOCK_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
            
    # 親ページのブロックの子要素（＝子ページ）を取得
    url = f"https://api.notion.com/v1/blocks/{NOTION_PARENT_PAGE_ID}/children"
    response = requests.get(url, headers=HEADERS)
    
    if response.status_code != 200:
        print(f"[Warning] Notion page children fetch failed: {response.text}")
        print("Falling back to local mock data...")
        create_mock_data_if_not_exists()
        with open(MOCK_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
            
    data = response.json()
    terms = []
    
    for block in data.get("results", []):
        if block.get("type") == "child_page":
            page_id = block.get("id")
            title = block.get("child_page", {}).get("title", "無題")
            
            # 子ページの中身テキストと、過去の復習回数を取得
            content, review_count, last_reviewed = fetch_page_text_content(page_id)
            
            # ページタイトルまたは本文の最初の1行からキーワード(学習テーマ)を推測
            # 本文全体が渡されるため、Gemini側でより深い文脈が理解できます
            terms.append({
                "id": page_id,
                "name": title,          # タイトル (例: '20260511')
                "content": content,      # ページ本文
                "review_count": review_count,
                "last_reviewed": last_reviewed
            })
            
    return terms

def select_terms_for_review(count=3):
    """復習回数が少ない日記（子ページ）を優先してランダムに抽出"""
    terms = fetch_notion_terms()
    if not terms:
        return []
        
    terms.sort(key=lambda x: x["review_count"])
    min_count = terms[0]["review_count"]
    candidates = [t for t in terms if t["review_count"] <= min_count + 1]
    
    selected = random.sample(candidates, min(len(candidates), count))
    
    if len(selected) < count:
        for t in terms:
            if t not in selected:
                selected.append(t)
                if len(selected) == count:
                    break
                    
    return selected

def update_term_review_status(page_id, current_count):
    """日記ページの末尾に「📝 復習履歴」のブロックを追記更新する"""
    today_str = datetime.today().strftime('%Y-%m-%d')
    new_count = current_count + 1
    record_text = f"📝 復習履歴: {new_count}回目 (最終: {today_str})"
    
    if not is_notion_configured() or page_id.startswith("mock-"):
        # モックの更新
        if os.path.exists(MOCK_FILE_PATH):
            with open(MOCK_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                if item["id"] == page_id:
                    item["review_count"] = new_count
                    item["last_reviewed"] = today_str
                    break
            with open(MOCK_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            print(f"[Mock] Updated {page_id}: count={new_count}, date={today_str}")
        return True
        
    # 日記子ページの末尾に段落ブロックとして復習履歴を追記
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    payload = {
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": f"\n{record_text}"
                            },
                            "annotations": {
                                "bold": True,
                                "italic": False,
                                "color": "purple"  # 目立つように紫に設定
                            }
                        }
                    ]
                }
            }
        ]
    }
    
    response = requests.patch(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        print(f"[Notion Page] Appended review stamp to page {page_id}: {record_text}")
        return True
    else:
        print(f"[Error] Failed to append review stamp to Notion page {page_id}: {response.text}")
        return False

# 動作テスト用
if __name__ == "__main__":
    print("Notion Helper (Page-based) Test Running...")
    selected = select_terms_for_review(3)
    print("Selected Pages:")
    for s in selected:
        print(f"- Title: {s['name']} (Count: {s['review_count']}, Last: {s['last_reviewed']})")
        # print(f"  Content: {s['content'][:100]}...")
