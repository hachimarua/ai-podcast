from unittest.mock import call, patch

from episode_formats import EpisodeFormatError
import script_generator
from script_generator import validate_dialogue_register


class _TransientGeminiError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.code = status_code


class _FakeGeminiModels:
    def __init__(self, responses):
        self.responses = list(responses)

    def generate_content(self, **_kwargs):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _FakeGeminiClient:
    def __init__(self, responses):
        self.models = _FakeGeminiModels(responses)


class _FakeGeminiResponse:
    text = "ケンジ：今日は確認します。\nアミ：はい、整理します。"


def test_transient_generation_has_one_final_delayed_retry():
    client = _FakeGeminiClient(
        [_TransientGeminiError(503) for _ in range(5)]
        + [_FakeGeminiResponse()]
    )
    with (
        patch.object(script_generator, "get_gemini_client", return_value=client),
        patch.object(script_generator.time, "sleep") as sleep,
    ):
        result = script_generator.generate_radio_script([], [], [])

    assert result == _FakeGeminiResponse.text
    assert sleep.call_args_list == [
        call(5),
        call(15),
        call(30),
        call(60),
        call(300),
    ]


def test_transient_generation_stops_after_final_retry():
    client = _FakeGeminiClient(
        [_TransientGeminiError(503) for _ in range(6)]
    )
    with (
        patch.object(script_generator, "get_gemini_client", return_value=client),
        patch.object(script_generator.time, "sleep") as sleep,
    ):
        result = script_generator.generate_radio_script([], [], [])

    assert result is None
    assert sleep.call_args_list == [
        call(5),
        call(15),
        call(30),
        call(60),
        call(300),
    ]


def test_polite_register_is_consistent():
    script = """
ケンジ：今日は新しい機能について確認します。
アミ：はい、まず仕組みを整理します。
ケンジ：利用条件も押さえておきたいです。
アミ：その点は公式情報を確認しましょう。
"""
    result = validate_dialogue_register(script)
    assert result["passed"] is True


def test_casual_register_is_allowed_when_both_speakers_use_it():
    script = """
ケンジ：今日は新しい機能を見るよ。
アミ：うん、まず仕組みを整理しよう。
ケンジ：利用条件も押さえたいね。
アミ：その点は公式情報で確認するよ。
"""
    result = validate_dialogue_register(script)
    assert result["passed"] is True


def test_asymmetric_register_is_rejected():
    script = """
ケンジ：今日は新しい機能を確認するよ。
アミ：はい、まず仕組みを整理します。
ケンジ：利用条件も押さえたいね。
アミ：その点は公式情報を確認しましょう。
"""
    try:
        validate_dialogue_register(script)
    except EpisodeFormatError as exc:
        assert "asymmetric" in str(exc)
    else:
        raise AssertionError("asymmetric dialogue register was accepted")


if __name__ == "__main__":
    test_transient_generation_has_one_final_delayed_retry()
    test_transient_generation_stops_after_final_retry()
    test_polite_register_is_consistent()
    test_casual_register_is_allowed_when_both_speakers_use_it()
    test_asymmetric_register_is_rejected()
    print("test_script_generator: ok")
