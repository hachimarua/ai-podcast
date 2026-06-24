import os
import re
import asyncio
import edge_tts

# キャラクターと対応するEdgeニューラル音声の割り当て
VOICE_MAP = {
    "ケンジ": "ja-JP-KeitaNeural",   # 男性ボイス
    "アミ": "ja-JP-NanamiNeural"     # 女性ボイス
}

def apply_pronunciation_dict(text):
    """テキスト内の特定の英単語を、Edge TTSが正しく読めるようにカタカナ等に置換する"""
    if not text:
        return ""
        
    # 置換用辞書 (大文字小文字を区別せずマッチさせるため、正規表現を作成)
    replacements = {
        r'(?i)Claude': 'クロード',
        r'(?i)MCP': 'エムシーピー',
        r'(?i)LLMs': 'エルエルエムズ',
        r'(?i)LLM': 'エルエルエム',
        r'(?i)APIs': 'エーピーアイズ',
        r'(?i)API': 'エーピーアイ',
        r'(?i)Notion': 'ノーション',
        r'(?i)Gemini': 'ジェミニ',
        r'(?i)ChatGPT': 'チャットジーピーティー',
        r'(?i)OpenAI': 'オープンエーアイ',
        r'(?i)Anthropic': 'アンスロピック',
        r'(?i)RAG': 'ラグ',
    }
    
    result = text
    for pattern, replacement in replacements.items():
        result = re.sub(pattern, replacement, result)
        
    return result

async def generate_line_audio(text, voice, output_path):
    """1行のセリフの音声を生成"""
    sanitized_text = text.strip()
    if not sanitized_text:
        return False
        
    # 発音辞書の適用 (Claude などの誤読対策)
    sanitized_text = apply_pronunciation_dict(sanitized_text)
        
    # 文末に句読点を必ず付与することで、合成音声の末尾に自然な「間（余韻）」を作らせる
    if not sanitized_text.endswith(("。", "！", "？", "!", "?")):
        sanitized_text += "。"
        
    # 音声合成の実行 (話速を1.1倍速相当の +10% にスピードアップ設定)
    communicate = edge_tts.Communicate(sanitized_text, voice, rate="+10%")
    await communicate.save(output_path)
    return True

def parse_script_file(script_path):
    """台本ファイルをパースして (話者, セリフ) のリストを返す"""
    parsed_lines = []
    if not os.path.exists(script_path):
        print(f"[Error] Script file not found: {script_path}")
        return parsed_lines
        
    # 全角・半角のコロンに対応する正規表現
    pattern = re.compile(r"^(ケンジ|アミ)\s*[:：]\s*(.*)$")
    
    with open(script_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            match = pattern.match(line)
            if match:
                speaker = match.group(1)
                text = match.group(2).strip()
                if text:
                    parsed_lines.append((speaker, text))
                
    return parsed_lines

async def synthesize_podcast(script_path, output_mp3_path):
    """台本から音声ファイルを生成し、バイナリ結合してポッドキャストMP3を出力"""
    parsed_lines = parse_script_file(script_path)
    if not parsed_lines:
        print("[Error] No valid script lines found to synthesize.")
        return False
        
    print(f"台本の解析完了: {len(parsed_lines)} 行のセリフが見つかりました。")
    temp_files = []
    
    try:
        # 1. 各行の音声を一時ファイルとして生成
        print("音声の個別生成を開始します...")
        for idx, (speaker, text) in enumerate(parsed_lines):
            voice = VOICE_MAP.get(speaker)
            if not voice:
                print(f"[Warning] Unknown speaker '{speaker}', skipping.")
                continue
                
            temp_line_path = f"temp_line_{idx}.mp3"
            
            # セリフ音声の生成
            print(f" -> [{speaker}] を生成中... ({idx+1}/{len(parsed_lines)})")
            success = await generate_line_audio(text, voice, temp_line_path)
            if success:
                temp_files.append(temp_line_path)
                
        # 2. 一時ファイルをバイナリ結合
        print("\n音声ファイルの結合処理を行っています...")
        with open(output_mp3_path, "wb") as outfile:
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    with open(temp_file, "rb") as infile:
                        outfile.write(infile.read())
                        
        print(f"ポッドキャスト音声の生成が完了しました: {output_mp3_path}")
        return True
        
    except Exception as e:
        print(f"[Error] Audio synthesis failed in synthesize_podcast: {e}")
        return False
        
    finally:
        # 一時ファイルの削除クリーンアップ
        print("一時ファイルをクリーンアップしています...")
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception as e:
                    print(f"[Warning] Failed to delete temporary file {temp_file}: {e}")

if __name__ == "__main__":
    script_dir = os.path.dirname(__file__)
    test_script_path = os.path.join(script_dir, "todays_script.txt")
    output_mp3 = os.path.join(script_dir, "todays_podcast.mp3")
    
    print("音声合成のテストを開始します。")
    asyncio.run(synthesize_podcast(test_script_path, output_mp3))
