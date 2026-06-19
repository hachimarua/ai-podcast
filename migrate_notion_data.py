import os
import re
import requests
from datetime import datetime
from dotenv import load_dotenv

# 環境変数の読み込み
load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_PARENT_PAGE_ID = "35d142da197280b3ae74f921ac365125"

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def parse_date_from_title(title):
    match = re.search(r"(\d{4})(\d{2})(\d{2})", title)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month}-{day}"
    return None

def clean_block_object(block_dict):
    """
    APIリクエストのバリデーションエラーを防ぐため、
    オブジェクト内の null キー（特に icon, color 等）やシステム用の不要なキーを再帰的に削除。
    """
    if not isinstance(block_dict, dict):
        return block_dict
        
    cleaned = {}
    for k, v in block_dict.items():
        # 作成リクエストで null が入るとエラーになるキーを排除
        if k in ["icon", "color"] and v is None:
            continue
        # IDや自動作成・更新日などのシステムキーを削除
        if k in ["id", "parent", "created_time", "last_edited_time", "created_by", "last_edited_by", "has_children"]:
            continue
        if v is None:
            continue
            
        if isinstance(v, dict):
            cleaned[k] = clean_block_object(v)
        elif isinstance(v, list):
            cleaned[k] = [clean_block_object(item) if isinstance(item, dict) else item for item in v]
        else:
            cleaned[k] = v
    return cleaned

def fetch_page_blocks(page_id):
    """旧ページの全子ブロックを取得・クリーンアップし、復習履歴を抽出"""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    try:
        response = requests.get(url, headers=HEADERS)
        if response.status_code != 200:
            return [], 0, None
            
        data = response.json()
        blocks = data.get("results", [])
        
        cleaned_blocks = []
        review_count = 0
        last_reviewed = None
        
        for block in blocks:
            block_type = block.get("type")
            # 復習履歴のパース
            if block_type in ["paragraph", "bulleted_list_item", "numbered_list_item"]:
                rich_text = block.get(block_type, {}).get("rich_text", [])
                plain_text = "".join([t.get("plain_text", "") for t in rich_text])
                
                match = re.search(r"📝\s*復習履歴:\s*(\d+)回目\s*\(最終:\s*([\d-]+)\)", plain_text)
                if match:
                    review_count = max(review_count, int(match.group(1)))
                    last_reviewed = match.group(2)
                    continue # 履歴ブロック自体は本文コピーから除外
            
            # コピー可能なブロックタイプ
            if block_type in ["paragraph", "bulleted_list_item", "numbered_list_item", "heading_1", "heading_2", "heading_3", "code", "quote"]:
                # ブロックのクリーンアップを実行
                raw_block = {
                    "object": "block",
                    "type": block_type,
                    block_type: block.get(block_type)
                }
                cleaned_block = clean_block_object(raw_block)
                cleaned_blocks.append(cleaned_block)
                
        return cleaned_blocks, review_count, last_reviewed
    except Exception as e:
        print(f"[Warning] Failed to fetch/parse blocks of page {page_id}: {e}")
        return [], 0, None

def migrate_data():
    if not NOTION_API_KEY or not NOTION_DATABASE_ID or "YOUR_" in NOTION_API_KEY:
        print("[Error] .env ファイルの設定が不十分です。")
        return
        
    print("--- Notion データ一括移行を開始します (再サニタイズ版) ---")
    
    url = f"https://api.notion.com/v1/blocks/{NOTION_PARENT_PAGE_ID}/children"
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        print(f"[Error] 親ページの子要素の取得に失敗しました: {response.text}")
        return
        
    data = response.json()
    child_pages = []
    
    for block in data.get("results", []):
        if block.get("type") == "child_page":
            page_id = block.get("id")
            title = block.get("child_page", {}).get("title", "無題")
            
            # DB自身、およびすでに移行完了したページはスキップ
            if title == "AI学習データベース" or title.startswith("[Migrated]"):
                continue
                
            child_pages.append((page_id, title))
            
    print(f"未移行の対象日記ページが {len(child_pages)} 件見つかりました。")
    
    success_count = 0
    for idx, (page_id, title) in enumerate(child_pages, 1):
        print(f"\n[{idx}/{len(child_pages)}] 移行中: {title} ...")
        
        # 中身ブロックの取得とクリーンアップ
        blocks, review_count, last_reviewed = fetch_page_blocks(page_id)
        
        # 日付のパース
        parsed_date = parse_date_from_title(title)
        
        create_url = "https://api.notion.com/v1/pages"
        properties = {
            "名前": {
                "title": [
                    {
                        "text": {
                            "content": title
                        }
                    }
                ]
            },
            "復習回数": {
                "number": review_count
            },
            "元のページ名": {
                "rich_text": [
                    {
                        "text": {
                            "content": title
                        }
                    }
                ]
            }
        }
        
        if parsed_date:
            properties["学習日"] = {"date": {"start": parsed_date}}
        if last_reviewed:
            properties["最終復習日"] = {"date": {"start": last_reviewed}}
            
        payload = {
            "parent": {
                "database_id": NOTION_DATABASE_ID
            },
            "properties": properties,
            "children": blocks[:100]
        }
        
        create_response = requests.post(create_url, headers=HEADERS, json=payload)
        
        if create_response.status_code == 200:
            print(f" -> 新データベースへのインポート成功 (復習回数: {review_count})")
            
            # 元の旧日記ページのタイトルを変更して「移行済」マークをつける
            update_page_url = f"https://api.notion.com/v1/pages/{page_id}"
            update_payload = {
                "properties": {
                    "title": [
                        {
                            "text": {
                                "content": f"[Migrated] {title}"
                            }
                        }
                    ]
                }
            }
            requests.patch(update_page_url, headers=HEADERS, json=update_payload)
            success_count += 1
        else:
            print(f" -> [Error] 新データベースへのインポートに失敗しました: {create_response.text}")
            
    print("\n==================================================")
    print(f" 移行処理が完了しました！成功: {success_count} / 全体: {len(child_pages)}")
    print("==================================================")

if __name__ == "__main__":
    migrate_data()
