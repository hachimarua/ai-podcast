import os
import sys
import asyncio
from dotenv import load_dotenv
from notion_helper import select_terms_for_review, update_term_review_status, is_notion_configured
from news_collector import collect_latest_news, match_news_with_words
from script_generator import generate_radio_script
from audio_generator import synthesize_podcast
from podcast_generator import archive_today_podcast, generate_podcast_rss

async def async_main():
    print("==================================================")
    print("   AI News & Notion Learning System - Full Pipeline")
    print("==================================================")
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Notion(またはモック)から復習用語を抽出
    print("\n[Step 1] Notionから復習用語を抽出しています...")
    selected_terms = select_terms_for_review(3)
    if not selected_terms:
        print("[Error] 復習対象の用語が見つかりませんでした。")
        sys.exit(1)
        
    print("【本日の復習用語】:")
    for term in selected_terms:
        print(f" - {term['name']} (これまでの復習回数: {term['review_count']}回, 前回復習日: {term['last_reviewed'] or 'なし'})")
        
    # 2. ホワイトリストソースからニュースを収集
    print("\n[Step 2] 信頼できるソース(ホワイトリスト)から最新ニュースを収集しています...")
    all_news = collect_latest_news(max_entries_per_feed=5)
    print(f"合計 {len(all_news)} 件の最新ニュースをフェッチしました。")
    
    # 3. ニュースと用語のマッチング
    print("\n[Step 3] ニュースと復習用語の関連性をチェックしています...")
    matched, unmatched = match_news_with_words(all_news, selected_terms)
    print(f"関連ニュース: {len(matched)} 件 / その他のニュース: {len(unmatched)} 件")
    
    for m in matched:
        print(f" -> 関連あり: [{m['source']}] {m['title']} (マッチ用語: {m['matched_words']})")
        
    # 4. Gemini APIを用いて日本語対話ラジオ台本を生成
    print("\n[Step 4] Gemini APIを呼び出し、対話型ラジオ台本を生成しています...")
    model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash")
    print(f"使用モデル: {model_name}")
    
    script = generate_radio_script(selected_terms, matched, unmatched, model_name=model_name)
    
    if not script:
        print("[Error] 台本の生成に失敗しました。")
        sys.exit(1)
        
    # 台本の保存
    script_path = os.path.join(base_dir, "todays_script.txt")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)
    print(f"台本を保存しました: {script_path}")
    
    # 5. 音声合成 (TTS) による対話音声の生成
    print("\n[Step 5] Edge TTSを使用して対話型音声ファイル(MP3)を合成しています...")
    output_mp3_path = os.path.join(base_dir, "todays_podcast.mp3")
    
    # 音声合成を実行 (非同期処理)
    synthesis_success = await synthesize_podcast(script_path, output_mp3_path)
    if not synthesis_success:
        print("[Error] 音声合成に失敗しました。パイプラインを中断します。")
        sys.exit(1)
        
    # 6. ポッドキャストXML(RSSフィード)の生成とアーカイブ保存
    print("\n[Step 6] ポッドキャストRSSフィードを生成し、アーカイブを更新しています...")
    archived_filename = archive_today_podcast()
    if archived_filename:
        generate_podcast_rss()
    else:
        print("[Error] 音声ファイルのアーカイブに失敗しました。")
        sys.exit(1)
    
    # 7. Notion側の復習履歴をアップデート (すべてのステップが成功した後にのみ更新)
    print("\n[Step 7] Notion DBの復習回数と日付を更新しています...")
    update_success = True
    for term in selected_terms:
        success = update_term_review_status(term["id"], term["review_count"])
        if not success:
            update_success = False
            
    if update_success:
        if is_notion_configured():
            print("Notion DBの更新がすべて正常に完了しました！")
        else:
            print("ローカルモックDB(notion_mock_db.json)の更新が完了しました。")
    else:
        print("[Warning] 一部の用語のステータス更新に失敗しました。")
        
    print("\n==================================================")
    print(" 全自動AIニュース学習音声化処理が正常に完了しました！")
    print("==================================================")

def main():
    load_dotenv()
    # 非同期メイン関数を実行
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
