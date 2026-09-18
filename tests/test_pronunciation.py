"""Guard the TTS pronunciation dictionary.

The dictionary is applied to each line just before Edge TTS speaks it, so an
English proper noun that is missing from it reaches the listener as-is.  The
substitutions run in insertion order, which makes ordering a real invariant:
if "Google" ran before "Google AI Blog", the feed name would be spoken as
"グーグル AI Blog".
"""

import re
import unittest

from audio_generator import apply_pronunciation_dict


def latin_left(text: str) -> list[str]:
    """Latin runs still present after substitution, ignoring the idiomatic "AI"."""
    found = [m.strip() for m in re.findall(r"[A-Za-z][A-Za-z0-9.\- ]{1,30}", text)]
    return [m for m in found if len(m) > 1 and m != "AI"]


class FeedSourceNameTests(unittest.TestCase):
    """Every feed name in news_collector.SOURCE_CONFIG is spoken aloud."""

    def test_all_configured_feed_names_are_converted(self):
        from news_collector import SOURCE_CONFIG

        unconverted = {}
        for name in SOURCE_CONFIG:
            # arXiv's feed name carries a parenthetical description that is not
            # a proper noun; only the source name itself has to be readable.
            head = name.split(" (")[0]
            left = latin_left(apply_pronunciation_dict(head))
            if left:
                unconverted[name] = left
        self.assertEqual(unconverted, {}, f"配信元名が未変換: {unconverted}")


class OrderingTests(unittest.TestCase):
    """Longer names must be substituted before the shorter names inside them."""

    def test_compound_names_are_not_broken_by_their_prefix(self):
        cases = {
            "Google AI Blog": "グーグルエーアイブログ",
            "Google Cloud": "グーグルクラウド",
            "Google Workspace": "グーグルワークスペース",
            "Hugging Face Blog": "ハギングフェイスブログ",
            "Cloudflare Workers": "クラウドフレアワーカーズ",
            "Cloudflare D1": "クラウドフレアディーワン",
            "GitHub Actions": "ギットハブアクションズ",
            "Vertex AI": "バーテックスエーアイ",
            "SQLite": "エスキューライト",
            "LLMs": "エルエルエムズ",
            "APIs": "エーピーアイズ",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(apply_pronunciation_dict(source), expected)

    def test_the_shorter_name_still_works_on_its_own(self):
        self.assertEqual(apply_pronunciation_dict("Google"), "グーグル")
        self.assertEqual(apply_pronunciation_dict("Cloudflare"), "クラウドフレア")
        self.assertEqual(apply_pronunciation_dict("GitHub"), "ギットハブ")
        self.assertEqual(apply_pronunciation_dict("SQL"), "エスキューエル")

    def test_aws_compound_names_precede_plain_amazon(self):
        cases = {
            "Amazon S3": "アマゾンエススリー",
            "Amazon Web Services": "アマゾンウェブサービシズ",
            "Amazon Bedrock": "アマゾンベッドロック",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(apply_pronunciation_dict(source), expected)
        self.assertEqual(apply_pronunciation_dict("Amazon"), "アマゾン")

    def test_gpt_is_defined_after_chatgpt(self):
        self.assertEqual(apply_pronunciation_dict("ChatGPT"), "チャットジーピーティー")
        self.assertEqual(apply_pronunciation_dict("GPT"), "ジーピーティー")
        # ハイフン+数字はTTSがそのまま正しく読めるため、残っていてよい。
        self.assertEqual(apply_pronunciation_dict("GPT-6"), "ジーピーティー 6")


class WordBoundaryTests(unittest.TestCase):
    """A short entry must not fire inside a longer English word."""

    def test_entries_do_not_match_inside_other_words(self):
        for source in ("Googleplex", "Metadata", "Flashlight", "Sorapunk", "Codexual"):
            with self.subTest(source=source):
                self.assertEqual(apply_pronunciation_dict(source), source)

    def test_s3_does_not_match_inside_other_tokens(self):
        for source in ("S3X", "XS3", "S30", "0S3"):
            with self.subTest(source=source):
                self.assertEqual(apply_pronunciation_dict(source), source)
        self.assertEqual(apply_pronunciation_dict("S3"), "エススリー")

    def test_it_only_matches_uppercase_exact(self):
        self.assertEqual(apply_pronunciation_dict("IT部門"), "アイティー部門")
        self.assertEqual(apply_pronunciation_dict("Make it work"), "Make it work")
        self.assertEqual(apply_pronunciation_dict("It works"), "It works")


class RegressionTests(unittest.TestCase):
    """Behaviour that existed before the dictionary was expanded."""

    def test_existing_entries_are_preserved(self):
        cases = {
            "深掘りしていきます": "詳しく見ていきます",
            "冪等性": "べき等性",
            "Claude": "クロード",
            "ChatGPT": "チャットジーピーティー",
            "Anthropic": "アンスロピック",
            "TechCrunch": "テッククランチ",
            "Hugging Face": "ハギングフェイス",
            "DeepMind": "ディープマインド",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(apply_pronunciation_dict(source), expected)

    def test_empty_input_is_safe(self):
        self.assertEqual(apply_pronunciation_dict(""), "")
        self.assertEqual(apply_pronunciation_dict(None), "")


class SpokenScriptTests(unittest.TestCase):
    """A realistic line should leave nothing for the Japanese voice to stumble on."""

    def test_a_representative_line_is_fully_readable(self):
        line = (
            "Google AI Blog によると、Gemini 3.8 Flash が発表されました。"
            "TechCrunch は Anthropic の Claude について報じ、"
            "ITmedia AI+ と AI Watch も続いています。"
            "手元では Obsidian と Notion に記録し、GitHub Actions と Cloudflare Workers で動かします。"
        )
        self.assertEqual(latin_left(apply_pronunciation_dict(line)), [])

    def test_a_line_with_aws_terms_is_fully_readable(self):
        line = (
            "AWS 上で Amazon S3 を使い、FAA は GPT-6 と Astra の検証を進めています。"
        )
        self.assertEqual(latin_left(apply_pronunciation_dict(line)), [])



class HyphenatedVersionTests(unittest.TestCase):
    """A converted product name followed by -<digit> must not be read as マイナス."""

    def test_hyphen_after_converted_name_becomes_a_space(self):
        self.assertEqual(apply_pronunciation_dict("GPT-6 Astra"), "ジーピーティー 6 アストラ")
        self.assertEqual(apply_pronunciation_dict("Gemini-3"), "ジェミニ 3")

    def test_hyphens_elsewhere_are_untouched(self):
        self.assertEqual(apply_pronunciation_dict("2026-09-18"), "2026-09-18")
        self.assertEqual(apply_pronunciation_dict("A-1"), "A-1")

if __name__ == "__main__":
    unittest.main()
