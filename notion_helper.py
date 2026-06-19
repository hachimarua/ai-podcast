import os
import random
import json
from datetime import datetime
import requests
from dotenv import load_dotenv

# 環境変数の読み込み
load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# Notion API Headers
HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# ローカルモック用ファイルパス
MOCK_FILE_PATH = os.path.join(os.path.dirname(__file__), "notion_mock_db.json")

def create_mock_data_if_not_exists():
    """Notion APIキーが設定されていない場合に使用するダミーデータを作成"""
    if not os.path.exists(MOCK_FILE_PATH):
        dummy_data = [
            {"id": "mock-1", "name": "RAG (Retrieval-Augmented Generation)", "review_count": 0, "last_reviewed": None},
            {"id": "mock-2", "name": "MCP (Model Context Protocol)", "review_count": 0, "last_reviewed": None},
            {"id": "mock-3", "name": "LLM Context Window", "review_count": 0, "last_reviewed": None},
            {"id": "mock-4", "name": "Prompt Injection", "review_count": 0, "last_reviewed": None},
            {"id": "mock-5", "name": "Fine-Tuning", "review_count": 0, "last_reviewed": None},
            {"id": "mock-6", "name": "Vector Database", "review_count": 0, "last_reviewed": None},
            {"id": "mock-7", "name": "Agentic Workflow", "review_count": 0, "last_reviewed": None}
        ]
        with open(MOCK_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(dummy_data, f, indent=4, ensure_ascii=False)
        print(f"Created local mock database at {MOCK_FILE_PATH}")

def is_notion_configured():
    """Notion APIが設定されているか確認"""
    return NOTION_API_KEY and NOTION_DATABASE_ID and "YOUR_" not in NOTION_API_KEY

def get_title_property_name(properties):
    """NotionのTitleプロパティ名（'Name', '名前', 'タイトル' など）を自動検出"""
    for prop_name, prop_val in properties.items():
        if prop_val.get("type") == "title":
            return prop_name
    return "Name"

def fetch_notion_terms():
    """NotionまたはモックDBから全用語を取得"""
    if not is_notion_configured():
        create_mock_data_if_not_exists()
        with open(MOCK_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
            
    # 実環境でのNotion APIクエリ
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
            print(f"[Warning] Notion API query failed: {response.text}")
            print("Falling back to local mock data...")
            # エラー時はモックにフォールバック
            create_mock_data_if_not_exists()
            with open(MOCK_FILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
                
        data = response.json()
        for page in data.get("results", []):
            props = page.get("properties", {})
            title_prop = get_title_property_name(props)
            
            # 用語名の抽出
            title_list = props.get(title_prop, {}).get("title", [])
            name = title_list[0].get("plain_text", "") if title_list else "無題"
            
            # 復習回数プロパティ (Review Count / 復習回数) の抽出
            # カラム名候補: 'Review Count' または '復習回数'
            review_count = 0
            for col in ["Review Count", "復習回数"]:
                if col in props and props[col].get("type") == "number":
                    review_count = props[col].get("number") or 0
                    break
                    
            # 最終復習日 (Last Reviewed / 最終復習日) の抽出
            last_reviewed = None
            for col in ["Last Reviewed", "最終復習日"]:
                if col in props and props[col].get("type") == "date":
                    date_val = props[col].get("date")
                    if date_val:
                        last_reviewed = date_val.get("start")
                    break
            
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
    """復習回数が少ない単語を優先してランダムに抽出 (案C改)"""
    terms = fetch_notion_terms()
    if not terms:
        return []
        
    # 復習回数でソート (昇順)
    terms.sort(key=lambda x: x["review_count"])
    
    # 復習回数が最小のグループを特定する
    min_count = terms[0]["review_count"]
    # 復習回数が最小値に近いものをプール（最小値 + 1回までの単語を候補とする）
    candidates = [t for t in terms if t["review_count"] <= min_count + 1]
    
    # プール内からランダムに指定数選ぶ
    selected = random.sample(candidates, min(len(candidates), count))
    
    # 足りない場合は全体の順位が低い順に補填
    if len(selected) < count:
        for t in terms:
            if t not in selected:
                selected.append(t)
                if len(selected) == count:
                    break
                    
    return selected

def update_term_review_status(term_id, current_count):
    """用語の復習回数を+1し、最終復習日を今日に更新"""
    today_str = datetime.today().strftime('%Y-%m-%d')
    new_count = current_count + 1
    
    if not is_notion_configured() or term_id.startswith("mock-"):
        # ローカルモックデータの更新
        if os.path.exists(MOCK_FILE_PATH):
            with open(MOCK_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                if item["id"] == term_id:
                    item["review_count"] = new_count
                    item["last_reviewed"] = today_str
                    break
            with open(MOCK_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            print(f"[Mock] Updated {term_id}: count={new_count}, date={today_str}")
        return True
        
    # 実環境でのNotion API更新
    url = f"https://api.notion.com/v1/pages/{term_id}"
    
    # カラム名が 'Review Count' または '復習回数' のどちらで定義されているか判定
    # ※PATCHリクエスト時には、対象となるプロパティのみを指定して送信可能
    # ここでは一般的な英語・日本語のペアで両方アップデートを試みます。
    # 存在しないプロパティを送るとエラーになるため、事前にデータベーススキーマのプロパティ一覧を取得するか、
    # 汎用的に動くよう properties を構成します。
    
    properties_to_update = {}
    
    # fetch_notion_terms()で検知されたプロパティ名に合わせるため、
    # 共通化のために Notion DB の情報を再度簡易的に参照するか、一般的なデフォルト値をセットします。
    # ユーザーのDBスキーマに合わせるため、一般的なカラムを更新対象にします。
    properties_to_update["Review Count"] = {"number": new_count}
    properties_to_update["Last Reviewed"] = {"date": {"start": today_str}}
    
    # もしエラーが出た場合は日本語版カラム（復習回数、最終復習日）でも再試行できるようにします。
    payload = {"properties": properties_to_update}
    response = requests.patch(url, headers=HEADERS, json=payload)
    
    if response.status_code != 200:
        # 日本語カラム名で再試行
        properties_to_update = {
            "復習回数": {"number": new_count},
            "最終復習日": {"date": {"start": today_str}}
        }
        payload = {"properties": properties_to_update}
        response = requests.patch(url, headers=HEADERS, json=payload)
        
    if response.status_code == 200:
        print(f"[Notion] Updated page {term_id}: count={new_count}, date={today_str}")
        return True
    else:
        print(f"[Error] Failed to update Notion page {term_id}: {response.text}")
        return False

# 簡易動作テスト用
if __name__ == "__main__":
    print("Notion Helper Test Running...")
    selected = select_terms_for_review(3)
    print("Selected Terms:")
    for s in selected:
        print(f"- {s['name']} (Count: {s['review_count']}, Last: {s['last_reviewed']})")
        # テストとして更新を実行
        update_term_review_status(s['id'], s['review_count'])
