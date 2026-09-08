"""One-shot fixes after the formats-v10 editorial migration.

Keeps old safety invariants that are still desirable while updating tests that
intentionally encoded the superseded v9 editorial policy.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one occurrence, found {count}: {old[:100]!r}")
    file_path.write_text(text.replace(old, new), encoding="utf-8")


# Preserve user-facing duration labels while keeping the new sharp generation center.
replace_once(
    "script_generator.py",
    "- 生成中心は読み上げ約{target_minutes:g}分。台本文字数は{spec.prompt_character_min}〜{spec.prompt_character_max}文字を狙う。これは中心値であり、文字数を満たすための言い換え・反復・水増しは禁止する。",
    "- 表示上の目安は{spec.duration_label}。生成中心は読み上げ約{target_minutes:g}分。台本文字数は{spec.prompt_character_min}〜{spec.prompt_character_max}文字を狙う。これは中心値であり、文字数を満たすための言い換え・反復・水増しは禁止する。",
)
replace_once(
    "script_generator.py",
    "- 生成中心は読み上げ約{target_minutes:g}分。台本文字数は{spec.prompt_character_min}〜{spec.prompt_character_max}文字を狙うが、尺合わせの反復・水増しは禁止する。",
    "- 表示上の目安は{spec.duration_label}。生成中心は読み上げ約{target_minutes:g}分。台本文字数は{spec.prompt_character_min}〜{spec.prompt_character_max}文字を狙うが、尺合わせの反復・水増しは禁止する。",
)
replace_once(
    "script_generator.py",
    "各ニュースについて、なぜ今重要か、背景、意味、制約を自然な会話で十分に説明してください。",
    "各ニュースについて、今週なぜ重要か、背景、意味、制約を自然な会話で十分に説明してください。",
)

# Daily candidate pool: stay source-diverse and do not force stale Japanese reporting.
replace_once(
    "news_collector.py",
    """        remaining = [item for item in ordered_candidates if item not in selected]
        if not remaining:
            break

        selected_sources = {item.get("source") for item in selected}
""",
    """        remaining = [item for item in ordered_candidates if item not in selected]
        remaining = [
            item
            for item in remaining
            if not (
                item.get("lane") == "japan"
                and _published_at_or_none(item) is not None
                and not _is_fresh_japan_candidate(item, now)
            )
        ]
        if not remaining:
            break

        selected_sources = {item.get("source") for item in selected}
""",
)
replace_once(
    "news_collector.py",
    """        elif different_source:
            candidate = min(different_source, key=sort_key)
            reason = "different_source"
        else:
            candidate = remaining[0]
            reason = "candidate_fallback"
        add(candidate, reason)
""",
    """        elif different_source:
            candidate = min(different_source, key=sort_key)
            reason = "different_source"
        else:
            # Candidate capacity is not a quota. Do not add another story merely
            # to fill the third slot when it brings no source diversity.
            break
        add(candidate, reason)
""",
)

# Weekly safety: any supplied untrusted/malformed source is a hard error, not a
# silent omission. This preserves the previous fail-closed trust boundary.
replace_once(
    "news_collector.py",
    """        source_config = SOURCE_CONFIG.get(item.get("source"))
        canonical_urls = safe_public_news_urls([item.get("link")])
        if not source_config or len(canonical_urls) != 1:
            continue
""",
    """        source_config = SOURCE_CONFIG.get(item.get("source"))
        if not source_config:
            raise LabSourceError("weekly review source is not trusted")
        canonical_urls = safe_public_news_urls([item.get("link")])
        if len(canonical_urls) != 1:
            raise LabSourceError("weekly review requires a public HTTPS source URL")
""",
)
replace_once(
    "news_collector.py",
    'class LabSourceError(RuntimeError):\n    """Raised when Weekly Lab lacks a safe, practical official basis."""',
    'class LabSourceError(RuntimeError):\n    """Raised when Weekly AI Review violates the trusted-source boundary."""',
)
replace_once(
    "news_collector.py",
    """# Weekly Lab is deliberately independent from the user's Notion review terms.
# Rank recent stories by whether they teach a reusable skill for an everyday
# vibe-coding workflow, then require the primary story to come from a trusted
# first-party feed.  These are selection hints, not facts injected into the
# generated script.
""",
    """# Weekly AI Review is deliberately independent from the user's Notion review
# terms. Practical implementation signals remain only as ranking hints; they are
# no longer eligibility requirements, and first-party evidence is preferred but
# not mandatory.
""",
)

# v10 expectation updates in the broad episode-format regression suite.
replace_once(
    "tests/test_episode_formats.py",
    'self.assertIn("1200〜2600文字", prompt)\n        self.assertIn("特に上限寄りの2600文字前後", prompt)\n        self.assertIn("2800文字を超えないでください", prompt)',
    'self.assertIn("3000〜3500文字", prompt)\n        self.assertIn("特に上限寄りの3500文字前後", prompt)\n        self.assertIn("8200文字を超えないでください", prompt)',
)
replace_once(
    "tests/test_episode_formats.py",
    'news = self.reporting_news()\n        with (\n            patch.object(pipeline_main, "load_recent_manifests", return_value=[existing]),',
    'news = self.reporting_news()\n        news["source"] = "Unknown Source"\n        with (\n            patch.object(pipeline_main, "load_recent_manifests", return_value=[existing]),',
)

# Phase-0 safety tests: retain safety semantics but update superseded v9 quotas.
replace_once(
    "tests/test_phase0_safety.py",
    "def test_prompt_keeps_one_programme_to_two_curated_news_items(self):",
    "def test_prompt_allows_three_curated_candidates_without_forcing_usage(self):",
)
replace_once(
    "tests/test_phase0_safety.py",
    'self.assertNotIn("Title: three", prompt)\n        self.assertIn("5分のラジオ番組1本", prompt)',
    'self.assertIn("Title: three", prompt)\n        self.assertIn("ニュース件数は固定しません", prompt)\n        self.assertIn("件数を埋めるための追加は禁止", prompt)',
)
replace_once(
    "tests/test_phase0_safety.py",
    """    def test_unrelated_second_item_is_omitted(self):
        primary = self.make_news("TechCrunch AI", "world", "model-release")
        unrelated = self.make_news("AI Watch", "japan", "robotics-event")
        selected, _audit = news_collector.select_news_for_broadcast(
            [], [primary, unrelated], [], now=datetime(2026, 7, 12, tzinfo=timezone.utc)
        )
        self.assertEqual([item["source"] for item in selected], ["TechCrunch AI"])
""",
    """    def test_independent_second_item_is_allowed_when_source_diverse(self):
        primary = self.make_news("TechCrunch AI", "world", "model-release")
        unrelated = self.make_news("AI Watch", "japan", "robotics-event")
        selected, _audit = news_collector.select_news_for_broadcast(
            [], [primary, unrelated], [], now=datetime(2026, 7, 12, tzinfo=timezone.utc)
        )
        self.assertEqual(
            [item["source"] for item in selected], ["TechCrunch AI", "AI Watch"]
        )
""",
)

print("formats-v10 regression fixes applied")
