"""Tests for the template-placeholder regression gate.

Real incident: a model copied the system instruction's format example
``ケンジ：[セリフ]`` literally, producing lines like
``ケンジ：[セリフ]おはようございます…``. All existing gates passed and TTS
would have read "セリフ" aloud on every line. ``strip_template_markers``
removes that exact formatting noise deterministically (no regeneration
budget spent), and ``validate_no_placeholders`` catches anything left over,
such as placeholders that were not immediately after the speaker label.
"""

import unittest

import script_generator
from episode_formats import EpisodeFormatError


class StripTemplateMarkersTests(unittest.TestCase):
    def test_incident_shape_is_stripped_and_passes_existing_gates(self):
        raw = (
            "ケンジ：[セリフ]おはようございます、今日は新しいAIモデルの話をしましょう。\n"
            "アミ：[セリフ]はい、先週発表されたモデルについて詳しく見ていきます。\n"
            "ケンジ：[セリフ]このモデルは画像認識の精度が向上したと聞きました。\n"
            "アミ：[セリフ]その通り、特に医療画像の分野で応用が期待されています。\n"
            "ケンジ：[セリフ]今後の展開が楽しみですね、ではまた来週。\n"
        )

        cleaned, removed = script_generator.strip_template_markers(raw)

        self.assertEqual(removed, 5)
        self.assertNotIn("セリフ", cleaned)
        self.assertNotIn("[", cleaned)

        # All existing deterministic gates pass on the cleaned script.
        style = script_generator.validate_dialogue_style(cleaned)
        register = script_generator.validate_dialogue_register(cleaned)
        repetition = script_generator.validate_script_repetition(cleaned)
        placeholders = script_generator.validate_no_placeholders(cleaned)

        self.assertTrue(style["passed"])
        self.assertTrue(register["passed"])
        self.assertTrue(repetition["passed"])
        self.assertTrue(placeholders["passed"])
        self.assertEqual(placeholders["placeholder_count"], 0)
        self.assertEqual(placeholders["dialogue_line_count"], 5)

    def test_fullwidth_marker_directly_after_label_is_stripped(self):
        script = "アミ：［セリフ］こんにちは。\n"
        cleaned, removed = script_generator.strip_template_markers(script)
        self.assertEqual(removed, 1)
        self.assertEqual(cleaned, "アミ：こんにちは。\n")

    def test_half_width_colon_marker_is_stripped(self):
        script = "ケンジ:[セリフ]こんばんは。"
        cleaned, removed = script_generator.strip_template_markers(script)
        self.assertEqual(removed, 1)
        self.assertEqual(cleaned, "ケンジ:こんばんは。")

    def test_marker_not_immediately_after_label_is_left_untouched(self):
        script = "ケンジ：これは[セリフ]という意味の言葉です。\n"

        cleaned, removed = script_generator.strip_template_markers(script)

        self.assertEqual(removed, 0)
        self.assertEqual(cleaned, script)

        # It must instead be caught by validate_no_placeholders.
        result = script_generator.validate_no_placeholders(script, enforce=False)
        self.assertFalse(result["passed"])
        self.assertEqual(result["placeholder_count"], 1)


class ValidateNoPlaceholdersTests(unittest.TestCase):
    def test_circle_and_bracket_instruction_placeholders_fail(self):
        script = (
            "ケンジ：今日は〇〇について話します。\n"
            "アミ：[ここに具体例]を後で埋めてください。\n"
        )

        result = script_generator.validate_no_placeholders(script, enforce=False)

        self.assertFalse(result["passed"])
        self.assertEqual(result["placeholder_count"], 2)
        self.assertEqual(result["dialogue_line_count"], 2)

        with self.assertRaises(EpisodeFormatError):
            script_generator.validate_no_placeholders(script)

    def test_fullwidth_instruction_bracket_fails(self):
        script = "ケンジ：【会社名を入れる】の担当者にお伝えください。\n"

        result = script_generator.validate_no_placeholders(script, enforce=False)

        self.assertFalse(result["passed"])
        self.assertEqual(result["placeholder_count"], 1)

    def test_title_line_and_normal_japanese_brackets_pass(self):
        script = (
            "【表示タイトル】新しいAIモデルの発表について\n"
            "ケンジ：先日「注意点」について話しましたが（前回のおさらいです）、"
            "今日は続きを解説します。\n"
            "アミ：はい、（補足しますと）「実際の使い方」を見ていきましょう。\n"
        )

        result = script_generator.validate_no_placeholders(script)

        self.assertTrue(result["passed"])
        self.assertEqual(result["placeholder_count"], 0)
        # Only the two speaker-labelled lines count; the title line is not
        # dialogue and must not be scanned.
        self.assertEqual(result["dialogue_line_count"], 2)

    def test_x_marks_placeholder_fails(self):
        script = "アミ：詳細はまだ××で確定していません。\n"

        result = script_generator.validate_no_placeholders(script, enforce=False)

        self.assertFalse(result["passed"])
        self.assertEqual(result["placeholder_count"], 1)


if __name__ == "__main__":
    unittest.main()
