import os
import requests
from dotenv import load_dotenv

# 環境変数の読み込み
load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

def setup_database_properties():
    if not NOTION_API_KEY or not NOTION_DATABASE_ID or "YOUR_" in NOTION_API_KEY:
        print("[Error] .env ファイルの NOTION_API_KEY または NOTION_DATABASE_ID が正しく設定されていません。")
        print("まずは .env ファイルにキーを設定し、Notionデータベース側でインテグレーションが接続されていることを確認してください。")
        return False
        
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    # データベースに新しく追加するプロパティ（スキーマ）の定義
    payload = {
        "properties": {
            "復習回数": {
                "number": {
                    "format": "number"
                }
            },
            "最終復習日": {
                "date": {}
            }
        }
    }
    
    print("Notion データベースのプロパティを更新しています...")
    response = requests.patch(url, headers=headers, json=payload)
    
    if response.status_code == 200:
        print("\n🎉 成功しました！")
        print("データベースに以下のプロパティが正常に追加されました：")
        print(" - 復習回数 (Number)")
        print(" - 最終復習日 (Date)")
        return True
    else:
        print(f"\n[Error] Notionデータベースの更新に失敗しました。")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        print("\n【よくある原因】")
        print("1. Notionデータベースの右上「...」から「接続先」に今回のインテグレーションが登録されていない")
        print("2. .env に記述したインテグレーションキーまたはデータベースIDが間違っている")
        return False

if __name__ == "__main__":
    setup_database_properties()
