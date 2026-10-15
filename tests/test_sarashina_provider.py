"""Tests for Sarashina as the primary script writer, and its fallback to OpenAI/Gemini.

No network access: ``generate_with_sarashina`` runs with a fake ``post``/``sleep``
pair, and ``generate_radio_script`` runs with the provider functions patched out.
"""

import os
import unittest
from unittest.mock import Mock, patch

import requests

import episode_history
import sarashina_script_client
import script_generator
from sarashina_script_client import generate_with_sarashina


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _ok_payload(text="アミ：おはようございます、ai podcastsです。", finish_reason="stop"):
    return {
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                     "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 6688, "completion_tokens": 563, "total_tokens": 7251},
    }


class GenerateWithSarashinaTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"SARASHINA_API_KEY": "sara-test-secret-value"}, clear=False)
        env.start()
        self.addCleanup(env.stop)

    def test_success_sends_documented_fields_and_records_usage(self):
        post = Mock(return_value=FakeResponse(200, _ok_payload()))
        text, info = generate_with_sarashina("system", "prompt", sleep=Mock(), post=post)

        self.assertEqual(text, "アミ：おはようございます、ai podcastsです。")
        body = post.call_args.kwargs["json"]
        # 未定義のフィールドは 400 になるので、max_tokens・reasoning は送らない。
        self.assertEqual(set(body), {"model", "max_completion_tokens", "messages"})
        self.assertEqual(body["model"], "sarashina3-mini")
        self.assertEqual(body["max_completion_tokens"], 8000)
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertEqual(info["input_tokens"], 6688)
        self.assertEqual(info["output_tokens"], 563)
        self.assertEqual(info["provider"], "sarashina")

    def test_rate_limit_waits_then_succeeds(self):
        post = Mock(side_effect=[FakeResponse(429), FakeResponse(200, _ok_payload())])
        sleep = Mock()
        text, info = generate_with_sarashina("s", "p", sleep=sleep, post=post)

        self.assertIsNotNone(text)
        self.assertEqual(info["attempts"], 2)
        sleep.assert_called_once_with(20)

    def test_repeated_rate_limit_is_exhausted_after_three_attempts(self):
        post = Mock(return_value=FakeResponse(429))
        sleep = Mock()
        text, info = generate_with_sarashina("s", "p", sleep=sleep, post=post)

        self.assertIsNone(text)
        self.assertEqual(info["error_category"], "sarashina_transient_exhausted")
        self.assertEqual(post.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [20, 40])

    def test_timeout_is_retried(self):
        post = Mock(side_effect=[requests.Timeout(), FakeResponse(200, _ok_payload())])
        text, _ = generate_with_sarashina("s", "p", sleep=Mock(), post=post)
        self.assertIsNotNone(text)

    def test_auth_and_beta_end_fall_back_without_waiting(self):
        for status, category in ((401, "sarashina_auth"), (403, "sarashina_auth"),
                                 (404, "sarashina_unavailable"), (400, "sarashina_bad_request")):
            with self.subTest(status=status):
                sleep = Mock()
                post = Mock(return_value=FakeResponse(status))
                text, info = generate_with_sarashina("s", "p", sleep=sleep, post=post)
                self.assertIsNone(text)
                self.assertEqual(info["error_category"], category)
                self.assertEqual(post.call_count, 1)
                sleep.assert_not_called()

    def test_truncated_or_empty_output_falls_back(self):
        for payload, category in ((_ok_payload(finish_reason="length"), "sarashina_incomplete"),
                                  (_ok_payload(text="  "), "sarashina_empty_output")):
            with self.subTest(category=category):
                post = Mock(return_value=FakeResponse(200, payload))
                text, info = generate_with_sarashina("s", "p", sleep=Mock(), post=post)
                self.assertIsNone(text)
                self.assertEqual(info["error_category"], category)

    def test_missing_key_never_calls_post(self):
        with patch.dict(os.environ, {"SARASHINA_API_KEY": ""}, clear=False):
            post = Mock()
            text, info = generate_with_sarashina("s", "p", sleep=Mock(), post=post)
        self.assertIsNone(text)
        self.assertEqual(info["error_category"], "sarashina_unconfigured")
        post.assert_not_called()

    def test_api_key_never_appears_in_info(self):
        post = Mock(return_value=FakeResponse(401))
        _, info = generate_with_sarashina("s", "p", sleep=Mock(), post=post)
        self.assertNotIn("sara-test-secret-value", repr(info))


def _news():
    return [{"source": "TechCrunch AI", "title": "t", "link": "https://example.com/n",
             "content": "A brief description of the news."}]


def _ok(provider, model):
    return Mock(return_value=(f"アミ：{provider}が書いた台本", {"provider": provider, "model": model, "attempts": 1}))


def _fail(provider, category):
    return Mock(return_value=(None, {"provider": provider, "model": "m", "attempts": 1,
                                     "error_category": category}))


class SarashinaProviderChainTests(unittest.TestCase):
    def setUp(self):
        script_generator.reset_script_generation_log()
        self.addCleanup(script_generator.reset_script_generation_log)
        env = patch.dict(os.environ, {"SCRIPT_PROVIDER": "sarashina"}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        self.no_gemini = Mock(side_effect=AssertionError("Gemini must not be constructed"))

    def _run(self, sarashina, openai, **kwargs):
        with (
            patch.object(script_generator, "generate_with_sarashina", sarashina),
            patch.object(script_generator, "generate_with_openai", openai),
            patch.object(script_generator, "get_gemini_client", self.no_gemini),
        ):
            result = script_generator.generate_radio_script([], _news(), [], episode_format="daily", **kwargs)
        return result, script_generator.script_generation_summary()

    def test_sarashina_success_skips_openai_and_gemini(self):
        openai = Mock(side_effect=AssertionError("OpenAI must not be called"))
        result, summary = self._run(_ok("sarashina", "sarashina3-mini"), openai)

        self.assertIn("sarashina", result)
        self.assertEqual(summary["primary_provider"], "sarashina")
        self.assertEqual(summary["provider"], "sarashina")
        self.assertFalse(summary["fallback_used"])
        self.assertEqual(summary["calls"][0]["purpose"], "initial")

    def test_sarashina_failure_falls_back_to_openai(self):
        result, summary = self._run(_fail("sarashina", "sarashina_auth"), _ok("openai", "gpt-6-sol"))

        self.assertIn("openai", result)
        self.assertEqual(summary["provider"], "openai")
        self.assertTrue(summary["fallback_used"])
        self.assertEqual(summary["calls"][0]["fallback_reason"], "sarashina_auth")
        self.assertEqual(summary["calls"][1]["fallback_reason"], "sarashina_auth")

    def test_both_failures_fall_back_to_gemini(self):
        gemini_client = Mock()
        gemini_client.models.generate_content.return_value = Mock(text="アミ：Geminiの台本", usage_metadata=None)
        with (
            patch.object(script_generator, "generate_with_sarashina", _fail("sarashina", "sarashina_unavailable")),
            patch.object(script_generator, "generate_with_openai", _fail("openai", "openai_quota")),
            patch.object(script_generator, "get_gemini_client", return_value=gemini_client),
        ):
            result = script_generator.generate_radio_script([], _news(), [], episode_format="daily")
        summary = script_generator.script_generation_summary()

        self.assertEqual(result, "アミ：Geminiの台本")
        self.assertEqual([c["provider"] for c in summary["calls"]], ["sarashina", "openai", "gemini"])

    def test_quality_repairs_go_to_openai_not_sarashina(self):
        for flags in ({"style_retry": True}, {"length_retry": True}, {"repetition_retry": True},
                      {"hedging_retry": True}, {"duration_retry": True}, {"prefer_backup": True}):
            with self.subTest(flags=flags):
                script_generator.reset_script_generation_log()
                sarashina = Mock(side_effect=AssertionError("repair must not use Sarashina"))
                result, summary = self._run(sarashina, _ok("openai", "gpt-6-sol"), **flags)
                self.assertIn("openai", result)
                self.assertEqual(summary["calls"][0]["purpose"], "repair")
                self.assertFalse(summary["fallback_used"])

    def test_openai_primary_is_unchanged(self):
        with patch.dict(os.environ, {"SCRIPT_PROVIDER": "openai"}, clear=False):
            sarashina = Mock(side_effect=AssertionError("Sarashina must not be called"))
            result, summary = self._run(sarashina, _ok("openai", "gpt-6-sol"))
        self.assertIn("openai", result)
        self.assertEqual(summary["primary_provider"], "openai")

    def test_gemini38_handles_initial_and_repairs_without_other_providers(self):
        for flags in ({}, {"style_retry": True}, {"prefer_backup": True}):
            with self.subTest(flags=flags):
                script_generator.reset_script_generation_log()
                client = Mock()
                client.models.generate_content.return_value = Mock(text="アミ：Geminiの台本", usage_metadata=None)
                with (
                    patch.dict(os.environ, {"SCRIPT_PROVIDER": "gemini"}, clear=False),
                    patch.object(script_generator, "generate_with_sarashina") as sarashina,
                    patch.object(script_generator, "generate_with_openai") as openai,
                    patch.object(script_generator, "get_gemini_client", return_value=client),
                ):
                    text = script_generator.generate_radio_script([], _news(), [], **flags)
                    summary = script_generator.script_generation_summary()
                sarashina.assert_not_called()
                openai.assert_not_called()
                self.assertEqual(text, "アミ：Geminiの台本")
                self.assertEqual(client.models.generate_content.call_args.kwargs["model"], "gemini-3.8-flash")
                self.assertEqual(summary["provider"], "gemini")
                self.assertEqual(summary["calls"][0]["purpose"], "initial" if not flags else "repair")


class SarashinaManifestTests(unittest.TestCase):
    def test_error_categories_and_model_survive_public_projection(self):
        for category in sarashina_script_client.ERROR_CATEGORIES:
            self.assertIn(category, episode_history.PUBLIC_CHECK_STRINGS)
        cleaned = episode_history.public_deterministic_checks({"script_generation": {
            "primary_provider": "sarashina", "provider": "openai", "model": "gpt-6-sol",
            "calls": [{"provider": "sarashina", "model": "sarashina3-mini", "purpose": "initial",
                       "succeeded": False, "fallback_reason": "sarashina_auth"},
                      {"provider": "openai", "model": "gpt-6-sol", "purpose": "repair", "succeeded": True}],
        }})["script_generation"]

        self.assertEqual(cleaned["primary_provider"], "sarashina")
        self.assertEqual(cleaned["calls"][0]["model"], "sarashina3-mini")
        self.assertEqual(cleaned["calls"][0]["purpose"], "initial")
        self.assertEqual(cleaned["calls"][0]["fallback_reason"], "sarashina_auth")
        self.assertEqual(cleaned["calls"][1]["purpose"], "repair")


class WorkflowScriptSelectionTests(unittest.TestCase):
    def test_pipeline_uses_gemini38_without_cloud_blocked_providers(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            ".github", "workflows", "podcast.yml")
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        start = content.index("Run Podcast Pipeline")
        end = content.find("\n    - name:", start)
        step = content[start: end if end != -1 else None]

        self.assertIn('SCRIPT_PROVIDER: "gemini"', step)
        self.assertIn('GEMINI_MODEL_NAME: "gemini-3.8-flash"', step)
        self.assertNotIn("SARASHINA_API_KEY:", step)
        self.assertNotIn("OPENAI_API_KEY:", step)


if __name__ == "__main__":
    unittest.main()
