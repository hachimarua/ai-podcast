"""台本の言い回しの傾向を数える（読み取り専用。配信パイプラインからは呼ばない）。

2026-10-09 に「切り分けて考えます」「〜とは言っていません」が続く回があり、
プロンプトを整理した。その後の回で癖が減ったかを見るための計測道具。
ゲートではないので、数値で配信を止めない。

    ./venv/bin/python scripts/tone_metrics.py --last 14
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "episode_scripts"

PATTERNS = {
    "区別": r"切り分け|分けて(考え|見|判断|記録|扱|捉え|整理)|区別|混同|混ぜ(ない|ず)|(は|とは)別(です|の話|物|もの|問題)|同じ[^。]{0,12}扱わない|と見なせない",
    "否定の注釈": r"とは限りません|わけではありません|ではありません|言えません|断定(は|でき)|示していません|言っていません|分かりません|ではない|とは言えない",
    "前向き": r"楽しみ|期待|気になり|面白|いいですね|便利になり|広がり|注目|わくわく|ワクワク",
}


def measure(text: str) -> dict:
    lines = [line.split("：", 1)[1] for line in text.splitlines() if "：" in line]
    counts = {name: sum(1 for line in lines if re.search(pattern, line)) for name, pattern in PATTERNS.items()}
    return {"lines": len(lines), **counts}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--last", type=int, default=14, help="新しい順に何本見るか")
    args = parser.parse_args()
    files = sorted(SCRIPTS_DIR.glob("podcast_*.txt"))[-args.last:]
    print(f"{'回':<10} {'行':>3} " + " ".join(f"{name:>6}" for name in PATTERNS))
    for path in files:
        result = measure(path.read_text(encoding="utf-8"))
        print(f"{path.stem[8:16]:<10} {result['lines']:>3} " + " ".join(f"{result[name]:>6}" for name in PATTERNS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
