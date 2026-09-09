import script_generator


def test_generated_title_overrides_japanese_first_source_title():
    original = "マラソン大会のポスターが“AIっぽい”と波紋"
    generated = "Adobeの生成AI機能とClaudeトークン窃取を整理"

    assert script_generator.choose_public_topic(original, generated) == generated


def test_missing_generated_title_falls_back_to_first_source_title():
    original = "マラソン大会のポスターが“AIっぽい”と波紋"

    assert script_generator.choose_public_topic(original, None) == original


def test_invalid_generated_title_falls_back_to_first_source_title():
    original = "マラソン大会のポスターが“AIっぽい”と波紋"

    assert script_generator.choose_public_topic(original, "Adobe Premiere") == original


def test_split_generated_title_and_dialogue_supports_multi_news_editorial_choice():
    raw = (
        "【表示タイトル】Adobeの生成AI機能とClaudeトークン窃取を整理\n"
        "ケンジ：今日はAdobeとClaudeの2つの話題を見ます。\n"
        "アミ：どちらも実務上の注意点があります。"
    )

    dialogue, generated = script_generator.split_generated_script_output(raw)

    assert generated == "Adobeの生成AI機能とClaudeトークン窃取を整理"
    assert dialogue.startswith("ケンジ：今日はAdobeとClaude")
