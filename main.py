import os
import sys
import asyncio
from datetime import datetime, timezone, timedelta
from mutagen.mp3 import MP3
from dotenv import load_dotenv
from notion_helper import select_terms_for_review, update_term_review_status, is_notion_configured
from news_collector import collect_latest_news, match_news_with_words
from script_generator import generate_radio_script
from audio_generator import synthesize_podcast
from podcast_generator import archive_today_podcast, generate_podcast_rss
from episode_history import (
    build_manifest,
    exclude_recent_news,
    load_recent_manifests,
    max_recent_similarity,
    write_manifest_atomic,
)
from audio_quality import require_audio_quality
from gemini_audio_qa import run_shadow_audio_qa, write_improvement_proposal

async def async_main():
    print("==================================================")
    print("   AI News & Notion Learning System - Full Pipeline")
    print("==================================================")
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    manifests_dir = os.path.join(base_dir, "episode_manifests")
    recent_manifests = load_recent_manifests(manifests_dir, limit=3)
    recent_topics = [
        manifest.get("primary_topic", "")
        for manifest in recent_manifests
        if manifest.get("primary_topic")
    ]
    
    # 1. Notion(またはモック)から復習用語を抽出
    print("\n[Step 1] Notionから復習用語を抽出しています...")
    selected_terms = select_terms_for_review(3, recent_manifests=recent_manifests)
    if not selected_terms:
        print("過去3回または直近3日と重ならない復習項目がないため、最新ニュース特集へ切り替えます。")
    else:
        print("【本日の復習用語】:")
        for term in selected_terms:
            print(f" - {term['name']} (これまでの復習回数: {term['review_count']}回, 前回復習日: {term['last_reviewed'] or 'なし'})")
        
    # 2. ホワイトリストソースからニュースを収集
    print("\n[Step 2] 信頼できるソース(ホワイトリスト)から最新ニュースを収集しています...")
    all_news = collect_latest_news(max_entries_per_feed=5)
    all_news, recent_news_removed = exclude_recent_news(all_news, recent_manifests)
    print(
        f"新規ニュース {len(all_news)} 件を採用候補にしました。"
        f"過去3回で使用済みの {recent_news_removed} 件は除外しました。"
    )
    if not all_news and not selected_terms:
        raise RuntimeError(
            "No fresh Notion terms or news remain after the past-three-episodes filter"
        )
    
    # 3. ニュースと用語のマッチング
    print("\n[Step 3] ニュースと復習用語の関連性をチェックしています...")
    matched, unmatched = match_news_with_words(all_news, selected_terms)
    print(f"関連ニュース: {len(matched)} 件 / その他のニュース: {len(unmatched)} 件")
    
    for m in matched:
        print(f" -> 関連あり: [{m['source']}] {m['title']} (マッチ用語: {m['matched_words']})")
        
    # 4. Gemini APIを用いて日本語対話ラジオ台本を生成
    print("\n[Step 4] Gemini APIを呼び出し、対話型ラジオ台本を生成しています...")
    model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-3.1-pro")
    print(f"使用モデル: {model_name}")
    
    script = generate_radio_script(
        selected_terms,
        matched,
        unmatched,
        model_name=model_name,
        avoid_topics=recent_topics,
    )
    
    if not script:
        print("[Error] 台本の生成に失敗しました。")
        sys.exit(1)
        
    duplicate_threshold = float(os.getenv("DUPLICATE_SIMILARITY_THRESHOLD", "0.82"))
    if not 0.0 <= duplicate_threshold <= 1.0:
        raise ValueError("DUPLICATE_SIMILARITY_THRESHOLD must be between 0 and 1")
    first_similarity = max_recent_similarity(script, recent_manifests)
    used_news_only_fallback = False

    if first_similarity >= duplicate_threshold:
        print(
            f"[Duplicate Gate] 過去3回との類似度 {first_similarity:.2f}。"
            "復習項目を外した最新ニュース特集として1回だけ再生成します。"
        )
        script = generate_radio_script(
            [],
            [],
            all_news,
            model_name=model_name,
            avoid_topics=recent_topics,
        )
        if not script:
            raise RuntimeError("Duplicate fallback script generation failed")
        selected_terms = []
        matched = []
        unmatched = all_news
        used_news_only_fallback = True

    final_similarity = max_recent_similarity(script, recent_manifests)
    if final_similarity >= duplicate_threshold:
        raise RuntimeError(
            f"Generated script is too similar to a recent episode ({final_similarity:.2f}); publication stopped"
        )

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

    audio_quality = require_audio_quality(output_mp3_path)
    print(
        "音声品質ゲート通過: "
        f"{audio_quality['duration_seconds']:.1f}秒, "
        f"平均{audio_quality['mean_volume_db']:.1f}dB, "
        f"最大{audio_quality['max_volume_db']:.1f}dB"
    )
    gemini_qa = run_shadow_audio_qa(output_mp3_path)
    print(f"Gemini音声シャドー監査: {gemini_qa.get('status')}")
        
    # 6. ポッドキャストXML(RSSフィード)の生成とアーカイブ保存 (GitHub Actions上でのみ本番アーカイブを更新)
    print("\n[Step 6] ポッドキャストRSSフィードを生成し、アーカイブを更新しています...")
    if os.getenv("GITHUB_ACTIONS") == "true":
        archived_filename = archive_today_podcast()
        if archived_filename:
            JST = timezone(timedelta(hours=9))
            broadcast_date = datetime.now(JST).strftime("%Y-%m-%d")
            episode_id = os.path.splitext(archived_filename)[0]
            archived_path = os.path.join(base_dir, "episodes", archived_filename)
            duration_seconds = int(MP3(archived_path).info.length)
            primary_topic = (
                selected_terms[0]["name"]
                if selected_terms
                else (all_news[0]["title"] if all_news else "最新AIニュース")
            )
            used_news = matched + unmatched[:2]
            manifest = build_manifest(
                episode_id=episode_id,
                broadcast_date=broadcast_date,
                selected_terms=selected_terms,
                primary_topic=primary_topic,
                news_urls=[item.get("link", "") for item in used_news],
                script=script,
                audio_path=archived_path,
                duration_seconds=duration_seconds,
                deterministic_checks={
                    "recent_episode_count": len(recent_manifests),
                    "initial_script_similarity": round(first_similarity, 4),
                    "final_script_similarity": round(final_similarity, 4),
                    "duplicate_threshold": duplicate_threshold,
                    "used_news_only_fallback": used_news_only_fallback,
                    "audio_quality": audio_quality,
                },
                publish_status="published",
                gemini_qa_summary=gemini_qa,
            )
            manifest_path = write_manifest_atomic(manifest, manifests_dir)
            print(f"Episode manifest saved: {manifest_path}")
            proposal_path = write_improvement_proposal(
                qa_result=gemini_qa,
                episode_id=episode_id,
                broadcast_date=broadcast_date,
                reports_dir=os.path.join(base_dir, "quality_reports"),
            )
            if proposal_path:
                print(f"Audio improvement proposal saved: {proposal_path}")
            generate_podcast_rss()
        else:
            print("[Error] 音声ファイルのアーカイブに失敗しました。")
            sys.exit(1)
    else:
        print("ローカル環境での実行を検知しました。配信RSSとepisodes/へのアーカイブは更新せず、todays_podcast.mp3 の生成のみに留めます。")
    
    # 7. Notion側の復習履歴をアップデート (すべてのステップが成功した後にのみ更新)
    print("\n[Step 7] Notion DBの復習回数と日付を更新しています...")
    if not selected_terms:
        print("ニュース特集として生成したため、Notionの復習履歴は更新しません。")
    else:
        for term in selected_terms:
            update_term_review_status(term["id"], term["review_count"])
        if is_notion_configured():
            print("Notion DBの更新がすべて正常に完了しました！")
        else:
            print("ローカルモックDB(notion_mock_db.json)の更新が完了しました。")
        
    print("\n==================================================")
    print(" 全自動AIニュース学習音声化処理が正常に完了しました！")
    print("==================================================")

def main():
    load_dotenv()
    try:
        # 非同期メイン関数を実行
        asyncio.run(async_main())
    except Exception as exc:
        print(f"[Fatal] Pipeline stopped safely: {type(exc).__name__}: {exc}")
        raise SystemExit(1) from exc

if __name__ == "__main__":
    main()
