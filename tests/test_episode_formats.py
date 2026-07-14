import asyncio
import json
import io
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import episode_formats
import episode_history
import main as pipeline_main
import news_collector
import notion_helper
import podcast_generator
import process_inbox
import script_generator
import phase10_trial


class EpisodeFormatConfigTests(unittest.TestCase):
    def enabled_config(self):
        payload = episode_formats.load_episode_formats().model_dump()
        payload["weekly_lab"]["enabled"] = True
        return episode_formats.EpisodeFormatsConfig.model_validate(payload)

    def test_weekly_lab_starts_on_approved_sunday(self):
        config = episode_formats.load_episode_formats()
        sunday = datetime(2026, 7, 19, 4, 0, tzinfo=episode_formats.JST)
        self.assertTrue(config.weekly_lab.enabled)
        self.assertEqual(
            episode_formats.resolve_episode_format(config, now_jst=sunday, override="auto"),
            "lab",
        )

    def test_phase10_trial_mode_is_a_closed_boolean(self):
        self.assertTrue(phase10_trial.phase10_trial_enabled("true"))
        self.assertFalse(phase10_trial.phase10_trial_enabled("false"))
        with self.assertRaises(phase10_trial.Phase10TrialError):
            phase10_trial.phase10_trial_enabled("yes please")

    def test_phase10_anchor_is_closed_and_matches_public_titles_only(self):
        self.assertEqual(phase10_trial.phase10_trial_anchor("ai_agents"), "ai_agents")
        with self.assertRaises(phase10_trial.Phase10TrialError):
            phase10_trial.phase10_trial_anchor("private custom theme")
        matched, unmatched = phase10_trial.match_news_for_trial_anchor(
            [
                {"title": "Managed Agents update", "content": "unrelated"},
                {"title": "Other update", "content": "agents only in private body"},
            ],
            "ai_agents",
        )
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["matched_words"], ["ai_agents"])
        self.assertEqual(len(unmatched), 1)

    def test_enabled_sunday_selects_lab_and_weekday_selects_daily(self):
        config = self.enabled_config()
        sunday = datetime(2026, 7, 19, 4, 0, tzinfo=episode_formats.JST)
        monday = datetime(2026, 7, 20, 4, 0, tzinfo=episode_formats.JST)
        self.assertEqual(
            episode_formats.resolve_episode_format(config, now_jst=sunday, override="auto"),
            "lab",
        )
        self.assertEqual(
            episode_formats.resolve_episode_format(config, now_jst=monday, override="auto"),
            "daily",
        )

    def test_override_and_same_day_lock_are_closed_enums(self):
        config = episode_formats.load_episode_formats()
        self.assertEqual(episode_formats.resolve_episode_format(config, override="lab"), "lab")
        self.assertEqual(
            episode_formats.resolve_episode_format(
                config, override="daily", existing_format="lab"
            ),
            "lab",
        )
        with self.assertRaises(episode_formats.EpisodeFormatError):
            episode_formats.resolve_episode_format(config, override="lab\n<xml>")

    def test_daily_and_lab_have_independent_length_and_audio_ranges(self):
        config = episode_formats.load_episode_formats()
        daily = config.formats["daily"]
        lab = config.formats["lab"]
        self.assertEqual((daily.audio_thresholds.min_duration_seconds, daily.audio_thresholds.max_duration_seconds), (240.0, 360.0))
        self.assertEqual((lab.audio_thresholds.min_duration_seconds, lab.audio_thresholds.max_duration_seconds), (450.0, 720.0))
        self.assertEqual(daily.speech_rate, "+10%")
        self.assertEqual(lab.speech_rate, "+10%")
        daily_result = episode_formats.validate_script_length("あ" * 1000, daily)
        lab_result = episode_formats.validate_script_length("あ" * 2200, lab)
        self.assertTrue(daily_result["passed"])
        self.assertTrue(lab_result["passed"])
        with self.assertRaises(episode_formats.EpisodeFormatError):
            episode_formats.validate_script_length("あ" * 1000, lab)

    def test_dialogue_style_allows_occasional_reaction_but_rejects_repetition(self):
        natural = "\n".join(
            [
                "アミ：構造化しても、誤り自体は残るんですね。",
                "ケンジ：ここは二つに分けて考えます。",
                "アミ：なるほど、直す仕組みは別に必要なんですね。",
            ]
        )
        self.assertTrue(script_generator.validate_dialogue_style(natural)["passed"])
        repetitive = "\n".join(
            [
                "アミ：そうですね。",
                "ケンジ：その通りです。",
                "アミ：そうですね、次へ進みましょう。",
            ]
        )
        with self.assertRaises(episode_formats.EpisodeFormatError):
            script_generator.validate_dialogue_style(repetitive)

    def test_same_day_rerun_does_not_increment_notion_review(self):
        selected_terms = [
            {"id": "term", "review_count": 1, "last_reviewed": "2026-07-14"}
        ]
        self.assertFalse(
            pipeline_main.should_update_notion_review(
                {"broadcast_date": "2026-07-14", "publish_status": "published"},
                selected_terms,
                broadcast_date="2026-07-14",
            )
        )
        selected_terms[0]["last_reviewed"] = "2026-07-13"
        self.assertTrue(
            pipeline_main.should_update_notion_review(
                {"broadcast_date": "2026-07-14", "publish_status": "published"},
                selected_terms,
                broadcast_date="2026-07-14",
            )
        )

    def test_same_day_manifest_is_excluded_but_three_prior_runs_remain(self):
        manifests = [
            {"broadcast_date": "2026-07-14", "publish_status": "published"},
            {"broadcast_date": "2026-07-13", "publish_status": "published"},
            {"broadcast_date": "2026-07-12", "publish_status": "published"},
            {"broadcast_date": "2026-07-11", "publish_status": "published"},
        ]
        existing, history = pipeline_main.split_run_manifests(
            manifests, "2026-07-14"
        )
        self.assertEqual(existing["broadcast_date"], "2026-07-14")
        self.assertEqual(
            [item["broadcast_date"] for item in history],
            ["2026-07-13", "2026-07-12", "2026-07-11"],
        )

    def test_same_day_rerun_restores_reviewed_term_from_opaque_key(self):
        term = {
            "id": "private-page-id",
            "name": "RAG",
            "review_count": 2,
            "last_reviewed": "2026-07-14",
            "content": "private body",
        }
        key = episode_history.stable_term_key(term["id"])
        with (
            patch.object(notion_helper, "fetch_notion_terms", return_value=[term]),
            patch.object(notion_helper, "is_notion_configured", return_value=False),
        ):
            selected = notion_helper.select_terms_for_review(
                1,
                recent_manifests=[],
                today=datetime(2026, 7, 14).date(),
                preferred_term_keys=[key],
            )
        self.assertEqual(selected, [term])

    def test_same_day_news_only_episode_locks_empty_review_term_set(self):
        term = {
            "id": "new-term",
            "name": "New topic",
            "review_count": 0,
            "last_reviewed": None,
            "content": "private body",
        }
        with (
            patch.object(notion_helper, "fetch_notion_terms", return_value=[term]),
            patch.object(notion_helper, "is_notion_configured", return_value=False),
        ):
            selected = notion_helper.select_terms_for_review(
                1, recent_manifests=[], preferred_term_keys=[]
            )
        self.assertEqual(selected, [])


class FormatPromptTests(unittest.TestCase):
    def news(self, source, title, role="reporting", matched="RAG"):
        return {
            "source": source,
            "title": title,
            "content": "根拠本文",
            "link": f"https://example.test/{title}",
            "evidence_role": role,
            "matched_words": [matched],
        }

    def test_daily_keeps_second_item_optional_and_tips_optional(self):
        prompt = script_generator.build_prompt_content(
            [], [], [self.news("one", "one"), self.news("two", "two")],
            episode_format="daily",
        )
        instruction = script_generator.build_system_instruction("daily")
        self.assertIn("ニュース2は主題を補強できる場合だけ任意", prompt)
        self.assertIn("Tipsは必須ではありません", prompt)
        self.assertIn("4〜6分", instruction)
        self.assertNotIn("3〜5段階の具体手順", instruction)

    def test_lab_requires_one_theme_official_steps_results_and_constraints(self):
        prompt = script_generator.build_prompt_content(
            [],
            [self.news("Google AI Blog", "one", "official")],
            [self.news("ITmedia AI+", "two")],
            episode_format="lab",
        )
        instruction = script_generator.build_system_instruction("lab")
        self.assertIn("Evidence role: official", prompt)
        self.assertIn("1テーマだけ", instruction)
        self.assertIn("3〜5段階の具体手順", instruction)
        self.assertIn("期待結果", instruction)
        self.assertIn("適用しない条件", instruction)
        self.assertIn("8〜12分", instruction)
        self.assertNotIn("ニュース2は主題を補強", instruction)

    def test_lab_generation_rejects_unsafe_sources_before_mock_or_api(self):
        with self.assertRaises(news_collector.LabSourceError):
            script_generator.generate_radio_script(
                [],
                [self.news("Unknown Source", "one", "official")],
                [self.news("ITmedia AI+", "two")],
                episode_format="lab",
            )


class LabSourceSelectionTests(unittest.TestCase):
    def item(self, source, title, matched="RAG"):
        config = news_collector.SOURCE_CONFIG[source]
        return {
            "source": source,
            "title": title,
            "content": "RAGの本文",
            "link": f"https://example.test/{title}",
            "lane": config["lane"],
            "evidence_role": config["evidence_role"],
            "matched_words": [matched],
        }

    def test_lab_selects_same_anchor_from_distinct_sources_with_official_basis(self):
        selected, audit = news_collector.select_news_for_lab(
            [
                self.item("Google AI Blog", "official"),
                self.item("ITmedia AI+", "report"),
                self.item("AI Watch", "report-two"),
            ],
            [],
        )
        self.assertTrue(audit["anchor_present"])
        self.assertNotIn("RAG", json.dumps(audit, ensure_ascii=False))
        self.assertTrue(audit["official_basis_present"])
        self.assertGreaterEqual(len(selected), 2)
        self.assertEqual(len({item["source"] for item in selected}), len(selected))

    def test_lab_rejects_reporting_only_or_one_source(self):
        with self.assertRaises(news_collector.LabSourceError):
            news_collector.select_news_for_lab(
                [
                    self.item("ITmedia AI+", "one"),
                    self.item("AI Watch", "two"),
                ],
                [],
            )

    def test_lab_rejects_unknown_source_that_self_declares_official(self):
        unknown = {
            "source": "Unknown Source",
            "title": "untrusted",
            "content": "RAGの本文",
            "link": "https://unknown.example/RAG",
            "lane": "world",
            "evidence_role": "official",
            "matched_words": ["RAG"],
        }
        with self.assertRaises(news_collector.LabSourceError):
            news_collector.select_news_for_lab(
                [unknown, self.item("ITmedia AI+", "report")],
                [],
            )

    def test_lab_rejects_query_variants_of_the_same_canonical_url(self):
        official = self.item("Google AI Blog", "official")
        reporting = self.item("ITmedia AI+", "report")
        official["link"] = "https://example.test/article?utm_source=google"
        reporting["link"] = "https://example.test/article?utm_source=itmedia"
        with self.assertRaises(news_collector.LabSourceError):
            news_collector.validate_lab_sources([official, reporting])


class LabPipelineIntegrationTests(unittest.TestCase):
    def reporting_news(self):
        return {
            "source": "ITmedia AI+",
            "title": "RAG update",
            "content": "RAGの本文",
            "link": "https://example.test/rag",
            "lane": "japan",
            "evidence_role": "reporting",
            "matched_words": ["RAG"],
        }

    def test_scheduled_lab_without_official_corroboration_falls_back_to_daily_spec(self):
        term = {
            "id": "term",
            "name": "RAG",
            "content": "private",
            "review_count": 0,
            "last_reviewed": None,
        }
        news = self.reporting_news()
        generated_script = "あ" * 1000
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(pipeline_main, "__file__", str(Path(tmp) / "main.py")),
                patch.object(pipeline_main, "load_recent_manifests", return_value=[]),
                patch.object(pipeline_main, "select_terms_for_review", return_value=[term]),
                patch.object(pipeline_main, "collect_latest_news", return_value=[news]),
                patch.object(
                    pipeline_main, "match_news_with_words", return_value=([news], [])
                ),
                patch.object(
                    pipeline_main, "generate_radio_script", return_value=generated_script
                ) as generate,
                patch.object(
                    pipeline_main, "synthesize_podcast", new=AsyncMock(return_value=True)
                ),
                patch.object(
                    pipeline_main,
                    "require_audio_quality",
                    return_value={
                        "passed": True,
                        "duration_seconds": 300.0,
                        "mean_volume_db": -18.0,
                        "max_volume_db": -1.0,
                    },
                ) as audio_gate,
                patch.object(
                    pipeline_main, "run_shadow_audio_qa", return_value={"status": "disabled"}
                ),
                patch.object(pipeline_main, "update_term_review_status"),
                patch.dict(
                    os.environ,
                    {"PODCAST_EPISODE_FORMAT": "lab", "GITHUB_ACTIONS": "false"},
                    clear=False,
                ),
            ):
                asyncio.run(pipeline_main.async_main())

        call = generate.call_args
        self.assertEqual(call.kwargs["episode_format"], "daily")
        self.assertEqual(call.kwargs["spec"].display_name, "Daily Brief")
        runtime_thresholds = audio_gate.call_args.args[1]
        self.assertEqual(runtime_thresholds.min_duration_seconds, 240.0)
        self.assertEqual(runtime_thresholds.max_duration_seconds, 360.0)

    def test_short_audio_regenerates_once_with_same_sources_before_publication(self):
        term = {
            "id": "term",
            "name": "RAG",
            "content": "private",
            "review_count": 0,
            "last_reviewed": None,
        }
        news = self.reporting_news()
        first_script = "あ" * 1000
        retry_script = "い" * 1300
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(pipeline_main, "__file__", str(root / "main.py")),
                patch.object(pipeline_main, "load_recent_manifests", return_value=[]),
                patch.object(pipeline_main, "select_terms_for_review", return_value=[term]),
                patch.object(pipeline_main, "collect_latest_news", return_value=[news]),
                patch.object(
                    pipeline_main, "match_news_with_words", return_value=([news], [])
                ),
                patch.object(
                    pipeline_main,
                    "generate_radio_script",
                    side_effect=[first_script, retry_script],
                ) as generate,
                patch.object(
                    pipeline_main,
                    "synthesize_podcast",
                    new=AsyncMock(return_value=True),
                ) as synthesize,
                patch.object(
                    pipeline_main,
                    "require_audio_quality",
                    side_effect=[
                        pipeline_main.AudioQualityError(
                            "Generated audio failed deterministic checks: duration_too_short"
                        ),
                        {
                            "passed": True,
                            "issues": [],
                            "duration_seconds": 270.0,
                            "mean_volume_db": -18.0,
                            "max_volume_db": -1.0,
                        },
                    ],
                ) as audio_gate,
                patch.object(
                    pipeline_main, "run_shadow_audio_qa", return_value={"status": "disabled"}
                ),
                patch.object(pipeline_main, "update_term_review_status"),
                patch.dict(
                    os.environ,
                    {"PODCAST_EPISODE_FORMAT": "daily", "GITHUB_ACTIONS": "false"},
                    clear=False,
                ),
            ):
                asyncio.run(pipeline_main.async_main())

            saved_script = (root / "todays_script.txt").read_text(encoding="utf-8")

        self.assertEqual(generate.call_count, 2)
        self.assertTrue(generate.call_args.kwargs["duration_retry"])
        self.assertEqual(synthesize.await_count, 2)
        self.assertEqual(audio_gate.call_count, 2)
        self.assertEqual(saved_script, retry_script)

    def test_duration_retry_prompt_expands_without_repeating_sources(self):
        spec = episode_formats.load_episode_formats().formats["daily"]
        prompt = script_generator.build_prompt_content(
            [],
            [],
            [self.reporting_news()],
            episode_format="daily",
            spec=spec,
            duration_retry=True,
        )
        self.assertIn("最低尺に届きませんでした", prompt)
        self.assertIn(
            f"{spec.prompt_character_max}〜{spec.hard_character_max}文字", prompt
        )
        self.assertIn("同じ説明の反復はせず", prompt)

    def test_same_day_existing_lab_stops_instead_of_falling_back(self):
        today = datetime.now(episode_formats.JST).strftime("%Y-%m-%d")
        existing = {
            "broadcast_date": today,
            "publish_status": "published",
            "episode_format": "lab",
            "selected_term_keys": [],
        }
        news = self.reporting_news()
        with (
            patch.object(pipeline_main, "load_recent_manifests", return_value=[existing]),
            patch.object(pipeline_main, "select_terms_for_review", return_value=[]),
            patch.object(pipeline_main, "collect_latest_news", return_value=[news]),
            patch.object(
                pipeline_main, "match_news_with_words", return_value=([news], [])
            ),
            patch.dict(os.environ, {"PODCAST_EPISODE_FORMAT": "lab"}, clear=False),
        ):
            with self.assertRaises(news_collector.LabSourceError):
                asyncio.run(pipeline_main.async_main())

    def test_phase10_trial_writes_private_artifacts_without_public_or_notion_updates(self):
        private = "private-qa-sentinel"
        term = {
            "id": "term",
            "name": "RAG",
            "content": "private learning memo",
            "review_count": 0,
            "last_reviewed": None,
        }
        official = {
            "source": "Google AI Blog",
            "title": "Official RAG update",
            "content": "RAG official details",
            "link": "https://example.test/official?utm_source=rss",
            "lane": "world",
            "evidence_role": "official",
            "matched_words": ["RAG"],
        }
        reporting = {
            "source": "ITmedia AI+",
            "title": "RAG implementation report",
            "content": "RAG reporting details",
            "link": "https://example.test/report",
            "lane": "japan",
            "evidence_role": "reporting",
            "matched_words": ["RAG"],
        }
        generated_script = "あ" * 2200
        repetitive_script = "\n".join(
            [
                "アミ：そうですね。" + "あ" * 700,
                "ケンジ：その通りです。" + "い" * 700,
                "アミ：そうですね。" + "う" * 700,
            ]
        )

        async def synthesize(_script_path, audio_path, speech_rate):
            self.assertEqual(speech_rate, "+10%")
            Path(audio_path).write_bytes(b"trial-audio")
            return True

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(pipeline_main, "__file__", str(root / "main.py")),
                patch.object(pipeline_main, "load_recent_manifests", return_value=[]),
                patch.object(pipeline_main, "select_terms_for_review", return_value=[term]),
                patch.object(
                    pipeline_main, "collect_latest_news", return_value=[official, reporting]
                ),
                patch.object(
                    pipeline_main,
                    "match_news_with_words",
                    return_value=([official, reporting], []),
                ),
                patch.object(
                    pipeline_main,
                    "generate_radio_script",
                    side_effect=["あ" * 3500, repetitive_script, generated_script],
                ) as generate,
                patch.object(
                    pipeline_main, "synthesize_podcast", new=AsyncMock(side_effect=synthesize)
                ),
                patch.object(
                    pipeline_main,
                    "require_audio_quality",
                    return_value={
                        "passed": True,
                        "issues": [],
                        "duration_seconds": 600.0,
                        "mean_volume_db": -18.0,
                        "max_volume_db": -1.0,
                        "long_silence_seconds": 0.0,
                        "long_silence_ratio": 0.0,
                        "file_size_bytes": 11,
                    },
                ) as audio_gate,
                patch.object(
                    pipeline_main,
                    "run_shadow_audio_qa",
                    return_value={
                        "status": "completed",
                        "summary": private,
                        "overall_score": 4,
                        "requires_human_review": False,
                        "issues": [],
                    },
                ),
                patch.object(pipeline_main, "archive_today_podcast") as archive,
                patch.object(pipeline_main, "generate_podcast_rss") as rss,
                patch.object(pipeline_main, "write_manifest_atomic") as public_manifest,
                patch.object(pipeline_main, "write_improvement_proposal") as proposal,
                patch.object(pipeline_main, "update_term_review_status") as update_notion,
                patch.dict(
                    os.environ,
                    {"PHASE10_TRIAL_MODE": "true", "GITHUB_ACTIONS": "true"},
                    clear=False,
                ),
            ):
                asyncio.run(pipeline_main.async_main())

            trial_dirs = list((root / "phase10_trials").glob("trial_*"))
            self.assertEqual(len(trial_dirs), 1)
            trial_dir = trial_dirs[0]
            report_text = (trial_dir / "trial_report.json").read_text(encoding="utf-8")
            report = json.loads(report_text)
            self.assertTrue((trial_dir / "script.txt").is_file())
            self.assertTrue((trial_dir / "podcast.mp3").is_file())
            self.assertEqual(report["episode_format"], "lab")
            self.assertEqual(report["trial_status"], "ready_for_listening")
            self.assertNotIn(private, report_text)
            self.assertNotIn("private learning memo", report_text)
            self.assertFalse((root / "podcast.xml").exists())
            self.assertFalse((root / "episodes").exists())

        self.assertEqual(generate.call_count, 3)
        self.assertEqual(generate.call_args.kwargs["episode_format"], "lab")
        self.assertTrue(generate.call_args_list[1].kwargs["length_retry"])
        self.assertTrue(generate.call_args.kwargs["style_retry"])
        thresholds = audio_gate.call_args.args[1]
        self.assertEqual(thresholds.min_duration_seconds, 450.0)
        self.assertEqual(thresholds.max_duration_seconds, 720.0)
        archive.assert_not_called()
        rss.assert_not_called()
        public_manifest.assert_not_called()
        proposal.assert_not_called()
        update_notion.assert_not_called()


class PublicEpisodeMetadataTests(unittest.TestCase):
    def test_manifest_exposes_only_closed_format_profile_version_and_public_qa(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.mp3"
            audio.write_bytes(b"audio")
            private = "private-sentinel"
            manifest = episode_history.build_manifest(
                episode_id="podcast_20260720_040000",
                broadcast_date="2026-07-20",
                selected_terms=[{"id": "private-id", "name": private, "content": private}],
                primary_topic="Public news title",
                news_urls=[
                    "https://example.test/news#fragment",
                    "https://example.test/article?access_token=synthetic",
                    "https://example.test/article?X-Amz-Signature=synthetic",
                    "file:///private.txt",
                    "https://127.0.0.1/private",
                    "https://example.test/private?token=synthetic",
                    "https://user:pass@example.test/private",
                ],
                script="ケンジ：公開ニュースです。",
                audio_path=str(audio),
                duration_seconds=600,
                deterministic_checks={
                    "scheduled_format": "lab",
                    "private_note": private,
                    "news_selection": {"anchor_term": private, "anchor_present": True},
                },
                publish_status="published",
                gemini_qa_summary={
                    "status": "completed",
                    "overall_score": 4,
                    "summary": private,
                    "issues": [{
                        "category": "pacing",
                        "severity": "warning",
                        "timestamp": "01:20",
                        "evidence": private,
                        "suggested_change": private,
                    }],
                },
                episode_format="lab",
                editorial_profile_version="editorial-v1",
                public_topic="Public news title",
            )
        serialized = json.dumps(manifest, ensure_ascii=False)
        self.assertEqual(manifest["episode_format"], "lab")
        self.assertEqual(manifest["editorial_profile_version"], "editorial-v1")
        self.assertEqual(manifest["public_topic"], "Public news title")
        self.assertEqual(
            manifest["news_urls"],
            [
                "https://example.test/article",
                "https://example.test/news",
                "https://example.test/private",
            ],
        )
        self.assertEqual(
            manifest["deterministic_checks"],
            {"scheduled_format": "lab", "news_selection": {"anchor_present": True}},
        )
        self.assertNotIn(private, serialized)
        self.assertNotIn("approval_status", serialized)
        self.assertNotIn("available_tools", serialized)

    def test_public_qa_rejects_free_text_in_closed_scalar_fields(self):
        private = "private-qa-sentinel"
        sanitized = episode_history.public_qa_summary({
            "status": private,
            "overall_score": private,
            "has_internal_repetition": private,
            "requires_human_review": private,
            "issues": [],
        })
        self.assertNotIn(private, json.dumps(sanitized, ensure_ascii=False))

    def test_rss_uses_fixed_format_and_public_topic_but_not_profile_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            episodes = root / "episodes"
            manifests = root / "episode_manifests"
            episodes.mkdir()
            manifests.mkdir()
            filename = "podcast_20260720_040000.mp3"
            (episodes / filename).write_bytes(b"not-real-audio")
            (manifests / "podcast_20260720_040000.json").write_text(
                json.dumps({
                    "episode_format": "lab",
                    "editorial_profile_version": "editorial-v1",
                    "public_topic": "RAG & evaluation <test>",
                }),
                encoding="utf-8",
            )

            class FakeInfo:
                length = 600

            class FakeMP3:
                info = FakeInfo()

            with (
                patch.object(podcast_generator, "__file__", str(root / "podcast_generator.py")),
                patch.object(podcast_generator, "MP3", return_value=FakeMP3()),
                patch.dict(os.environ, {"BASE_URL": "https://example.test"}, clear=False),
            ):
                podcast_generator.generate_podcast_rss()

            xml_text = (root / "podcast.xml").read_text(encoding="utf-8")
            xml = ET.fromstring(xml_text)
            item = xml.find("./channel/item")
            self.assertEqual(item.findtext("title"), "AI実装ラボ｜RAG & evaluation <test>")
            self.assertIn("AI実装ラボ（8〜12分）", item.findtext("description"))
            self.assertNotIn("editorial-v1", xml_text)

    def test_non_object_manifest_falls_back_to_legacy_rss_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifests = root / "episode_manifests"
            manifests.mkdir()
            (manifests / "podcast_20260720_040000.json").write_text(
                "[]", encoding="utf-8"
            )
            self.assertIsNone(
                podcast_generator._manifest_episode_metadata(
                    str(root), "podcast_20260720_040000.mp3"
                )
            )

    def test_non_object_history_manifest_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.json"
            path.write_text("[]", encoding="utf-8")
            self.assertEqual(episode_history.load_recent_manifests(tmp), [])


class PublicWorkflowLogTests(unittest.TestCase):
    def test_inbox_processing_logs_no_private_titles_ids_or_dates(self):
        private_title = "private-inbox-title"
        private_term = "private-extracted-term"
        private_page_id = "private-page-id"

        class FakeModels:
            @staticmethod
            def generate_content(**_kwargs):
                class Response:
                    text = json.dumps({
                        "title": private_term,
                        "summary": "- private summary",
                        "study_date": "2026-07-14",
                    })
                return Response()

        class FakeClient:
            models = FakeModels()

        inbox_item = {
            "id": private_page_id,
            "properties": {
                "名前": {"title": [{"plain_text": private_title}]}
            },
        }
        stdout = io.StringIO()
        with (
            patch.object(process_inbox, "is_notion_configured", return_value=True),
            patch.object(process_inbox, "NOTION_INBOX_DATABASE_ID", "configured"),
            patch.object(process_inbox, "get_gemini_client", return_value=FakeClient()),
            patch.object(process_inbox, "fetch_inbox_items", return_value=[inbox_item]),
            patch.object(process_inbox, "fetch_page_content", return_value="private body"),
            patch.object(process_inbox, "request_json", return_value={}),
            patch.object(process_inbox, "archive_inbox_item", return_value=True),
            patch("sys.stdout", stdout),
        ):
            process_inbox.process_inbox()

        output = stdout.getvalue()
        for private_value in (
            private_title, private_term, private_page_id, "2026-07-14", "private body"
        ):
            self.assertNotIn(private_value, output)


if __name__ == "__main__":
    unittest.main()
