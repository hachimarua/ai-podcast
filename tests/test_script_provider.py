"""Tests for the OpenAI script provider and its fallback to Gemini.

No network access: ``generate_with_openai`` is exercised with a fake ``post``/
``sleep`` pair, and ``generate_radio_script`` is exercised with
``script_generator.generate_with_openai`` / ``script_generator.get_gemini_client``
patched out.
"""

import os
import unittest
from unittest.mock import patch

import episode_history
import openai_script_client
import script_generator
from openai_script_client import generate_with_openai


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _ok_payload(text="こんにちは、今日のニュースです。", **usage_overrides):
    usage = {
        "input_tokens": 120,
        "output_tokens": 340,
        "output_tokens_details": {"reasoning_tokens": 40},
        "total_tokens": 460,
    }
    usage.update(usage_overrides)
    return {
        "status": "completed",
        "output_text": text,
        "usage": usage,
    }


class GenerateWithOpenAITests(unittest.TestCase):
    def setUp(self):
        self._env_patch = patch.dict(
            os.environ, {"OPENAI_API_KEY": "sk-test-secret-value"}, clear=False
        )
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

    def test_success_returns_text_and_usage_tokens(self):
        posts = [FakeResponse(200, _ok_payload())]
        post = unittest.mock.Mock(side_effect=posts)
        sleeps = unittest.mock.Mock()

        text, info = generate_with_openai("system", "prompt", sleep=sleeps, post=post)

        self.assertEqual(text, "こんにちは、今日のニュースです。")
        self.assertEqual(info["input_tokens"], 120)
        self.assertEqual(info["output_tokens"], 340)
        self.assertEqual(info["reasoning_tokens"], 40)
        self.assertEqual(info["total_tokens"], 460)
        self.assertEqual(info["provider"], "openai")
        sleeps.assert_not_called()

    def test_two_transient_failures_then_success(self):
        posts = [
            FakeResponse(503, {"error": {"message": "overloaded"}}),
            FakeResponse(503, {"error": {"message": "overloaded"}}),
            FakeResponse(200, _ok_payload()),
        ]
        post = unittest.mock.Mock(side_effect=posts)
        sleeps = unittest.mock.Mock()

        text, info = generate_with_openai("system", "prompt", sleep=sleeps, post=post)

        self.assertEqual(text, "こんにちは、今日のニュースです。")
        self.assertEqual(info["attempts"], 3)
        sleeps.assert_has_calls([unittest.mock.call(5), unittest.mock.call(15)])
        self.assertEqual(sleeps.call_count, 2)

    def test_four_transient_failures_exhausts_retries(self):
        posts = [FakeResponse(503, {"error": {}}) for _ in range(4)]
        post = unittest.mock.Mock(side_effect=posts)
        sleeps = unittest.mock.Mock()

        text, info = generate_with_openai("system", "prompt", sleep=sleeps, post=post)

        self.assertIsNone(text)
        self.assertEqual(info["error_category"], "openai_transient_exhausted")
        self.assertEqual(sleeps.call_count, 3)

    def test_quota_error_is_not_retried(self):
        posts = [
            FakeResponse(
                429,
                {"error": {"code": "insufficient_quota", "type": "insufficient_quota"}},
            )
        ]
        post = unittest.mock.Mock(side_effect=posts)
        sleeps = unittest.mock.Mock()

        text, info = generate_with_openai("system", "prompt", sleep=sleeps, post=post)

        self.assertIsNone(text)
        self.assertEqual(info["error_category"], "openai_quota")
        sleeps.assert_not_called()
        self.assertEqual(post.call_count, 1)

    def test_401_is_auth_error(self):
        posts = [FakeResponse(401, {"error": {"message": "bad key"}})]
        post = unittest.mock.Mock(side_effect=posts)
        sleeps = unittest.mock.Mock()

        text, info = generate_with_openai("system", "prompt", sleep=sleeps, post=post)

        self.assertIsNone(text)
        self.assertEqual(info["error_category"], "openai_auth")
        sleeps.assert_not_called()

    def test_400_is_bad_request(self):
        posts = [FakeResponse(400, {"error": {"message": "bad request"}})]
        post = unittest.mock.Mock(side_effect=posts)
        sleeps = unittest.mock.Mock()

        text, info = generate_with_openai("system", "prompt", sleep=sleeps, post=post)

        self.assertIsNone(text)
        self.assertEqual(info["error_category"], "openai_bad_request")
        sleeps.assert_not_called()

    def test_timeout_is_retried(self):
        posts = [
            openai_script_client.requests.Timeout("timed out"),
            FakeResponse(200, _ok_payload()),
        ]

        def fake_post(*args, **kwargs):
            item = posts.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        sleeps = unittest.mock.Mock()
        text, info = generate_with_openai(
            "system", "prompt", sleep=sleeps, post=fake_post
        )

        self.assertEqual(text, "こんにちは、今日のニュースです。")
        self.assertEqual(info["attempts"], 2)
        sleeps.assert_called_once_with(5)

    def test_incomplete_status_falls_back(self):
        payload = _ok_payload()
        payload["status"] = "incomplete"
        posts = [FakeResponse(200, payload)]
        post = unittest.mock.Mock(side_effect=posts)
        sleeps = unittest.mock.Mock()

        text, info = generate_with_openai("system", "prompt", sleep=sleeps, post=post)

        self.assertIsNone(text)
        self.assertEqual(info["error_category"], "openai_incomplete")

    def test_empty_output_falls_back(self):
        payload = _ok_payload(text="")
        payload["output_text"] = ""
        posts = [FakeResponse(200, payload)]
        post = unittest.mock.Mock(side_effect=posts)
        sleeps = unittest.mock.Mock()

        text, info = generate_with_openai("system", "prompt", sleep=sleeps, post=post)

        self.assertIsNone(text)
        self.assertEqual(info["error_category"], "openai_empty_output")

    def test_missing_key_never_calls_post(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            post = unittest.mock.Mock()
            sleeps = unittest.mock.Mock()
            text, info = generate_with_openai(
                "system", "prompt", sleep=sleeps, post=post
            )
        self.assertIsNone(text)
        self.assertEqual(info["error_category"], "openai_unconfigured")
        post.assert_not_called()

    def test_placeholder_key_never_calls_post(self):
        with patch.dict(
            os.environ, {"OPENAI_API_KEY": "YOUR_OPENAI_API_KEY"}, clear=False
        ):
            post = unittest.mock.Mock()
            sleeps = unittest.mock.Mock()
            text, info = generate_with_openai(
                "system", "prompt", sleep=sleeps, post=post
            )
        self.assertIsNone(text)
        self.assertEqual(info["error_category"], "openai_unconfigured")
        post.assert_not_called()

    def test_api_key_never_appears_in_info(self):
        posts = [FakeResponse(200, _ok_payload())]
        post = unittest.mock.Mock(side_effect=posts)
        sleeps = unittest.mock.Mock()

        _, info = generate_with_openai("system", "prompt", sleep=sleeps, post=post)

        self.assertNotIn("sk-test-secret-value", repr(info))


class FakeUsageMetadata:
    prompt_token_count = 500
    candidates_token_count = 800
    thoughts_token_count = 30
    total_token_count = 1330


class FakeGeminiResponse:
    text = "ケンジ：おはようございます。\nアミ：今日のAIニュースをお届けします。"
    usage_metadata = FakeUsageMetadata()


class FakeGeminiModels:
    def generate_content(self, **kwargs):
        return FakeGeminiResponse()


class FakeGeminiClient:
    def __init__(self):
        self.models = FakeGeminiModels()


def _news_fixture():
    return [
        {
            "source": "TechCrunch AI",
            "title": "New model release",
            "link": "https://example.com/news",
            "content": "A brief description of the news for the test fixture.",
        }
    ]


class GenerateRadioScriptProviderSwitchTests(unittest.TestCase):
    def setUp(self):
        script_generator.reset_script_generation_log()
        self.addCleanup(script_generator.reset_script_generation_log)

    def test_openai_success_skips_gemini(self):
        openai_text = (
            "【表示タイトル】OpenAIが書いた見出し\n"
            "ケンジ：おはようございます。\nアミ：今日のAIニュースをお届けします。"
        )
        fake_generate = unittest.mock.Mock(
            return_value=(
                openai_text,
                {
                    "provider": "openai",
                    "model": "gpt-5.6-terra",
                    "attempts": 1,
                    "input_tokens": 100,
                    "output_tokens": 200,
                },
            )
        )
        fake_gemini_client = unittest.mock.Mock(
            side_effect=AssertionError("Gemini client must not be constructed")
        )

        with patch.dict(os.environ, {"SCRIPT_PROVIDER": "openai"}, clear=False):
            with (
                patch.object(script_generator, "generate_with_openai", fake_generate),
                patch.object(script_generator, "get_gemini_client", fake_gemini_client),
            ):
                result = script_generator.generate_radio_script(
                    [], _news_fixture(), [], episode_format="daily"
                )
            summary = script_generator.script_generation_summary()

        self.assertEqual(result, openai_text)
        fake_gemini_client.assert_not_called()
        self.assertEqual(summary["provider"], "openai")
        self.assertEqual(summary["primary_provider"], "openai")
        self.assertFalse(summary["fallback_used"])
        self.assertEqual(summary["fallback_count"], 0)

    def test_openai_failure_falls_back_to_gemini(self):
        fake_generate = unittest.mock.Mock(
            return_value=(
                None,
                {
                    "provider": "openai",
                    "model": "gpt-5.6-terra",
                    "attempts": 4,
                    "error_category": "openai_transient_exhausted",
                },
            )
        )
        fake_client = FakeGeminiClient()

        with patch.dict(os.environ, {"SCRIPT_PROVIDER": "openai"}, clear=False):
            with (
                patch.object(script_generator, "generate_with_openai", fake_generate),
                patch.object(
                    script_generator, "get_gemini_client", return_value=fake_client
                ),
            ):
                result = script_generator.generate_radio_script(
                    [], _news_fixture(), [], episode_format="daily"
                )
            summary = script_generator.script_generation_summary()

        self.assertEqual(result, FakeGeminiResponse.text)
        self.assertEqual(summary["provider"], "gemini")
        self.assertTrue(summary["fallback_used"])
        self.assertEqual(summary["fallback_count"], 1)
        self.assertEqual(len(summary["calls"]), 2)
        self.assertEqual(
            summary["calls"][0]["fallback_reason"], "openai_transient_exhausted"
        )


class GenerateRadioScriptProviderDefaultTests(unittest.TestCase):
    def setUp(self):
        script_generator.reset_script_generation_log()
        self.addCleanup(script_generator.reset_script_generation_log)

    def _assert_openai_never_called(self, env_value):
        fake_openai = unittest.mock.Mock(
            side_effect=AssertionError("OpenAI must not be called")
        )
        fake_client = FakeGeminiClient()
        env = {}
        if env_value is None:
            # Ensure any inherited SCRIPT_PROVIDER does not leak into the test.
            env_ctx = patch.dict(os.environ, {}, clear=False)
        else:
            env["SCRIPT_PROVIDER"] = env_value
            env_ctx = patch.dict(os.environ, env, clear=False)

        with env_ctx:
            if env_value is None:
                os.environ.pop("SCRIPT_PROVIDER", None)
            with (
                patch.object(script_generator, "generate_with_openai", fake_openai),
                patch.object(
                    script_generator, "get_gemini_client", return_value=fake_client
                ),
            ):
                result = script_generator.generate_radio_script(
                    [], _news_fixture(), [], episode_format="daily"
                )
        self.assertEqual(result, FakeGeminiResponse.text)
        fake_openai.assert_not_called()

    def test_unset_provider_never_calls_openai(self):
        self._assert_openai_never_called(None)

    def test_gemini_provider_never_calls_openai(self):
        self._assert_openai_never_called("gemini")

    def test_garbage_provider_never_calls_openai(self):
        self._assert_openai_never_called("totally-not-a-real-provider")


class PublicDeterministicChecksScriptGenerationTests(unittest.TestCase):
    def test_closed_fields_survive_and_free_text_is_dropped(self):
        summary = {
            "primary_provider": "openai",
            "provider": "gemini",
            "model": "hello world",
            "fallback_used": True,
            "fallback_count": 1,
            "calls": [
                {
                    "provider": "openai",
                    "model": "gpt-5.6-terra",
                    "succeeded": False,
                    "fallback_reason": "some prose that should never be public",
                    "attempts": 4,
                    "input_tokens": 12,
                },
                {
                    "provider": "gemini",
                    "model": "gemini-3.7-flash",
                    "succeeded": True,
                    "fallback_used": True,
                    "attempts": 1,
                    "output_tokens": 34,
                },
            ],
        }

        cleaned = episode_history.public_deterministic_checks(
            {"script_generation": summary}
        )
        sg = cleaned["script_generation"]

        self.assertEqual(sg["primary_provider"], "openai")
        # Free-text model name is dropped because it does not match the model regex.
        self.assertNotIn("model", sg)
        self.assertTrue(sg["fallback_used"])
        self.assertEqual(sg["fallback_count"], 1)
        self.assertEqual(len(sg["calls"]), 2)
        self.assertEqual(sg["calls"][0]["provider"], "openai")
        self.assertEqual(sg["calls"][0]["model"], "gpt-5.6-terra")
        self.assertNotIn("fallback_reason", sg["calls"][0])
        self.assertEqual(sg["calls"][0]["attempts"], 4)
        self.assertEqual(sg["calls"][0]["input_tokens"], 12)
        self.assertEqual(sg["calls"][1]["model"], "gemini-3.7-flash")
        self.assertEqual(sg["calls"][1]["output_tokens"], 34)


class WorkflowScriptProviderGuardTests(unittest.TestCase):
    def test_pipeline_step_forwards_openai_credentials_and_provider(self):
        workflow_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".github",
            "workflows",
            "podcast.yml",
        )
        with open(workflow_path, "r", encoding="utf-8") as handle:
            content = handle.read()

        pipeline_step_start = content.index("Run Podcast Pipeline")
        next_step = content.find("\n    - name:", pipeline_step_start)
        pipeline_step = content[pipeline_step_start : next_step if next_step != -1 else None]

        self.assertIn("OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}", pipeline_step)
        self.assertIn("SCRIPT_PROVIDER:", pipeline_step)


if __name__ == "__main__":
    unittest.main()
