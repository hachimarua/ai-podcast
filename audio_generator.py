import os
import re
import asyncio
import edge_tts
import random
import subprocess
import shutil
import urllib.request
import time
import tempfile
from mutagen.mp3 import MP3

# キャラクターと対応するEdgeニューラル音声の割り当て
VOICE_MAP = {
    "ケンジ": "ja-JP-KeitaNeural",   # 男性ボイス
    "アミ": "ja-JP-NanamiNeural"     # 女性ボイス
}

# デフォルトのBGMリスト (朝の5分ラジオに最適な高品質アコースティック・カフェ風・クラシック音源)
DEFAULT_BGM_LIST = [
    {
        "name": "clear_air.mp3",
        "url": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Clear%20Air.mp3"
    },
    {
        "name": "porch_swing_days.mp3",
        "url": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Porch%20Swing%20Days%20-%20slower.mp3"
    },
    {
        "name": "friday_morning.mp3",
        "url": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Friday%20Morning.mp3"
    },
    {
        "name": "morning.mp3",
        "url": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Morning.mp3"
    },
    {
        "name": "carefree.mp3",
        "url": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Carefree.mp3"
    },
    {
        "name": "montauk_point.mp3",
        "url": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Montauk%20Point.mp3"
    },
    {
        "name": "bossa_antigua.mp3",
        "url": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Bossa%20Antigua.mp3"
    }
]

def download_default_bgms(bgm_dir):
    """デフォルトの高品質BGMをダウンロードしてbgm_dirに保存する"""
    os.makedirs(bgm_dir, exist_ok=True)
    
    # 以前の古いチープなループ音源(loop1~4)があればクリーンアップ削除
    old_loops = ["loop1.mp3", "loop2.mp3", "loop3.mp3", "loop4.mp3"]
    for old_file in old_loops:
        old_path = os.path.join(bgm_dir, old_file)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
                print(f"古いBGM素材を削除しました: {old_file}")
            except Exception as e:
                print(f"古いBGM素材の削除に失敗しました: {e}")

    # 既に新BGMファイルがあるかチェック
    existing_files = [f for f in os.listdir(bgm_dir) if f.endswith(".mp3")]
    if len(existing_files) >= len(DEFAULT_BGM_LIST):
        print(f"BGMフォルダ内に既に {len(existing_files)} 個の高品質ファイルが存在するため、ダウンロードをスキップします。")
        return
        
    print("朝のラジオにふさわしい高品質なアコースティックBGMをダウンロードしています...")
    for bgm_info in DEFAULT_BGM_LIST:
        dest_path = os.path.join(bgm_dir, bgm_info["name"])
        if os.path.exists(dest_path):
            continue
        url = bgm_info["url"]
        print(f" -> {bgm_info['name']} をダウンロード中...")
        
        # 最大3回のリトライ処理
        download_success = False
        for attempt in range(1, 4):
            try:
                req = urllib.request.Request(
                    url, 
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                )
                with urllib.request.urlopen(req, timeout=15) as response, open(dest_path, 'wb') as out_file:
                    shutil.copyfileobj(response, out_file)
                print(f"    成功: {bgm_info['name']}")
                download_success = True
                break
            except Exception as e:
                print(f"    [Attempt {attempt}/3 Warning] {bgm_info['name']} のダウンロードに失敗: {e}")
                time.sleep(2)
        
        if not download_success:
            print(f"    [Error] {bgm_info['name']} の取得をスキップして続行します。")
            
        time.sleep(1)

def mix_bgm(speech_mp3_path, output_mp3_path):
    """
    合成された音声ファイルに、ランダムに選択したBGMを重ね合わせる。
    BGMの有効無効、音量は環境変数から取得。
    """
    enable_bgm = os.getenv("ENABLE_BGM", "true").lower() == "true"
    if not enable_bgm:
        print("BGM機能は無効に設定されています。ミキシングをスキップします。")
        shutil.copy2(speech_mp3_path, output_mp3_path)
        return True

    # bgmフォルダのパスを設定（スクリプトと同じディレクトリ）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    bgm_dir = os.path.join(script_dir, "bgm")
    
    # BGMのダウンロード
    download_default_bgms(bgm_dir)
    
    # BGMファイルのリストを取得
    if not os.path.exists(bgm_dir):
        print("[Warning] bgmフォルダが存在しません。ミキシングをスキップします。")
        shutil.copy2(speech_mp3_path, output_mp3_path)
        return False
        
    bgm_files = [os.path.join(bgm_dir, f) for f in os.listdir(bgm_dir) if f.endswith((".mp3", ".ogg", ".wav"))]
    if not bgm_files:
        print("[Warning] bgmフォルダに音楽ファイルが見つかりません。ミキシングをスキップします。")
        shutil.copy2(speech_mp3_path, output_mp3_path)
        return False
        
    # ランダムにBGMを選択
    chosen_bgm = random.choice(bgm_files)
    print(f"使用するBGM: {os.path.basename(chosen_bgm)}")
    
    try:
        # 1. 音声（台本）の長さを取得
        audio = MP3(speech_mp3_path)
        duration = audio.info.length
        print(f"合成音声の長さ: {duration:.2f} 秒")
        
        # 2. フェードイン・フェードアウトの計算
        fade_in_duration = 2.0
        fade_out_duration = 3.0
        fade_out_start = max(0.0, duration - fade_out_duration)
        
        # 本格アコースティックBGMに適したバランス音量 (デフォルト 0.30)
        bgm_volume = float(os.getenv("BGM_VOLUME", "0.30"))
        
        # 3. ffmpegによるミキシング
        # loudnormで楽曲ごとの音圧差を均一化
        # volumeで指定音量にスケール
        # afadeでbgmを自然にフェードイン＆フェードアウト
        # amixのduration=firstで最初のインプット（speech）の長さに合わせる
        cmd = [
            "ffmpeg", "-y",
            "-i", speech_mp3_path,
            "-stream_loop", "-1",
            "-i", chosen_bgm,
            "-filter_complex", 
            f"[1:a]loudnorm=I=-20:LRA=11:TP=-1.5,volume={bgm_volume},"
            f"afade=t=in:st=0:d={fade_in_duration:.2f},"
            f"afade=t=out:st={fade_out_start:.2f}:d={fade_out_duration:.2f}[bgm_faded];"
            f"[0:a][bgm_faded]amix=inputs=2:duration=first:dropout_transition=3:normalize=0[a]",
            "-map", "[a]",
            "-c:a", "libmp3lame",
            "-q:a", "4",
            output_mp3_path
        ]
        
        print("FFmpegによるミキシング処理を実行中...")
        # stdout/stderrはデバッグ用にキャプチャするが、詳細なログ出力のためにバックグラウンドでは走らせない
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        if result.returncode == 0:
            print(f"BGMミキシングが正常に完了しました: {output_mp3_path}")
            return True
        else:
            print(f"[Error] FFmpeg mixing failed (exit code {result.returncode}):")
            print(result.stderr)
            print("フォールバックとしてBGM無しの音声を出力します。")
            shutil.copy2(speech_mp3_path, output_mp3_path)
            return False
            
    except Exception as e:
        print(f"[Error] Failed to mix BGM: {e}")
        print("フォールバックとしてBGM無しの音声を出力します。")
        shutil.copy2(speech_mp3_path, output_mp3_path)
        return False

def apply_pronunciation_dict(text):
    """テキスト内の特定の英単語を、Edge TTSが正しく読めるようにカタカナ等に置換する"""
    if not text:
        return ""
        
    # 置換用辞書 (大文字小文字を区別せずマッチさせるため、正規表現を作成)
    replacements = {
        r'(?i)(?<![A-Za-z])stateless(?![A-Za-z])': 'ステートレス',
        r'(?i)(?<![A-Za-z])idempotency(?![A-Za-z])': 'べき等性',
        r'冪等性': 'べき等性',
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

async def generate_line_audio(text, voice, output_path, speech_rate="+10%"):
    """1行のセリフの音声を生成"""
    sanitized_text = text.strip()
    if not sanitized_text:
        return False
        
    # 発音辞書の適用 (Claude などの誤読対策)
    sanitized_text = apply_pronunciation_dict(sanitized_text)
        
    # 文末に句読点を必ず付与することで、合成音声の末尾に自然な「間（余韻）」を作らせる
    if not sanitized_text.endswith(("。", "！", "？", "!", "?")):
        sanitized_text += "。"
        
    if speech_rate not in {"+10%", "0%"}:
        raise ValueError("speech_rate must be +10% or 0%")
    communicate = edge_tts.Communicate(sanitized_text, voice, rate=speech_rate)
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


def concatenate_mp3_files(input_paths, output_path):
    """Concatenate MP3 segments through FFmpeg instead of raw byte appends."""
    if not input_paths:
        return False
    list_path = os.path.join(os.path.dirname(output_path), "concat-list.txt")
    with open(list_path, "w", encoding="utf-8") as handle:
        for path in input_paths:
            escaped = os.path.abspath(path).replace("'", "'\\''")
            handle.write(f"file '{escaped}'\n")
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-c", "copy", output_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(f"[Error] FFmpeg concat failed: {result.stderr[-1000:]}")
        return False
    return os.path.isfile(output_path) and os.path.getsize(output_path) > 0

async def synthesize_podcast(script_path, output_mp3_path, speech_rate="+10%"):
    """台本から音声ファイルを生成し、FFmpegで結合してポッドキャストMP3を出力"""
    parsed_lines = parse_script_file(script_path)
    if not parsed_lines:
        print("[Error] No valid script lines found to synthesize.")
        return False

    print(f"台本の解析完了: {len(parsed_lines)} 行のセリフが見つかりました。")
    with tempfile.TemporaryDirectory(prefix="podcast-audio-") as temp_dir:
        try:
            temp_files = []
            print("音声の個別生成を開始します...")
            for idx, (speaker, text) in enumerate(parsed_lines):
                voice = VOICE_MAP.get(speaker)
                if not voice:
                    print(f"[Warning] Unknown speaker '{speaker}', skipping.")
                    continue

                temp_line_path = os.path.join(temp_dir, f"line_{idx}.mp3")
                print(f" -> [{speaker}] を生成中... ({idx+1}/{len(parsed_lines)})")
                success = await generate_line_audio(
                    text, voice, temp_line_path, speech_rate=speech_rate
                )
                if success:
                    temp_files.append(temp_line_path)

            print("\n音声ファイルの結合処理を行っています...")
            temp_combined_path = os.path.join(temp_dir, "speech-combined.mp3")
            if not concatenate_mp3_files(temp_files, temp_combined_path):
                return False

            print("\nBGMミキシング処理を開始します...")
            mix_success = mix_bgm(temp_combined_path, output_mp3_path)

            if mix_success:
                print(f"ポッドキャスト音声の生成が完了しました: {output_mp3_path}")
                return True
            print("[Warning] BGMミキシング処理で問題が発生しましたが、音声自体は出力されました。")
            return True
        except Exception as e:
            print(f"[Error] Audio synthesis failed in synthesize_podcast: {e}")
            return False

if __name__ == "__main__":
    script_dir = os.path.dirname(__file__)
    test_script_path = os.path.join(script_dir, "todays_script.txt")
    output_mp3 = os.path.join(script_dir, "todays_podcast.mp3")
    
    print("音声合成のテストを開始します。")
    asyncio.run(synthesize_podcast(test_script_path, output_mp3))
