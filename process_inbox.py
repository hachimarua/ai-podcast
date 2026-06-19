import os
import sys
import requests
from datetime import datetime
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from dotenv import load_dotenv
import json
from notion_helper import is_notion_configured

# 環境変数の読み込み
load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID") # メイン学習DB ID
NOTION_INBOX_DATABASE_ID = os.getenv("NOTION_INBOX_DATABASE_ID") # 受信箱DB ID
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# 1. Gemini構造化出力用のPydanticモデル定義
class StructuredStudyLog(BaseModel):
    title: str = Field(description="学習した技術や用語の簡潔な名前。例: 'RAG', 'Model Context Protocol', 'Fine-Tuning'")
    summary: str = Field(description="学習内容の分かりやすい解説要約（日本語）。マークダウン形式で、箇条書きなどを用いて綺麗に整理すること。")
    study_date: str = Field(description="学習した日付。YYYY-MM-DDの形式。ローデータ内に日付が見当たらない場合は 'today' とする")

def get_gemini_client():
    if not GEMINI_API_KEY or "YOUR_GEMINI" in GEMINI_API_KEY:
        print("[Warning] GEMINI_API_KEY is not set. Cannot run AI processing.")
        return None
    return genai.Client(api_key=GEMINI_API_KEY)

def fetch_inbox_items():
    """受信箱データベース内の全アイテムを取得"""
    url = f"https://api.notion.com/v1/databases/{NOTION_INBOX_DATABASE_ID}/query"
    response = requests.post(url, headers=HEADERS)
    if response.status_code != 200:
        print(f"[Error] Failed to fetch Inbox items: {response.text}")
        return []
    return response.json().get("results", [])

def fetch_page_content(page_id):
    """ページ内の全テキストブロックを結合して取得"""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        return ""
        
    data = response.json()
    texts = []
    for block in data.get("results", []):
        block_type = block.get("type")
        text_element = None
        if block_type in ["paragraph", "bulleted_list_item", "numbered_list_item", "heading_1", "heading_2", "heading_3", "code", "quote"]:
            text_element = block.get(block_type, {}).get("rich_text", [])
        if text_element:
            plain_text = "".join([t.get("plain_text", "") for t in text_element])
            texts.append(plain_text)
            
    return "\n".join(texts)

def parse_markdown_to_notion_blocks(markdown_text):
    """
    簡易的なマークダウンパーサー。
    テキストを行ごとに分割し、Notionブロックの配列に変換する。
    """
    blocks = []
    lines = markdown_text.split("\n")
    
    for line in lines:
        line_strip = line.strip()
        if not line_strip:
            continue
            
        # 箇条書きリストブロックの判定 (- または * で始まるもの)
        if line_strip.startswith(("- ", "* ")):
            content = line_strip[2:]
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                }
            })
        # 番号付きリストブロックの判定 (1. 2. 等で始まるもの)
        elif re.match(r"^\d+\.\s+", line_strip):
            content = re.sub(r"^\d+\.\s+", "", line_strip)
            blocks.append({
                "object": "block",
                "type": "numbered_list_item",
                "numbered_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                }
            })
        # 見出しブロックの判定
        elif line_strip.startswith("### "):
            content = line_strip[4:]
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                }
            })
        elif line_strip.startswith("## "):
            content = line_strip[3:]
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                }
            })
        # 通常の段落ブロック
        else:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": line}}]
                }
            })
            
    return blocks

import re # reモジュールのインポート

def archive_inbox_item(page_id):
    """処理が終わった受信箱アイテムをアーカイブ（ゴミ箱行き）にする"""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {"archived": True}
    response = requests.patch(url, headers=HEADERS, json=payload)
    return response.status_code == 200

def process_inbox():
    if not is_notion_configured() or not NOTION_INBOX_DATABASE_ID:
        print("[Error] .env ファイルの Notion データベース設定が正しくありません。")
        return
        
    client = get_gemini_client()
    if not client:
        print("[Mock Mode] APIキーが設定されていないため、モック動作のみ行います。")
        return
        
    print("--- Notion 受信箱(Inbox)の自動要約・振り分けを開始します ---")
    inbox_items = fetch_inbox_items()
    
    if not inbox_items:
        print("受信箱(Inbox)に未処理のアイテムはありません。")
        return
        
    print(f"受信箱に {len(inbox_items)} 件の未処理アイテムを検知しました。")
    
    for idx, item in enumerate(inbox_items, 1):
        page_id = item.get("id")
        # ページの初期タイトル
        title_list = item.get("properties", {}).get("名前", {}).get("title", [])
        initial_title = title_list[0].get("plain_text", "無題のメモ") if title_list else "無題のメモ"
        
        print(f"\n[{idx}/{len(inbox_items)}] 処理中: '{initial_title}' ...")
        
        # 1. 本文ローデータを取得
        raw_content = fetch_page_content(page_id)
        # 本文が空ならタイトルを代わりにコンテンツとする
        if not raw_content.strip():
            raw_content = initial_title
            
        print(f" -> 読み込んだテキスト量: {len(raw_content)}文字")
        
        # 2. Gemini API で構造化要約
        prompt = f"以下のテキスト（チャットログやメモのローデータ）を解析し、学習用語(title)と、日本語の整理された解説要約(summary)を抽出・整理してください。\n\n【ローデータ】\n{raw_content}"
        
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=StructuredStudyLog,
                    system_instruction="あなたは学習記録を整理する専門のアシスタントです。チャットログや乱雑なメモから、最も重要な技術単語(Title)を1つ特定し、その仕組みやポイントを日本語の整理された箇条書き形式のマークダウン(Summary)に変換してください。",
                    temperature=0.2
                )
            )
            
            # レスポンスJSONのパース
            result_json = json.loads(response.text)
            study_title = result_json.get("title")
            study_summary = result_json.get("summary")
            study_date_str = result_json.get("study_date")
            
            # 日付のフォールバック
            if not study_date_str or study_date_str == "today":
                study_date_str = datetime.today().strftime('%Y-%m-%d')
                
            print(f" -> AIによる抽出結果:\n    [用語名]: {study_title}\n    [日付]: {study_date_str}")
            
            # 3. メインデータベースへ清書登録
            create_url = "https://api.notion.com/v1/pages"
            blocks = parse_markdown_to_notion_blocks(study_summary)
            
            properties = {
                "名前": {
                    "title": [{"text": {"content": study_title}}]
                },
                "復習回数": {
                    "number": 0 # 新規は復習回数0回
                },
                "学習日": {
                    "date": {"start": study_date_str}
                },
                "元のページ名": {
                    "rich_text": [{"text": {"content": initial_title}}]
                }
            }
            
            payload = {
                "parent": {"database_id": NOTION_DATABASE_ID},
                "properties": properties,
                "children": blocks[:100]
            }
            
            create_response = requests.post(create_url, headers=HEADERS, json=payload)
            
            if create_response.status_code == 200:
                print(" -> メインデータベースへの登録成功！")
                # 4. 完了した受信箱アイテムをアーカイブ（消去）
                if archive_inbox_item(page_id):
                    print(" -> 受信箱(Inbox)から処理済みアイテムを消去しました。")
                else:
                    print(" -> [Warning] 受信箱アイテムの消去に失敗しました。")
            else:
                print(f" -> [Error] メインDBへの登録に失敗しました: {create_response.text}")
                
        except Exception as e:
            print(f" -> [Error] AI要約または登録処理中にエラーが発生しました: {e}")
            
    print("\n--- 受信箱の自動振り分け処理が完了しました ---")

if __name__ == "__main__":
    process_inbox()
