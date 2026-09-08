"""Finalize one stale regression assertion and synchronize the v10 roadmap."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one occurrence, found {count}: {old!r}")
    file_path.write_text(text.replace(old, new), encoding="utf-8")


replace_once(
    "tests/test_episode_formats.py",
    'self.assertIn("手順や今日のアクションは本当に役立つ場合だけ", instruction)',
    'self.assertIn("仕様、対応条件、具体的操作は入力ソースに根拠がある範囲だけ", instruction)',
)

replace_once(
    "docs/developer/FORMATS_V10_ROADMAP.md",
    "状態: **設計確定・実装前**",
    "状態: **実装完了・回帰CI確認中（実モデルcanaryは未実施）**",
)
replace_once(
    "docs/developer/FORMATS_V10_ROADMAP.md",
    "台本は**約1,600〜1,650文字中心**を初期値とする。",
    "台本は**1,550〜1,750文字を生成中心帯**とする。",
)
replace_once(
    "docs/developer/FORMATS_V10_ROADMAP.md",
    "- `210〜900秒`: normal\n- `> 900秒`: long-duration warning、公開継続\n- `> 1200秒`: extreme durationとしてHard Stop候補",
    "- `210〜600秒`: normal\n- `> 600秒`: long-duration warning、公開継続\n- `> 1200秒`: extreme durationとしてHard Stop",
)

print("formats-v10 final regression and roadmap patch applied")
