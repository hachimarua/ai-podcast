from episode_formats import EpisodeFormatError
from script_generator import validate_dialogue_register


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
    test_polite_register_is_consistent()
    test_casual_register_is_allowed_when_both_speakers_use_it()
    test_asymmetric_register_is_rejected()
    print("test_script_generator: ok")
