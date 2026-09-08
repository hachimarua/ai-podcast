import unittest
from datetime import datetime, timezone

import news_collector
import script_generator
import episode_formats


NOW = datetime(2026, 9, 8, 2, 0, tzinfo=timezone.utc)


def item(source, title, *, content="source text", matched=None, day="2026-09-08"):
    config = news_collector.SOURCE_CONFIG[source]
    return {
        "source": source,
        "title": title,
        "content": content,
        "link": f"https://example.test/{source.replace(' ', '-').replace('/', '-')}/{title.replace(' ', '-')}",
        "published": f"{day} 01:00:00",
        "lane": config["lane"],
        "evidence_role": config["evidence_role"],
        "matched_words": list(matched or []),
    }


class DailyEditorialV10Tests(unittest.TestCase):
    def test_daily_candidate_pool_allows_three_independent_stories(self):
        matched = [item("Google AI Blog", "Gemini memory update", matched=["memory"])]
        unmatched = [
            item("ITmedia AI+", "国内AI端末の新動向"),
            item("arXiv cs.AI (Artificial Intelligence)", "New reasoning benchmark"),
        ]
        selected, audit = news_collector.select_news_for_broadcast(
            matched, unmatched, [], now=NOW
        )
        self.assertEqual(len(selected), 3)
        self.assertEqual(len(set(audit["selected_sources"])), 3)
        self.assertIn("New reasoning benchmark", [entry["title"] for entry in selected])

    def test_daily_prompt_uses_sharp_center_but_flexible_story_count(self):
        spec = episode_formats.load_episode_formats().formats["daily"]
        instruction = script_generator.build_format_instruction("daily", spec)
        prompt = script_generator.build_prompt_content(
            [],
            [],
            [
                item("Google AI Blog", "First independent story"),
                item("ITmedia AI+", "Second independent story"),
                item("TechCrunch AI", "Third independent story"),
            ],
            episode_format="daily",
            spec=spec,
        )
        self.assertIn("生成中心は読み上げ約4分", instruction)
        self.assertIn("1550〜1750文字", instruction)
        self.assertIn("ニュース件数は固定しない", instruction)
        self.assertIn("重要な情報を削って約4分へ押し込まない", instruction)
        self.assertIn("ニュース件数は固定しません", prompt)
        self.assertIn("[ニュース 3]", prompt)


class WeeklyEditorialV10Tests(unittest.TestCase):
    def test_weekly_accepts_reporting_only_sources(self):
        selected, audit = news_collector.select_news_for_lab(
            [
                item("ITmedia AI+", "国内AIサービスの変化"),
                item("AI Watch", "AIデバイスの週次動向"),
            ],
            [],
            now=NOW,
        )
        self.assertEqual(len(selected), 2)
        self.assertFalse(audit["official_basis_present"])
        self.assertEqual(set(audit["evidence_roles"]), {"reporting"})

    def test_weekly_accepts_research_only_and_non_builder_topics(self):
        research, research_audit = news_collector.select_news_for_lab(
            [
                item(
                    "arXiv cs.AI (Artificial Intelligence)",
                    "Study of social effects of generative AI",
                    content="A research paper about societal effects rather than implementation.",
                )
            ],
            [],
            now=NOW,
        )
        self.assertEqual(len(research), 1)
        self.assertEqual(research_audit["evidence_roles"], ["research"])

        general, _ = news_collector.select_news_for_lab(
            [
                item(
                    "TechCrunch AI",
                    "AI changes the media market",
                    content="A reporting story about market structure with no coding tutorial.",
                )
            ],
            [],
            now=NOW,
        )
        self.assertEqual(general[0]["title"], "AI changes the media market")

    def test_weekly_still_rejects_untrusted_sources(self):
        untrusted = {
            "source": "Unknown Source",
            "title": "Unknown claim",
            "content": "untrusted body",
            "link": "https://unknown.example/story",
        }
        with self.assertRaises(news_collector.LabSourceError):
            news_collector.validate_lab_sources([untrusted])

    def test_weekly_business_filter_keeps_strategic_deals_but_not_routine_funding(self):
        funding = item(
            "TechCrunch AI",
            "Startup announces Series A funding",
            content="The company raised a new funding round.",
        )
        acquisition = item(
            "TechCrunch AI",
            "Major AI acquisition reshapes the market",
            content="The acquisition changes the structure of the AI market.",
        )
        weekly = news_collector.filter_business_noise(
            [funding, acquisition], episode_format="lab"
        )
        self.assertEqual([entry["title"] for entry in weekly], [acquisition["title"]])

        daily = news_collector.filter_business_noise(
            [acquisition], episode_format="daily"
        )
        self.assertEqual(daily, [])

    def test_weekly_instruction_is_independent_and_not_one_theme_only(self):
        spec = episode_formats.load_episode_formats().formats["lab"]
        instruction = script_generator.build_format_instruction("lab", spec)
        self.assertIn("Weekly AI Review", instruction)
        self.assertIn("生成中心は読み上げ約8分", instruction)
        self.assertIn("Notion復習から独立", instruction)
        self.assertIn("実装テーマに限定しない", instruction)
        self.assertIn("1テーマ固定にしない", instruction)
        self.assertIn("officialソースは強い根拠として優先するが必須ではない", instruction)
        self.assertIn("reportingやresearch", instruction)


if __name__ == "__main__":
    unittest.main()
