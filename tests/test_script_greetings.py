"""Tests for opening and closing greetings stability in podcast scripts."""

import re
import unittest
from script_generator import (
    check_script_greetings,
    ensure_script_greetings,
    OPENING_GREETING_PATTERNS,
    CLOSING_GREETING_PATTERNS,
)


class ScriptGreetingsTests(unittest.TestCase):
    def test_check_greetings_both_present(self):
        script = """
ケンジ：おはようございます。AI学習カーラジオです。今日のテーマを整理します。
アミ：はい、最新の研究動向を見ていきましょう。
ケンジ：今回は以上です。それでは、また次回。
"""
        status = check_script_greetings(script)
        self.assertTrue(status["opening_present"])
        self.assertTrue(status["closing_present"])
        self.assertEqual(status["dialogue_line_count"], 3)

    def test_check_greetings_missing_opening(self):
        script = """
ケンジ：今日はNotionの学習メモ、「イテレーション」を復習します。
アミ：はい、反復改善の重要性を整理しましょう。
ケンジ：今回は以上です。それでは、また次回。
"""
        status = check_script_greetings(script)
        self.assertFalse(status["opening_present"])
        self.assertTrue(status["closing_present"])

    def test_check_greetings_missing_closing(self):
        # 2026-09-26 の実際の台本のようにまとめだけで終わるケース
        script = """
アミ：おはようございます。今日はNotionの学習メモ、「イテレーション」を復習します。
ケンジ：反復の価値はフィードバックを受け取れる点にあります。
アミ：移動中の一歩として、次に回す作業で検証対象を一つずつ言語化してみてください。
"""
        status = check_script_greetings(script)
        self.assertTrue(status["opening_present"])
        self.assertFalse(status["closing_present"])

    def test_no_double_addition_when_greetings_exist(self):
        script = """
ケンジ：おはようございます。AI学習カーラジオです。今日のテーマを取り上げます。
アミ：よろしくお願いします。
ケンジ：今回は以上です。それでは、また次回。
"""
        result, info = ensure_script_greetings(
            script, topic="テストトピック", role_plan={"navigator": "ケンジ", "explainer": "アミ"}
        )
        self.assertTrue(info["opening_present"])
        self.assertTrue(info["closing_present"])
        self.assertFalse(info["opening_fallback_added"])
        self.assertFalse(info["closing_fallback_added"])
        self.assertEqual(result.strip(), script.strip())

    def test_opening_fallback_added_with_navigator(self):
        script = """
ケンジ：今日はNotionの学習メモを復習します。
アミ：はい、見ていきましょう。
ケンジ：今回は以上です。それでは、また次回。
"""
        # navigator がアミの場合
        result, info = ensure_script_greetings(
            script,
            topic="規格パーサと音声生成",
            role_plan={"navigator": "アミ", "explainer": "ケンジ"},
        )
        self.assertFalse(info["opening_present"])
        self.assertTrue(info["opening_fallback_added"])
        self.assertFalse(info["closing_fallback_added"])

        lines = [line.strip() for line in result.splitlines() if line.strip()]
        self.assertTrue(lines[0].startswith("アミ：おはようございます。AI学習カーラジオです。"))
        self.assertIn("規格パーサと音声生成", lines[0])

    def test_closing_fallback_alternates_speaker(self):
        # 最終話者がアミの場合、closing はケンジになる
        script = """
ケンジ：おはようございます。AI学習カーラジオです。
アミ：今日は新しい機能の使いどころを解説します。
アミ：日々の業務に合わせて検証してみてください。
"""
        result, info = ensure_script_greetings(
            script,
            topic="エージェント監査",
            role_plan={"navigator": "ケンジ", "explainer": "アミ"},
        )
        self.assertTrue(info["opening_present"])
        self.assertFalse(info["closing_present"])
        self.assertFalse(info["opening_fallback_added"])
        self.assertTrue(info["closing_fallback_added"])

        lines = [line.strip() for line in result.splitlines() if line.strip()]
        self.assertEqual(lines[-1], "ケンジ：今回は以上です。それでは、また次回。")

        # 最終話者がケンジの場合、closing はアミになる
        script_kenji_last = """
アミ：おはようございます。AI学習カーラジオです。
ケンジ：最後の一歩として、設定を確認しておきましょう。
"""
        result2, info2 = ensure_script_greetings(
            script_kenji_last,
            role_plan={"navigator": "アミ", "explainer": "ケンジ"},
        )
        self.assertTrue(info2["closing_fallback_added"])
        lines2 = [line.strip() for line in result2.splitlines() if line.strip()]
        self.assertEqual(lines2[-1], "アミ：今回は以上です。それでは、また次回。")

    def test_both_greetings_missing(self):
        script = """
ケンジ：今日復習するキーワードはイテレーションです。
アミ：信頼できるフィードバックで更新していきましょう。
"""
        result, info = ensure_script_greetings(
            script,
            topic="自律エージェントの検証",
            role_plan={"navigator": "ケンジ", "explainer": "アミ"},
        )
        self.assertFalse(info["opening_present"])
        self.assertFalse(info["closing_present"])
        self.assertTrue(info["opening_fallback_added"])
        self.assertTrue(info["closing_fallback_added"])

        lines = [line.strip() for line in result.splitlines() if line.strip()]
        self.assertTrue(lines[0].startswith("ケンジ：おはようございます。AI学習カーラジオです。"))
        self.assertEqual(lines[-1], "ケンジ：今回は以上です。それでは、また次回。")

    def test_preserves_public_title_prefix(self):
        script = """【表示タイトル】イテレーションとAI監査
ケンジ：今日はNotionのメモを復習します。
アミ：見ていきましょう。
"""
        result, info = ensure_script_greetings(
            script,
            topic="イテレーションとAI監査",
            role_plan={"navigator": "ケンジ", "explainer": "アミ"},
        )
        lines = [line.strip() for line in result.splitlines() if line.strip()]
        self.assertEqual(lines[0], "【表示タイトル】イテレーションとAI監査")
        self.assertTrue(lines[1].startswith("ケンジ：おはようございます。AI学習カーラジオです。"))
        self.assertEqual(lines[-1], "ケンジ：今回は以上です。それでは、また次回。")

    def test_empty_and_whitespace_safety(self):
        for empty in ("", "   ", "\n\n"):
            result, info = ensure_script_greetings(empty)
            self.assertFalse(info["opening_fallback_added"])
            self.assertFalse(info["closing_fallback_added"])

    def test_preview_script_not_doubled(self):
        # script_generator のモックプレビュー台本
        preview = (
            "【表示タイトル】AIの最新情報を実務につなげる考え方\n"
            "ケンジ：皆さん、おはようございます！今日のナビゲーターです。\n"
            "アミ：おはようございます。今日は提供された情報をもとに、背景と使いどころを解説します。\n"
            "ケンジ：まず、今回の情報で押さえるべき点を教えてください。\n"
            "アミ：確認できる事実を整理し、適用できる条件と注意点を分けて見ていきます。\n"
            "ケンジ：条件を分けて考えると、実際に試す場面を判断しやすくなりますね。\n"
            "アミ：その視点で、今日も無理なく学びを実務へつなげていきましょう。\n"
            "ケンジ：それでは、いってらっしゃい！"
        )
        result, info = ensure_script_greetings(
            preview,
            topic="AIの最新情報を実務につなげる考え方",
            role_plan={"navigator": "ケンジ", "explainer": "アミ"},
        )
        self.assertTrue(info["opening_present"])
        self.assertTrue(info["closing_present"])
        self.assertFalse(info["opening_fallback_added"])
        self.assertFalse(info["closing_fallback_added"])


if __name__ == "__main__":
    unittest.main()
