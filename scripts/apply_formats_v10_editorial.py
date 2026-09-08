"""One-shot migration for formats-v10 editorial/news-selection behavior.

This script is intentionally deterministic: every text replacement is asserted so
an upstream change cannot be silently overwritten. It is run once on the v10
feature branch and removed after the resulting code passes CI.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one occurrence, found {count}: {old[:80]!r}")
    file_path.write_text(text.replace(old, new), encoding="utf-8")


def regex_replace_once(path: str, pattern: str, replacement: str) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{path}: regex replacement count={count}: {pattern[:100]!r}")
    file_path.write_text(updated, encoding="utf-8")


# 1) Config: sharp generation target, wide anomaly-only character envelope.
config_path = ROOT / "config" / "episode_formats.json"
config = json.loads(config_path.read_text(encoding="utf-8"))
daily = config["formats"]["daily"]
daily.update(
    prompt_character_min=1550,
    prompt_character_max=1750,
    hard_character_min=900,
    hard_character_max=4200,
    max_news_items=3,
)
weekly = config["formats"]["lab"]
weekly.update(
    prompt_character_min=3000,
    prompt_character_max=3500,
    hard_character_min=900,
    hard_character_max=8200,
    max_news_items=4,
)
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

replace_once(
    "episode_formats.py",
    ") != (1400, 1650, 900, 2000):\n            raise ValueError(\"daily script target must remain 1400-1650 characters\")",
    ") != (1550, 1750, 900, 4200):\n            raise ValueError(\"daily script target must center on 1550-1750 characters\")",
)
replace_once(
    "episode_formats.py",
    ") != (1200, 2600, 900, 2800):\n            raise ValueError(\"lab script target must remain 1200-2600 characters\")",
    ") != (3000, 3500, 900, 8200):\n            raise ValueError(\"weekly script target must center on 3000-3500 characters\")",
)

# 2) Global editorial instruction: quality/depth per item, not one-story dogma.
replace_once(
    "script_generator.py",
    "- 複数の大きなニュースを並べるだけの「ニュースダイジェスト（Yahoo!トップページのような形式）」は絶対に避けてください。\n- 1つの主要ニュース（または復習用語）を深く掘り下げ、その技術的背景、なぜ注目されているのか、直面している課題などをアミとケンジの自然な掛け合いで解説してください。",
    "- ニュース件数を増やすこと自体を目的にした、見出しだけを薄く並べるダイジェストは避けてください。\n- 採用する各ニュースは、何が起きたか、なぜ重要か、利用・開発への意味または制約まで説明してください。1件で十分なら1件、独立した重要ニュースが複数あるなら複数件を扱って構いません。",
)
replace_once(
    "script_generator.py",
    "5. 尺と文字量は、後述の番組形式ごとの範囲に収めてください。",
    "5. 尺と文字量は後述の生成中心を狙ってください。ただし重要情報を削ったり、水増ししたりして中心値へ機械的に合わせないでください。",
)

new_build_format = '''def build_format_instruction(episode_format: str, spec: FormatSpec) -> str:
    target_minutes = spec.audio_thresholds.target_duration_seconds / 60
    if episode_format == "daily":
        return f"""
【番組形式: Daily Brief】
- 生成中心は読み上げ約{target_minutes:g}分。台本文字数は{spec.prompt_character_min}〜{spec.prompt_character_max}文字を狙う。これは中心値であり、文字数を満たすための言い換え・反復・水増しは禁止する。
- 冒頭は2発話以内で、その日に最も価値の高い論点へ入る。
- ニュース件数は固定しない。1件で十分なら1件だけ扱い、独立した重要ニュースが複数ある場合は、それぞれを十分説明できる限り複数件を扱ってよい。
- 各ニュースは「何が起きたか」「なぜ重要か」「利用者・開発への意味または制約」のうち、入力ソースで確認できる要素を十分に説明する。件数を増やすための薄い紹介は禁止する。
- 重要な情報を削って約{target_minutes:g}分へ押し込まない。情報量が多く聞く価値が続く場合は自然に長くしてよい。
- Tipsは必須ではない。具体的操作、期待結果、使わない条件を入力ソースから確認できない場合は、注意点または今後の観察ポイントへ置き換える。
""".strip()
    if episode_format == "lab":
        return f"""
【番組形式: Weekly AI Review】
- 生成中心は読み上げ約{target_minutes:g}分。台本文字数は{spec.prompt_character_min}〜{spec.prompt_character_max}文字を狙うが、尺合わせの反復・水増しは禁止する。
- 日曜はNotion復習から独立し、今週のAI界隈で「知らずに週を終えるのは惜しい」内容を編集して伝える。
- バイブコーディングや実装テーマに限定しない。モデル、エージェント、研究、サービス、デバイス、インフラ、重要な業界変化などを対象にできる。
- 1テーマ固定にしない。1件で十分なら1件、独立した重要ニュースが複数あるなら複数件を扱い、それぞれの背景と意味が薄くならないようにする。
- officialソースは強い根拠として優先するが必須ではない。信頼済みのreportingやresearchも、入力本文に根拠がある範囲で主題にできる。
- 通常の資金調達ニュースは低優先とする一方、大型買収、重要な提携、AIインフラ投資など業界構造へ影響しうる話題は一律除外しない。
- 情報量が少なければ無理に{target_minutes:g}分まで延ばさず、情報量が豊富なら重要事項を削らず自然に延長する。
- 同じ説明、同一論点、同じ結論の反復は絶対に禁止。情報量が尽きたら自然に会話を締めくくる。
- 仕様、対応条件、具体的操作は入力ソースに根拠がある範囲だけにし、不足部分を推測で補わない。
""".strip()
    raise EpisodeFormatError("episode format must be daily or lab")'''
regex_replace_once(
    "script_generator.py",
    r"def build_format_instruction\(episode_format: str, spec: FormatSpec\) -> str:\n.*?    raise EpisodeFormatError\(\"episode format must be daily or lab\"\)",
    new_build_format,
)

replace_once(
    "script_generator.py",
    "復習メモの代わりに、提供された最新ニュースのうち一つを主要テーマとして詳しく掘り下げてください。",
    "復習メモの代わりに、提供された最新ニュースから聞く価値の高いものを選び、採用した各ニュースを十分に説明してください。1件で十分なら1件だけで構いません。",
)
replace_once(
    "script_generator.py",
    "ニュース1を主題として番組の大半を使い、ニュース2は主題を補強できる場合だけ任意で使ってください。Tipsは必須ではありません。これは5分のラジオ番組1本です。",
    "ニュース件数は固定しません。独立した重要ニュースが複数ある場合は、各ニュースを薄くせず十分に説明できる範囲で複数扱ってください。件数を埋めるための追加は禁止です。Tipsは必須ではありません。",
)
replace_once(
    "script_generator.py",
    "1テーマだけを扱い、今週なぜ重要なのか、仕組み、バイブコーダーの個人開発でどう関係するか、使わない条件や注意点まで自然な会話で深掘りしてください。手順や期待結果は公式根拠があり、実際に役立つ場合だけ含めてください。",
    "今週知る価値を基準に1件以上を選び、各ニュースについて、なぜ今重要か、背景、意味、制約を自然な会話で十分に説明してください。実装テーマに限定せず、1テーマ固定にもせず、重要事項を削って尺へ合わせないでください。手順や期待結果は入力ソースに根拠があり、実際に役立つ場合だけ含めてください。",
)
replace_once(
    "script_generator.py",
    "f\"目標尺は{spec.duration_label}です。\"",
    "f\"目標尺は{spec.duration_label}です。ただし生成中心は約{spec.audio_thresholds.target_duration_seconds / 60:g}分です。\"",
)

# 3) Daily candidate pool: pass a small diverse pool; the writer chooses depth-first.
replace_once("news_collector.py", "MAX_NEWS_PER_BROADCAST = 2", "MAX_NEWS_PER_BROADCAST = 3")
replace_once(
    "news_collector.py",
    "\"\"\"Select at most two source-diverse items for one five-minute broadcast.\n\n    A matching item keeps priority.  The second slot prefers a fresh Japanese\n    reporting source, otherwise a source different from the first item.  This is\n    a deterministic fallback policy, not a daily quota: stale Japanese items are\n    never forced into the programme.\n    \"\"\"",
    "\"\"\"Select a small source-diverse candidate pool for one Daily episode.\n\n    A Notion match keeps priority, but later slots may be independent stories.\n    The generator decides how many candidates deserve airtime; deterministic\n    selection only prevents one feed from monopolizing the candidate pool.\n    \"\"\"",
)
replace_once(
    "news_collector.py",
    "remaining = [\n            item\n            for item in ordered_candidates\n            if item not in selected and related_to_primary(item)\n        ]",
    "remaining = [item for item in ordered_candidates if item not in selected]",
)

# 4) Weekly source validation no longer requires first-party evidence.
regex_replace_once(
    "news_collector.py",
    r"def validate_lab_sources\(news_items\):\n.*?    return True\n\n\ndef _weekly_lab_relevance_score",
    '''def validate_lab_sources(news_items):
    """Require only trusted, unique, public sources with usable source text."""

    if not news_items:
        raise LabSourceError("weekly review requires at least one trusted source")
    urls = set()
    for item in news_items:
        source_config = SOURCE_CONFIG.get(item.get("source"))
        if not source_config:
            raise LabSourceError("weekly review source is not trusted")
        canonical_urls = safe_public_news_urls([item.get("link")])
        if len(canonical_urls) != 1:
            raise LabSourceError("weekly review requires a public HTTPS source URL")
        canonical = canonical_urls[0]
        if canonical in urls:
            raise LabSourceError("weekly review source URLs must be distinct")
        urls.add(canonical)
        if not str(item.get("title", "")).strip() or not str(item.get("content", "")).strip():
            raise LabSourceError("weekly review source must include a title and content")
    return True


def _weekly_lab_relevance_score''',
)

new_select_lab = '''def select_news_for_lab(news_items, recent_manifests, *, now=None, max_items=4):
    """Build a recent, trusted, source-diverse candidate pool for Weekly AI Review.

    Notion matching, a practical coding keyword, and an official first-party source
    are all optional.  This selector provides several strong source candidates;
    the script writer may use one or several depending on editorial value.
    """

    if not 1 <= max_items <= 4:
        raise ValueError("weekly max_items must be between 1 and 4")
    now = now or datetime.now(timezone.utc)
    recent_source_counts = _recent_source_counts(recent_manifests)
    candidates = []
    seen_urls = set()
    for index, item in enumerate(news_items):
        source_config = SOURCE_CONFIG.get(item.get("source"))
        canonical_urls = safe_public_news_urls([item.get("link")])
        if not source_config or len(canonical_urls) != 1:
            continue
        if not str(item.get("title", "")).strip() or not str(item.get("content", "")).strip():
            continue
        canonical = canonical_urls[0]
        if canonical in seen_urls:
            continue
        seen_urls.add(canonical)
        published_at = _published_at_or_none(item)
        if published_at and published_at < now - timedelta(days=WEEKLY_LAB_NEWS_MAX_AGE_DAYS):
            continue
        candidate = item.copy()
        candidate["lane"] = candidate.get("lane", source_config.get("lane", "world"))
        candidate["evidence_role"] = source_config.get("evidence_role", "reporting")
        candidate["_matched_for_review"] = bool(candidate.get("matched_words"))
        candidate["_candidate_index"] = index
        candidate["_weekly_lab_score"] = _weekly_lab_relevance_score(item)
        candidate["_weekly_lab_published_at"] = published_at
        candidates.append(candidate)

    if not candidates:
        raise LabSourceError("Weekly AI Review has no recent trusted source with usable text")

    role_priority = {"official": 0, "research": 1, "reporting": 2}

    def sort_key(candidate):
        published_at = candidate.get("_weekly_lab_published_at")
        freshness = -published_at.timestamp() if published_at else float("inf")
        return (
            freshness,
            role_priority.get(candidate.get("evidence_role"), 3),
            -candidate["_weekly_lab_score"],
            recent_source_counts[candidate.get("source", "")],
            candidate["_candidate_index"],
        )

    ordered = sorted(candidates, key=sort_key)
    selected = []
    selected_sources = set()
    while ordered and len(selected) < max_items:
        diverse = [item for item in ordered if item.get("source") not in selected_sources]
        candidate = diverse[0] if diverse else ordered[0]
        ordered.remove(candidate)
        candidate["_selection_reason"] = (
            "weekly_primary_candidate" if not selected else "weekly_diverse_candidate"
        )
        selected.append(candidate)
        selected_sources.add(candidate.get("source"))

    validate_lab_sources(selected)
    audit_selection = [
        {
            "source": item.get("source", ""),
            "lane": item.get("lane", "world"),
            "matched_notion_terms": item["_matched_for_review"],
            "reason": item["_selection_reason"],
        }
        for item in selected
    ]
    return selected, {
        "candidate_counts_by_source": dict(sorted(Counter(
            item.get("source", "") for item in candidates
        ).items())),
        "anchor_present": any(item["_matched_for_review"] for item in selected),
        "selected_sources": [item.get("source", "") for item in selected],
        "selected": audit_selection,
        "evidence_roles": [item.get("evidence_role", "reporting") for item in selected],
        "official_basis_present": any(
            item.get("evidence_role") == "official" for item in selected
        ),
    }'''
regex_replace_once(
    "news_collector.py",
    r"def select_news_for_lab\(news_items, recent_manifests, \*, now=None, max_items=3\):\n.*?\n    return selected, \{\n        \"candidate_counts_by_source\":.*?\n        \"official_basis_present\": True,\n    \}",
    new_select_lab,
)

# 5) Business noise remains strict on Daily, but Weekly can consider strategic deals.
replace_once(
    "news_collector.py",
    "def filter_business_noise(news_list):",
    "def filter_business_noise(news_list, *, episode_format=\"daily\"):",
)
replace_once(
    "news_collector.py",
    "    english_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in english_noise_words]\n    \n    # 日本語のノイズワード（部分一致で検出）\n    japanese_noise_words = [\n        \"資金調達\", \"買収\", \"合併\", \"融資\", \"評価額\", \"子会社\", \"株式取得\", \n        \"資本業務提携\", \"ベンチャーキャピタル\", \"投資ラウンド\", \"出資\"\n    ]",
    "    if episode_format == \"lab\":\n        # Routine financing remains noise, while acquisitions, mergers, partnerships\n        # and infrastructure investment may be strategically important weekly news.\n        english_noise_words = [\n            r'\\bseed\\s+round\\b', r'\\bseries\\s+[a-z]\\b', r'\\bfunding\\b',\n            r'\\bvaluation\\b', r'\\bvc\\b', r'\\bventure\\s+capital\\b',\n            r'\\bipo\\b', r'\\braise\\s+money\\b',\n            r'\\braised\\s+(?:\\$\\d+|\\d+\\s*million|\\d+\\s*billion)\\b',\n        ]\n        japanese_noise_words = [\n            \"資金調達\", \"融資\", \"評価額\", \"ベンチャーキャピタル\", \"投資ラウンド\"\n        ]\n    else:\n        japanese_noise_words = [\n            \"資金調達\", \"買収\", \"合併\", \"融資\", \"評価額\", \"子会社\", \"株式取得\",\n            \"資本業務提携\", \"ベンチャーキャピタル\", \"投資ラウンド\", \"出資\"\n        ]\n    english_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in english_noise_words]",
)
replace_once(
    "news_collector.py",
    "def collect_latest_news(max_entries_per_feed=5):\n    \"\"\"ホワイトリストの全フィードから最新ニュースを収集し、ビジネスノイズをフィルタリング\"\"\"",
    "def collect_latest_news(max_entries_per_feed=5, *, episode_format=\"daily\"):\n    \"\"\"Collect trusted feeds with format-specific business-noise filtering.\"\"\"\n    if episode_format not in {\"daily\", \"lab\"}:\n        raise ValueError(\"episode_format must be daily or lab\")",
)
replace_once(
    "news_collector.py",
    "filtered_news = filter_business_noise(all_news)",
    "filtered_news = filter_business_noise(all_news, episode_format=episode_format)",
)

# 6) Main pipeline passes the active format to collection and uses Weekly wording.
replace_once(
    "main.py",
    "all_news = collect_latest_news(max_entries_per_feed=10 if trial_anchor else 5)",
    "all_news = collect_latest_news(\n        max_entries_per_feed=10 if trial_anchor else 5,\n        episode_format=episode_format,\n    )",
)
replace_once(
    "main.py",
    "日曜のWeekly Labは復習を休み、今週のニュースから\"\n            \"バイブコーダー向けの重要テーマを選びます。",
    "日曜のWeekly AI Reviewは復習を休み、今週のAIニュースから\"\n            \"知っておく価値の高い内容を自由に編集します。",
)
replace_once(
    "main.py",
    "No news candidates remain for the five-minute broadcast",
    "No news candidates remain for the current broadcast",
)

# 7) Manifest projection permits the new closed selection reason enums.
replace_once(
    "episode_history.py",
    '"candidate_fallback", "official_basis", "corroborating_source",',
    '"candidate_fallback", "official_basis", "corroborating_source",\n    "weekly_primary_candidate", "weekly_diverse_candidate",',
)

# 8) Update legacy regression expectations that intentionally encoded v9 policy.
replace_once(
    "tests/test_episode_formats.py",
    "(1200, 2600, 900, 2800),",
    "(3000, 3500, 900, 8200),",
)
replace_once(
    "tests/test_episode_formats.py",
    "(1400, 1650, 900, 2000),",
    "(1550, 1750, 900, 4200),",
)
replace_once(
    "tests/test_episode_formats.py",
    'self.assertIn("ニュース2は主題を補強できる場合だけ任意", prompt)',
    'self.assertIn("ニュース件数は固定しません", prompt)',
)
replace_once(
    "tests/test_episode_formats.py",
    'self.assertIn("1テーマだけ", instruction)',
    'self.assertIn("1テーマ固定にしない", instruction)',
)
replace_once(
    "tests/test_episode_formats.py",
    'oversize_script = "あ" * 2020',
    'oversize_script = "あ" * 4300',
)
replace_once(
    "tests/test_episode_formats.py",
    'oversize_retry_script = "い" * 2135',
    'oversize_retry_script = "い" * 4300',
)
replace_once(
    "tests/test_episode_formats.py",
    'side_effect=["あ" * 3650, repetitive_script],',
    'side_effect=["あ" * 8300, repetitive_script],',
)

# Replace two v9 Weekly policy tests with v10 expectations.
regex_replace_once(
    "tests/test_episode_formats.py",
    r"    def test_lab_rejects_reporting_only_candidates\(self\):\n.*?\n\n    def test_lab_does_not_treat_generic_ai_tools_marketing_as_builder_topic",
    '''    def test_weekly_accepts_reporting_only_candidates(self):
        selected, audit = news_collector.select_news_for_lab(
            [
                self.item("ITmedia AI+", "one", matched=""),
                self.item("AI Watch", "two", matched=""),
            ],
            [],
        )
        self.assertEqual(len(selected), 2)
        self.assertFalse(audit["official_basis_present"])

    def test_lab_does_not_treat_generic_ai_tools_marketing_as_builder_topic''',
)
regex_replace_once(
    "tests/test_episode_formats.py",
    r"    def test_lab_does_not_treat_generic_ai_tools_marketing_as_builder_topic\(self\):\n.*?\n\n    def test_lab_rejects_unknown_source_that_self_declares_official",
    '''    def test_weekly_can_consider_non_builder_ai_topic(self):
        marketing = self.item(
            "Google AI Blog", "Evolve your marketing with new AI tools", matched=""
        )
        marketing["content"] = "New AI tools help marketers improve campaigns."
        selected, _ = news_collector.select_news_for_lab([marketing], [])
        self.assertEqual(selected[0]["title"], marketing["title"])

    def test_lab_rejects_unknown_source_that_self_declares_official''',
)
regex_replace_once(
    "tests/test_episode_formats.py",
    r"    def test_scheduled_lab_without_official_corroboration_falls_back_to_daily_spec\(self\):\n.*?\n\n    def test_daily_script_stops_when_length_retry_fails",
    '''    def test_scheduled_weekly_reporting_only_stays_weekly(self):
        news = self.reporting_news()
        generated_script = "あ" * 3200
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(pipeline_main, "__file__", str(Path(tmp) / "main.py")),
                patch.object(pipeline_main, "load_recent_manifests", return_value=[]),
                patch.object(pipeline_main, "select_terms_for_review", return_value=[]),
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
                        "duration_seconds": 480.0,
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
        self.assertEqual(call.kwargs["episode_format"], "lab")
        self.assertEqual(call.kwargs["spec"].display_name, "AI実装ラボ")
        runtime_thresholds = audio_gate.call_args.args[1]
        self.assertEqual(runtime_thresholds.min_duration_seconds, 210.0)
        self.assertEqual(runtime_thresholds.target_duration_seconds, 480.0)

    def test_daily_script_stops_when_length_retry_fails''',
)

print("formats-v10 editorial migration applied")
