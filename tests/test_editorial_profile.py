import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import re

from pydantic import ValidationError

import editorial_profile
import script_generator


class EditorialProfileTests(unittest.TestCase):
    def valid_payload(self):
        return {
            "schema_version": 1,
            "profile_version": "editorial-v1",
            "approval_status": "pending",
            "experience_band": "workflow_builder_operator",
            "working_modes": ["multi_model_use", "coding_agent_collaboration"],
            "available_tools": ["chatgpt_and_codex", "notion", "apple_shortcuts"],
            "mastered_basics": ["chat_q_and_a", "basic_prompt_structure"],
            "interest_domains": ["ai_agents_and_coding", "reliability_qa"],
            "editorial_preferences": ["implementation_first", "avoid_beginner_tips"],
        }

    def test_committed_profile_is_valid_and_closed(self):
        profile = editorial_profile.load_editorial_profile()
        self.assertEqual(profile.profile_version, "editorial-v1")
        self.assertIn(profile.approval_status, {"pending", "approved"})

    def test_pending_profile_uses_legacy_instruction(self):
        profile = editorial_profile.EditorialProfile.model_validate(self.valid_payload())
        self.assertEqual(editorial_profile.get_approved_profile_instruction(profile), "")
        with patch.object(
            script_generator, "get_approved_profile_instruction", return_value=""
        ):
            instruction = script_generator.build_system_instruction()
        self.assertIn("現行の対象像", instruction)

    def test_render_uses_fixed_phrases_and_no_raw_enum_metadata(self):
        profile = editorial_profile.EditorialProfile.model_validate(self.valid_payload())
        rendered = editorial_profile.render_editorial_profile(profile)
        self.assertIn("AIを使って仕組みを設計・検証・運用している実践者", rendered)
        self.assertIn("人物紹介として読み上げ", rendered)
        self.assertIn("ChatGPTとCodex", rendered)
        self.assertNotIn("workflow_builder_operator", rendered)
        self.assertNotIn("profile_version", rendered)

    def test_approved_profile_can_be_injected(self):
        payload = self.valid_payload()
        payload["approval_status"] = "approved"
        profile = editorial_profile.EditorialProfile.model_validate(payload)
        instruction = editorial_profile.get_approved_profile_instruction(profile)
        self.assertIn("番組用編集プロフィール", instruction)

    def test_script_generator_adds_profile_only_to_system_instruction(self):
        marker = "【番組用編集プロフィール】\n- fixed-safe-marker"
        with patch.object(
            script_generator, "get_approved_profile_instruction", return_value=marker
        ):
            instruction = script_generator.build_system_instruction()
        prompt = script_generator.build_prompt_content([], [], [])
        self.assertIn(marker, instruction)
        self.assertNotIn("現行の対象像", instruction)
        self.assertNotIn(marker, prompt)

    def test_old_hard_coded_audience_is_not_in_base_instruction(self):
        self.assertNotIn("有料プランに課金している非エンジニア", script_generator.SYSTEM_INSTRUCTION)
        self.assertNotIn("非エンジニアのビジネス層", script_generator.SYSTEM_INSTRUCTION)

    def test_unknown_field_is_rejected(self):
        payload = self.valid_payload()
        payload["home_address"] = "synthetic"
        with self.assertRaises(ValidationError):
            editorial_profile.EditorialProfile.model_validate(payload)

    def test_free_text_or_secret_like_values_cannot_enter_enum_fields(self):
        payload = self.valid_payload()
        payload["working_modes"] = ["/Users/example/private"]
        with self.assertRaises(ValidationError):
            editorial_profile.EditorialProfile.model_validate(payload)

    def test_duplicate_enum_values_are_rejected(self):
        payload = self.valid_payload()
        payload["interest_domains"] = ["reliability_qa", "reliability_qa"]
        with self.assertRaises(ValidationError):
            editorial_profile.EditorialProfile.model_validate(payload)

    def test_rendered_profile_contains_no_sensitive_shape(self):
        profile = editorial_profile.load_editorial_profile()
        rendered = editorial_profile.render_editorial_profile(profile)
        denied = [
            r"/Users/",
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            r"\b\d{1,3}歳\b",
            r"https?://",
            r"(?i)(api[_-]?key|secret|token)",
            r"(病院|患者|診療|医師)",
        ]
        for pattern in denied:
            self.assertIsNone(re.search(pattern, rendered), pattern)

    def test_invalid_profile_version_is_rejected(self):
        payload = self.valid_payload()
        payload["profile_version"] = "private-notes-2026-07-14"
        with self.assertRaises(ValidationError):
            editorial_profile.EditorialProfile.model_validate(payload)

    def test_symlink_profile_is_rejected_before_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            link = root / "editorial_profile.json"
            link.symlink_to(target)
            with patch.object(editorial_profile, "PROFILE_PATH", link):
                with self.assertRaises(editorial_profile.EditorialProfileError):
                    editorial_profile.load_editorial_profile()

    def test_missing_and_malformed_profile_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"
            with patch.object(editorial_profile, "PROFILE_PATH", missing):
                with self.assertRaises(editorial_profile.EditorialProfileError):
                    editorial_profile.load_editorial_profile()

            malformed = Path(tmp) / "malformed.json"
            malformed.write_text("{not-json", encoding="utf-8")
            with patch.object(editorial_profile, "PROFILE_PATH", malformed):
                with self.assertRaises(editorial_profile.EditorialProfileError):
                    editorial_profile.load_editorial_profile()

    def test_generation_stops_before_client_when_profile_is_invalid(self):
        with (
            patch.object(
                script_generator,
                "get_approved_profile_instruction",
                side_effect=editorial_profile.EditorialProfileError("unsafe"),
            ),
            patch.object(script_generator, "get_gemini_client") as get_client,
        ):
            with self.assertRaises(editorial_profile.EditorialProfileError):
                script_generator.generate_radio_script([], [], [])
        get_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
