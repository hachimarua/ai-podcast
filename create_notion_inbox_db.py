import os
import requests
from dotenv import load_dotenv

# 環境変数の読み込み
load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_PARENT_PAGE_ID = "35d142da197280b3ae74f921ac365125" # 親ページのID

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def create_inbox_database():
    if not NOTION_API_KEY or "YOUR_" in NOTION_API_KEY:
        print("[Error] .env ファイルの API キーが正しく設定されていません。")
        return False
        
    url = "https://api.notion.com/v1/databases"
    
    # 受信箱データベースの設計（シンプルに「名前」プロパティのみ）
    payload = {
        "parent": {
            "type": "page_id",
            "page_id": NOTION_PARENT_PAGE_ID
        },
        "title": [
            {
                "type": "text",
                "text": {
                    "content": "AI学習受信箱 (Inbox)"
                }
            }
        ],
        "properties": {
            "名前": {
                "title": {}
            }
        }
    }
    
    print("親ページの配下に「AI学習受信箱 (Inbox)」を作成しています...")
    response = requests.post(url, headers=HEADERS, json=payload)
    
    if response.status_code == 200:
        data = response.json()
        inbox_db_id = data.get("id").replace("-", "")
        print("\n🎉 受信箱データベースの自動作成に成功しました！")
        print(f"作成されたDBのタイトル: {data.get('title', [{}])[0].get('plain_text')}")
        print(f"受信箱データベースID: {inbox_db_id}")
        
        # .env ファイルに NOTION_INBOX_DATABASE_ID を追記する
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            # すでに定義があるかチェックし、なければ追記、あれば置換
            if "NOTION_INBOX_DATABASE_ID=" in content:
                lines = content.splitlines()
                new_lines = []
                for line in lines:
                    if line.startswith("NOTION_INBOX_DATABASE_ID="):
                        new_lines.append(f'NOTION_INBOX_DATABASE_ID="{inbox_db_id}"')
                    else:
                        new_lines.append(line)
                new_content = "\n".join(new_lines) + "\n"
            else:
                new_content = content.rstrip() + f'\n\n# Notion Inbox Database ID for raw notes\nNOTION_INBOX_DATABASE_ID="{inbox_db_id}"\n'
                
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(" -> .env ファイルに NOTION_INBOX_DATABASE_ID を自動更新しました。")
            
        print("\n⚠️ 【重要】")
        print("GitHub Secrets に「NOTION_INBOX_DATABASE_ID」という名前で、上記の新IDを登録してください。")
        return inbox_db_id
    else:
        print(f"\n[Error] 受信箱データベースの作成に失敗しました。")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        return None

if __name__ == "__main__":
    create_inbox_database()
