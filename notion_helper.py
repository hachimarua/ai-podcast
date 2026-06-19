import os
import random
import json
from datetime import datetime, timezone, timedelta
import requests
from dotenv import load_dotenv

# 環境変数の読み込み
load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID") # 新規作成されたデータベースのID

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
    return NOTION_API_KEY and NOTION_DATABASE_ID and "YOUR_" not in NOTION_API_KEY

def fetch_page_text_content(page_id):
    """選択されたページIDの中身（テキストブロック）を結合して取得"""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    try:
        response = requests.get(url, headers=HEADERS)
        if response.status_code != 200:
            return ""
            
        data = response.json()
        texts = []
        
        # 本文ブロックをパース
        for block in data.get("results", []):
            block_type = block.get("type")
            text_element = None
            
            if block_type in ["paragraph", "bulleted_list_item", "numbered_list_item", "heading_1", "heading_2", "heading_3"]:
                text_element = block.get(block_type, {}).get("rich_text", [])
                
            if text_element:
                plain_text = "".join([t.get("plain_text", "") for t in text_element])
                texts.append(plain_text)
                
        return "\n".join(texts)
    except Exception as e:
        print(f"[Warning] Failed to fetch page content: {e}")
        return ""

def fetch_notion_terms():
    """新データベースから学習レコード（用語）の一覧を取得"""
    if not is_notion_configured():
        create_mock_data_if_not_exists()
        with open(MOCK_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
            
    # データベースのクエリを実行
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    terms = []
    has_more = True
    start_cursor = None
    
    while has_more:
        payload = {}
        if start_cursor:
            payload["start_cursor"] = start_cursor
            
        response = requests.post(url, headers=HEADERS, json=payload)
        if response.status_code != 200:
            print(f"[Warning] Notion DB query failed: {response.text}")
            print("Falling back to local mock data...")
            create_mock_data_if_not_exists()
            with open(MOCK_FILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
                
        data = response.json()
        for page in data.get("results", []):
            props = page.get("properties", {})
            
            # 用語名の取得（「名前」プロパティ）
            title_list = props.get("名前", {}).get("title", [])
            name = title_list[0].get("plain_text", "") if title_list else "無題"
            
            # 復習回数の取得（「復習回数」プロパティ）
            review_count = props.get("復習回数", {}).get("number") or 0
            
            # 最終復習日の取得（「最終復習日」プロパティ）
            last_reviewed = None
            date_val = props.get("最終復習日", {}).get("date")
            if date_val:
                last_reviewed = date_val.get("start")
                
            terms.append({
                "id": page.get("id"),
                "name": name,
                "review_count": review_count,
                "last_reviewed": last_reviewed
            })
            
        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")
        
    return terms

def select_terms_for_review(count=3):
    """復習回数が少ないレコードを優先してランダムに3件抽出し、その本文テキストも結合して返す"""
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
                    
    # 選出されたレコードに対してのみ、本文（中身のテキスト）をNotionから遅延読み込みする
    # ※APIの負荷軽減および高速化のため
    for s in selected:
        if is_notion_configured() and not s["id"].startswith("mock-"):
            print(f" -> ページ内容を読み込み中: {s['name']}")
            s["content"] = fetch_page_text_content(s["id"])
        else:
            # モックモード時はcontentは既に存在
            pass
            
    return selected

def update_term_review_status(page_id, current_count):
    """新データベースのページプロパティ（復習回数、最終復習日）を書き換える"""
    JST = timezone(timedelta(hours=9))
    today_str = datetime.now(JST).strftime('%Y-%m-%d')
    new_count = current_count + 1
    
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
        
    # データベースのページ更新 (PATCH /v1/pages/{page_id})
    url = f"https://api.notion.com/v1/pages/{page_id}"
    
    payload = {
        "properties": {
            "復習回数": {
                "number": new_count
            },
            "最終復習日": {
                "date": {
                    "start": today_str
                }
            }
        }
    }
    
    response = requests.patch(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        print(f"[Notion DB] Updated record {page_id}: 復習回数={new_count}, 最終復習日={today_str}")
        return True
    else:
        print(f"[Error] Failed to update Notion record {page_id}: {response.text}")
        return False

# 動作テスト用
if __name__ == "__main__":
    print("Notion Helper (DB-based) Test Running...")
    selected = select_terms_for_review(3)
    print("Selected Terms:")
    for s in selected:
        print(f"- Name: {s['name']} (Count: {s['review_count']}, Last: {s['last_reviewed']})")
        # テスト更新
        update_term_review_status(s['id'], s['review_count'])
