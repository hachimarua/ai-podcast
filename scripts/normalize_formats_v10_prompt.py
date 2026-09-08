"""Normalize one split Python string literal before the one-shot v10 migration."""
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "script_generator.py"
text = path.read_text(encoding="utf-8")
old = '''            "1テーマだけを扱い、今週なぜ重要なのか、仕組み、バイブコーダーの"
            "個人開発でどう関係するか、使わない条件や注意点まで自然な会話で深掘りしてください。"
            "手順や期待結果は公式根拠があり、実際に役立つ場合だけ含めてください。\\n"
'''
new = '''            "1テーマだけを扱い、今週なぜ重要なのか、仕組み、バイブコーダーの個人開発でどう関係するか、使わない条件や注意点まで自然な会話で深掘りしてください。手順や期待結果は公式根拠があり、実際に役立つ場合だけ含めてください。\\n"
'''
count = text.count(old)
if count != 1:
    raise RuntimeError(f"expected one split weekly prompt literal, found {count}")
path.write_text(text.replace(old, new), encoding="utf-8")
print("weekly prompt literal normalized")
