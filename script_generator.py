import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

# 環境変数の読み込み
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def get_gemini_client():
    if not GEMINI_API_KEY or "YOUR_GEMINI" in GEMINI_API_KEY:
        print("[Warning] GEMINI_API_KEY is not set. Using dummy client for preview.")
        return None
    return genai.Client(api_key=GEMINI_API_KEY)

# ラジオ台本生成用システム命令
SYSTEM_INSTRUCTION = """
あなたは、毎朝の通勤時間に聴く「5分間のAI学習カーラジオ」のプロの構成作家です。
提供された「Notionの過去の学習日記」および「関連する最新のAIニュース」のみを情報源として使用し、
車内で聞き流すのに最適な、日本語の対話型ラジオ台本を作成してください。

【出演キャラクター】
- ケンジ (Kenji): ナビゲーター。聞き手役であり、少し親しみやすく、私たちの日常や学習の目線で質問する。
- アミ (Ami): AI解説者。専門知識を持ち、最新ニュースを解説する。親切で聞き取りやすいトーンで話す。

【台本の構成ルール】
1. オープニング（挨拶と、今日復習する学習日記の日付やその時のキーワードの紹介）
2. ニュース解説と復習（今日収集された最新ニュースと、過去の学習日記のメモ内容を紐解いて、関連性を復習する）
3. エンディング（まとめと、学習へのモチベーションを促す挨拶）
4. トータルで「朝の5分」程度（文字数で約1000〜1200文字程度）のボリュームに収めてください。

【ハルシネーション対策（極めて重要）】
- あなたは提供された「最新ニュース」および「Notionの学習メモ」のテキスト情報に**100%忠実**でなければなりません。
- テキストに記載されていない新しい事実、未確認の仕様、開発会社の推測、あるいは他社製品の憶測を**絶対に付け加えないでください**。
- 情報が不足している場合は、それを想像で補わず、淡々と与えられた事実の範囲内で解説してください。

【出力フォーマット】
音声合成（TTS）にかけるため、余計な説明文や解説は一切出力せず、以下のキャラクターの台詞のみの形式で出力してください。
ケンジ：[セリフ]
アミ：[セリフ]
ケンジ：[セリフ]
"""

def build_prompt_content(selected_terms, matched_news, general_news):
    """プロンプトのコンテキスト（一次情報）を組み立てる"""
    content = "## 一次情報 (ソーステキスト)\n\n"
    
    # Notionの日記メモ（本文含む）の追加
    content += "### 今日の復習対象となるNotionの学習日記メモ:\n"
    for term in selected_terms:
        content += f"- 日付/タイトル: {term['name']}\n"
        content += f"  学習メモ本文:\n{term.get('content', '（中身なし）')}\n"
        content += "-" * 30 + "\n"
    content += "\n"
    
    # 関連ニュースの追加
    content += "### 関連する最新のAIニュース:\n"
    if matched_news:
        for i, news in enumerate(matched_news, 1):
            content += f"[ニュース {i}] Source: {news['source']}\n"
            content += f"Title: {news['title']}\n"
            content += f"URL: {news['link']}\n"
            content += f"Content:\n{news['content'][:2000]}\n"
            content += f"Matched Notion Words: {news.get('matched_words', [])}\n"
            content += "-" * 30 + "\n"
    else:
        content += "(過去の学習メモに直接関連するニュースはありませんでした)\n\n"
        
    # 一般ニュースの追加
    content += "### その他の最新AIニュース:\n"
    for i, news in enumerate(general_news[:3], 1):
        content += f"[一般ニュース {i}] Source: {news['source']}\n"
        content += f"Title: {news['title']}\n"
        content += f"Content:\n{news['content'][:1500]}\n"
        content += "-" * 30 + "\n"
        
    content += "\n## 指示:\n"
    content += "上記の「今日の復習対象となるNotionの学習日記」と「最新ニュース」を自然に融合させ、朝の5分間ラジオ台本を日本語で作成してください。\n"
    content += "過去にユーザーが学んだ内容（学習メモ本文に記載されている内容）をおさらいしながら、アミが分かりやすく最新情報と結びつけて解説してください。"
    
    return content

def generate_radio_script(selected_terms, matched_news, general_news, model_name="gemini-2.5-flash"):
    """Gemini APIを使用してラジオ台本を生成"""
    client = get_gemini_client()
    
    if not client:
        print("[Mock] Generating preview script...")
        preview = "ケンジ：皆さん、おはようございます！ケンジです。朝の5分AI学習ラジオの時間です。\n"
        preview += "アミ：おはようございます、AI解説者のアミです。今朝の復習テーマは「RAG」と「MCP」ですね。\n"
        preview += "ケンジ：RAGは検索拡張生成、MCPは最近話題のモデルコンテキストプロトコルだよね。これらに関する最新ニュースはある？\n"
        preview += "アミ：はい、ホワイトリストのソースから、RAGの精度向上に関する最新技術ニュースと、MCP対応ツールが拡大しているニュースをピックアップしました。\n"
        preview += "ケンジ：なるほど！過去に僕たちが学んだ単語が、最新のニュースで実際にこうやって使われているのを聞くと、知識が繋がる感じがするね。\n"
        preview += "アミ：そうですね。こうして繰り返し最新の動向と紐づけて復習することで、知識が脳に定着していきます。それでは、今日も一日、AIの学びを楽しんでいきましょう！\n"
        preview += "ケンジ：いってらっしゃい！"
        return preview
        
    prompt = build_prompt_content(selected_terms, matched_news, general_news)
    
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.3,
            )
        )
        return response.text
    except Exception as e:
        print(f"[Error] Failed to generate script via Gemini: {e}")
        return None

if __name__ == "__main__":
    print("Script Generator Test Running...")
    dummy_terms = [
        {"name": "20260511", "content": "RAG (Retrieval-Augmented Generation) について学習。外部データを検索し、LLMに渡して回答精度を高める。"}
    ]
    dummy_matched = [
        {
            "source": "TechCrunch AI",
            "title": "New retrieval tech improves RAG accuracy",
            "link": "https://example.com/rag",
            "content": "A new retrieval technique has been developed that significantly enhances the precision of RAG systems by sorting chunks better.",
            "matched_words": ["RAG"]
        }
    ]
    dummy_general = []
    
    script = generate_radio_script(dummy_terms, dummy_matched, dummy_general)
    print("\n--- Generated Script Preview ---")
    print(script)
    print("--------------------------------")
