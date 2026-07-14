import os
import sys
import asyncio
from datetime import datetime
from mutagen.mp3 import MP3
from dotenv import load_dotenv
from notion_helper import select_terms_for_review, update_term_review_status, is_notion_configured
from news_collector import (
    LabSourceError,
    collect_latest_news,
    match_news_with_words,
    select_news_for_broadcast,
    select_news_for_lab,
)
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
from editorial_profile import get_approved_profile_version
from episode_formats import (
    EpisodeFormatError,
    JST,
    load_episode_formats,
    resolve_episode_format,
    validate_script_length,
)
from gemini_audio_qa import run_shadow_audio_qa, write_improvement_proposal
from gemini_models import normalize_gemini_model
from phase10_trial import (
    build_trial_report,
    match_news_for_trial_anchor,
    phase10_trial_anchor,
    phase10_trial_enabled,
    trial_paths,
    write_trial_report_atomic,
)


def terms_requiring_review_update(selected_terms, broadcast_date):
    """Return terms whose absolute review state is not yet reflected for this date."""
    return [
        term
        for term in selected_terms
        if str(term.get("last_reviewed") or "")[:10] != broadcast_date
    ]


def should_update_notion_review(existing_today, selected_terms, broadcast_date=None):
    """Compatibility predicate backed by the term's persisted review date."""
    if broadcast_date is None:
        return not existing_today and bool(selected_terms)
    return bool(terms_requiring_review_update(selected_terms, broadcast_date))


def split_run_manifests(manifests, broadcast_date, *, history_limit=3):
    """Separate today's published episode from prior comparison history."""
    existing_today = next(
        (
            manifest
            for manifest in manifests
            if manifest.get("broadcast_date") == broadcast_date
            and manifest.get("publish_status") == "published"
        ),
        None,
    )
    history = [
        manifest
        for manifest in manifests
        if manifest.get("broadcast_date") != broadcast_date
    ][:history_limit]
    return existing_today, history


async def async_main():
    print("==================================================")
    print("   AI News & Notion Learning System - Full Pipeline")
    print("==================================================")
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    manifests_dir = os.path.join(base_dir, "episode_manifests")
    recent_manifests = load_recent_manifests(manifests_dir, limit=4)
    run_now_jst = datetime.now(JST)
    trial_mode = phase10_trial_enabled()
    trial_anchor = phase10_trial_anchor() if trial_mode else None
    trial_artifacts = trial_paths(base_dir, run_now_jst) if trial_mode else None
    broadcast_date = run_now_jst.strftime("%Y-%m-%d")
    existing_today, history_manifests = split_run_manifests(
        recent_manifests, broadcast_date
    )
    formats_config = load_episode_formats()
    editorial_profile_version = get_approved_profile_version()
    scheduled_format = (
        "lab"
        if trial_mode
        else resolve_episode_format(
            formats_config,
            now_jst=run_now_jst,
            existing_format=(existing_today or {}).get("episode_format"),
        )
    )
    episode_format = scheduled_format
    format_spec = formats_config.formats[episode_format]
    format_fallback_reason = None
    print(
        f"番組形式: {format_spec.display_name} ({format_spec.duration_label}) "
        f"/ config={formats_config.config_version}"
    )
    if trial_mode:
        print("Phase 10非公開トライアル: RSS・episodes・Notionは更新しません。")
    recent_topics = [
        manifest.get("primary_topic", "")
        for manifest in history_manifests
        if manifest.get("primary_topic")
    ]
    
    # 1. Notion(またはモック)から復習用語を抽出
    print("\n[Step 1] Notionから復習用語を抽出しています...")
    if trial_anchor:
        selected_terms = []
        print(
            f"Phase 10固定テーマ {trial_anchor} を使用するため、"
            "Notionの復習項目は読み込みません。"
        )
    else:
        selected_terms = select_terms_for_review(
            format_spec.max_review_terms,
            recent_manifests=history_manifests,
            preferred_term_keys=(existing_today or {}).get("selected_term_keys"),
        )
    if not trial_anchor:
        if not selected_terms:
            print("過去3回または直近3日と重ならない復習項目がないため、最新ニュース特集へ切り替えます。")
        else:
            print(f"【本日の復習用語】: {len(selected_terms)}件を採用しました。")
        
    # 2. ホワイトリストソースからニュースを収集
    print("\n[Step 2] 信頼できるソース(ホワイトリスト)から最新ニュースを収集しています...")
    all_news = collect_latest_news(max_entries_per_feed=10 if trial_anchor else 5)
    all_news, recent_news_removed = exclude_recent_news(all_news, history_manifests)
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
    if trial_anchor:
        matched, unmatched = match_news_for_trial_anchor(all_news, trial_anchor)
    else:
        matched, unmatched = match_news_with_words(all_news, selected_terms)
    print(f"関連ニュース: {len(matched)} 件 / その他のニュース: {len(unmatched)} 件")
    
    for m in matched:
        print(f" -> 関連あり: [{m['source']}] {m['title']}")

    if episode_format == "lab":
        try:
            broadcast_news, news_selection = select_news_for_lab(
                matched, history_manifests, max_items=format_spec.max_news_items
            )
        except LabSourceError as exc:
            if trial_mode or (
                existing_today and existing_today.get("episode_format") == "lab"
            ):
                raise
            format_fallback_reason = "insufficient_multi_source_official_basis"
            print(f"[Format Fallback] {exc}; Daily Briefへ切り替えます。")
            episode_format = "daily"
            format_spec = formats_config.formats[episode_format]
            broadcast_news, news_selection = select_news_for_broadcast(
                matched,
                unmatched,
                history_manifests,
                max_items=format_spec.max_news_items,
            )
    else:
        broadcast_news, news_selection = select_news_for_broadcast(
            matched,
            unmatched,
            history_manifests,
            max_items=format_spec.max_news_items,
        )
    if not broadcast_news:
        raise RuntimeError("No news candidates remain for the five-minute broadcast")
    selected_matched = [item for item in broadcast_news if item["_matched_for_review"]]
    selected_general = [item for item in broadcast_news if not item["_matched_for_review"]]
    print(f"本日のニュース構成（{format_spec.display_name} 1本）:")
    for item in broadcast_news:
        print(
            f" -> [{item['lane']}] [{item['source']}] {item['title']}"
            f" ({item['_selection_reason']})"
        )
        
    # 4. Gemini APIを用いて日本語対話ラジオ台本を生成
    print("\n[Step 4] Gemini APIを呼び出し、対話型ラジオ台本を生成しています...")
    model_name = normalize_gemini_model(os.getenv("GEMINI_MODEL_NAME"))
    print(f"使用モデル: {model_name}")
    
    script = generate_radio_script(
        selected_terms,
        selected_matched,
        selected_general,
        model_name=model_name,
        avoid_topics=recent_topics,
        episode_format=episode_format,
        spec=format_spec,
    )
    
    if not script:
        print("[Error] 台本の生成に失敗しました。")
        sys.exit(1)
        
    duplicate_threshold = float(os.getenv("DUPLICATE_SIMILARITY_THRESHOLD", "0.82"))
    if not 0.0 <= duplicate_threshold <= 1.0:
        raise ValueError("DUPLICATE_SIMILARITY_THRESHOLD must be between 0 and 1")
    first_similarity = max_recent_similarity(script, history_manifests)
    used_news_only_fallback = False

    if first_similarity >= duplicate_threshold:
        if episode_format == "lab":
            raise RuntimeError(
                f"Lab script is too similar to a recent episode ({first_similarity:.2f}); "
                "automatic news-only conversion is not allowed"
            )
        print(
            f"[Duplicate Gate] 過去3回との類似度 {first_similarity:.2f}。"
            "復習項目を外した最新ニュース特集として1回だけ再生成します。"
        )
        broadcast_news, news_selection = select_news_for_broadcast(
            [], all_news, history_manifests, max_items=format_spec.max_news_items
        )
        script = generate_radio_script(
            [],
            [],
            broadcast_news,
            model_name=model_name,
            avoid_topics=recent_topics,
            episode_format=episode_format,
            spec=format_spec,
        )
        if not script:
            raise RuntimeError("Duplicate fallback script generation failed")
        selected_terms = []
        selected_matched = []
        selected_general = broadcast_news
        used_news_only_fallback = True

    final_similarity = max_recent_similarity(script, history_manifests)
    if final_similarity >= duplicate_threshold:
        raise RuntimeError(
            f"Generated script is too similar to a recent episode ({final_similarity:.2f}); publication stopped"
        )

    try:
        script_length = validate_script_length(script, format_spec)
    except EpisodeFormatError:
        if episode_format != "lab":
            raise
        print(
            "[Length Gate] Lab台本が規定文字数外のため、同じ出典のまま1回だけ再生成します。"
        )
        script = generate_radio_script(
            selected_terms,
            selected_matched,
            selected_general,
            model_name=model_name,
            avoid_topics=recent_topics,
            episode_format=episode_format,
            spec=format_spec,
            length_retry=True,
        )
        if not script:
            raise RuntimeError("Lab length retry script generation failed")
        final_similarity = max_recent_similarity(script, history_manifests)
        if final_similarity >= duplicate_threshold:
            raise RuntimeError(
                f"Length retry script is too similar to a recent episode ({final_similarity:.2f}); "
                "publication stopped"
            )
        script_length = validate_script_length(script, format_spec)

    # 台本の保存
    if trial_mode:
        trial_artifacts["directory"].mkdir(parents=True, exist_ok=False)
        script_path = str(trial_artifacts["script"])
    else:
        script_path = os.path.join(base_dir, "todays_script.txt")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)
    print(f"台本を保存しました: {script_path}")
    
    # 5. 音声合成 (TTS) による対話音声の生成
    print("\n[Step 5] Edge TTSを使用して対話型音声ファイル(MP3)を合成しています...")
    output_mp3_path = (
        str(trial_artifacts["audio"])
        if trial_mode
        else os.path.join(base_dir, "todays_podcast.mp3")
    )
    
    # 音声合成を実行 (非同期処理)
    synthesis_success = await synthesize_podcast(
        script_path, output_mp3_path, speech_rate=format_spec.speech_rate
    )
    if not synthesis_success:
        print("[Error] 音声合成に失敗しました。パイプラインを中断します。")
        sys.exit(1)

    audio_quality = require_audio_quality(
        output_mp3_path, format_spec.audio_thresholds.to_runtime()
    )
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
    if trial_mode:
        public_topic = (
            broadcast_news[0].get("title", "最新AIニュース")
            if broadcast_news
            else "最新AIニュース"
        )
        report = build_trial_report(
            trial_id=trial_artifacts["directory"].name,
            generated_at=run_now_jst.isoformat(),
            editorial_profile_version=editorial_profile_version,
            format_config_version=formats_config.config_version,
            public_topic=public_topic,
            news_urls=[item.get("link", "") for item in broadcast_news],
            script=script,
            audio_path=output_mp3_path,
            deterministic_checks={
                "recent_episode_count": len(history_manifests),
                "initial_script_similarity": round(first_similarity, 4),
                "final_script_similarity": round(final_similarity, 4),
                "duplicate_threshold": duplicate_threshold,
                "used_news_only_fallback": used_news_only_fallback,
                "news_selection": news_selection,
                "audio_quality": audio_quality,
                "script_length": script_length,
                "scheduled_format": scheduled_format,
                "format_fallback_reason": format_fallback_reason,
                "format_config_version": formats_config.config_version,
            },
            qa_result=gemini_qa,
        )
        report_path = write_trial_report_atomic(trial_artifacts["report"], report)
        print(f"Phase 10非公開トライアルを保存しました: {report_path.parent}")
    elif os.getenv("GITHUB_ACTIONS") == "true":
        archived_filename = archive_today_podcast(now=run_now_jst)
        if archived_filename:
            episode_id = os.path.splitext(archived_filename)[0]
            archived_path = os.path.join(base_dir, "episodes", archived_filename)
            duration_seconds = int(MP3(archived_path).info.length)
            public_topic = (
                broadcast_news[0].get("title", "最新AIニュース")
                if broadcast_news
                else "最新AIニュース"
            )
            primary_topic = public_topic
            used_news = broadcast_news
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
                    "recent_episode_count": len(history_manifests),
                    "initial_script_similarity": round(first_similarity, 4),
                    "final_script_similarity": round(final_similarity, 4),
                    "duplicate_threshold": duplicate_threshold,
                    "used_news_only_fallback": used_news_only_fallback,
                    "news_selection": news_selection,
                    "audio_quality": audio_quality,
                    "script_length": script_length,
                    "scheduled_format": scheduled_format,
                    "format_fallback_reason": format_fallback_reason,
                    "format_config_version": formats_config.config_version,
                },
                publish_status="published",
                gemini_qa_summary=gemini_qa,
                episode_format=episode_format,
                editorial_profile_version=editorial_profile_version,
                public_topic=public_topic,
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
    pending_review_terms = terms_requiring_review_update(
        selected_terms, broadcast_date
    )
    if trial_mode:
        print("Phase 10非公開トライアルのため、Notionの復習履歴は更新しません。")
    elif not selected_terms:
        print("ニュース特集として生成したため、Notionの復習履歴は更新しません。")
    elif not pending_review_terms:
        print("当日の復習履歴は反映済みのため、Notionを再更新しません。")
    elif should_update_notion_review(
        existing_today, selected_terms, broadcast_date=broadcast_date
    ):
        for term in pending_review_terms:
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
