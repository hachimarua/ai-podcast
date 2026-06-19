import os
import requests
from dotenv import load_dotenv

# 環境変数の読み込み
load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_PARENT_PAGE_ID = os.getenv("NOTION_DATABASE_ID") # 現在親ページのIDが入っています

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def create_new_database():
    if not NOTION_API_KEY or not NOTION_PARENT_PAGE_ID or "YOUR_" in NOTION_API_KEY:
        print("[Error] .env ファイルの API キーまたは親ページIDが正しく設定されていません。")
        return False
        
    url = "https://api.notion.com/v1/databases"
    
    # データベースの設計
    payload = {
        "parent": {
            "type": "page_id",
            "page_id": NOTION_PARENT_PAGE_ID
        },
        "title": [
            {
                "type": "text",
                "text": {
                    "content": "AI学習データベース"
                }
            }
        ],
        "properties": {
            "名前": {
                "title": {}
            },
            "復習回数": {
                "number": {
                    "format": "number"
                }
            },
            "最終復習日": {
                "date": {}
            },
            "学習日": {
                "date": {}
            },
            "元のページ名": {
                "rich_text": {}
            }
        }
    }
    
    print(f"親ページ {NOTION_PARENT_PAGE_ID} の配下に新規データベースを作成しています...")
    response = requests.post(url, headers=HEADERS, json=payload)
    
    if response.status_code == 200:
        data = response.json()
        db_id = data.get("id").replace("-", "") # ハイフンを除去した32桁のID
        print("\n🎉 データベースの自動作成に成功しました！")
        print(f"作成されたDBのタイトル: {data.get('title', [{}])[0].get('plain_text')}")
        print(f"新規データベースID: {db_id}")
        
        # .env ファイルの NOTION_DATABASE_ID を新しいデータベースIDに自動で書き換える
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            new_lines = []
            for line in lines:
                if line.startswith("NOTION_DATABASE_ID="):
                    new_lines.append(f'NOTION_DATABASE_ID="{db_id}"\n')
                    print(f" -> .env ファイルの NOTION_DATABASE_ID を自動更新しました。")
                else:
                    new_lines.append(line)
                    
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
                
        print("\n⚠️ 【重要】次のステップに進む前に")
        print("GitHub Secrets の NOTION_DATABASE_ID も、上記の新IDに上書き更新してください。")
        return db_id
    else:
        print(f"\n[Error] データベースの作成に失敗しました。")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        return None

if __name__ == "__main__":
    create_new_database()
