#!/usr/bin/env python3
"""Run A/B canary test on 2026-10-02 episode source with GPT-5.6 Terra and GPT-6 Sol.

Uses identical source articles, Notion review term, and role assignment
(navigator=アミ, explainer=ケンジ) to determine whether the interview-like
structure (83% questions from navigator) was caused by GPT-6 Sol's strict role adherence
or the underlying prompt design, or their interaction.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from dotenv import load_dotenv
load_dotenv(WORKSPACE / ".env")

import news_collector
from episode_formats import load_episode_formats
from script_generator import (
    build_prompt_content,
    build_system_instruction,
    split_generated_script_output,
    validate_dialogue_roles,
    validate_dialogue_style,
    validate_script_repetition,
)
from scripts.llm_canary import openai_generate, redact, require_key, evaluate_script, summarise


OCT2_NEWS = [
    {
        "source": "AI Watch",
        "title": "Notion CEOが語る「コンテキストレイヤー」としてのAI戦略 - AI Watch",
        "link": "https://ai.watch.impress.co.jp/docs/news/2144987.html",
        "lane": "japan",
    },
    {
        "source": "TechCrunch AI",
        "title": "OpenAI cuts ties with 3 safety researchers, WSJ reports | TechCrunch",
        "link": "https://techcrunch.com/2026/10/01/openai-cuts-ties-with-three-safety-researchers-wsj-reports/",
        "lane": "world",
    },
    {
        "source": "Google AI Blog",
        "title": "Google Beam expands to new countries",
        "link": "https://blog.google/innovation-and-ai/technology/research/google-beam-expansion/",
        "lane": "world",
    },
]

OCT2_TERMS = [
    {
        "name": "Virtual Machine (VM)",
        "content": (
            "**Virtual Machine (VM)**: 仮想マシンの略称です。\n"
            "**一時VM**: 処理のために一時的に作成される仮想コンピューターを指します。\n"
            "**GitHub Actionsでの利用**: ワークフローの実行時にUbuntu環境として一時VMが用意されます。\n"
            "**特性**: 処理が完了すると基本的に破棄されるため、「使い捨てに近い一時的な仮想マシン」として機能します。"
        ),
    }
]

QUESTION_PATTERNS = [
    re.compile(r"[？\?]"),
    re.compile(r"(でしょうか|ですか|何でしょう|何ですか|ありますか|言えますか|見えますか|なりますか|しますか|ですかね|のかな|のでしょうか|のか)[。！!]?$"),
    re.compile(r"^(なぜ|何が|何を|どこが|どうして|どんな|どのように|いつ|誰が|どう)"),
]

def analyze_dialogue_structure(script_text: str, navigator: str, explainer: str) -> dict:
    lines = []
    for raw_line in script_text.splitlines():
        m = re.match(r"^(ケンジ|アミ)\s*[:：]\s*(.+)$", raw_line.strip())
        if m:
            lines.append((m.group(1), m.group(2).strip()))

    nav_lines = [l for l in lines if l[0] == navigator]
    exp_lines = [l for l in lines if l[0] == explainer]

    def is_question(text: str) -> bool:
        # Ignore opening/closing greetings
        if re.search(r"(おはよう|こんにちは|いってらっしゃい|また次回|お会いしましょう)", text):
            return False
        return any(p.search(text) for p in QUESTION_PATTERNS)

    nav_questions = [l for l in nav_lines if is_question(l[1])]
    exp_questions = [l for l in exp_lines if is_question(l[1])]

    return {
        "total_lines": len(lines),
        "navigator": navigator,
        "explainer": explainer,
        "nav_line_count": len(nav_lines),
        "nav_question_count": len(nav_questions),
        "nav_question_ratio": round(len(nav_questions) / len(nav_lines), 2) if nav_lines else 0,
        "nav_sample_questions": [l[1] for l in nav_questions],
        "exp_line_count": len(exp_lines),
        "exp_question_count": len(exp_questions),
        "exp_question_ratio": round(len(exp_questions) / len(exp_lines), 2) if exp_lines else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="2026-10-02素材でのTerra vs Sol A/Bカナリア")
    parser.add_argument("--models", default="gpt-5.6-terra,gpt-6-sol",
                        help="比較するモデル（カンマ区切り）")
    parser.add_argument("--max-output-tokens", type=int, default=16000)
    parser.add_argument("--out-dir", default=str(WORKSPACE / "comparisons"))
    args = parser.parse_args()

    openai_key = require_key("OPENAI_API_KEY")
    spec = load_episode_formats().formats["daily"]
    role_plan = {"navigator": "アミ", "explainer": "ケンジ"}

    print("=== 10/2 素材の準備 ===")
    print("  記事本文を取得中...")
    enriched_news = news_collector.enrich_news_with_article_text(OCT2_NEWS)
    for n in enriched_news:
        print(f"  - [{n['source']}] {n['title'][:50]} (本文: {len(n.get('article_text', ''))}字)")

    selected_matched = []
    selected_general = enriched_news

    system = build_system_instruction("daily", spec, role_plan)
    prompt = build_prompt_content(
        OCT2_TERMS, selected_matched, selected_general,
        episode_format="daily", spec=spec, role_plan=role_plan,
    )

    print(f"\nプロンプト作成完了: system {len(system)}字, prompt {len(prompt)}字")

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    results = {}
    errors = {}

    for model in models:
        label = f"openai:{model}"
        print(f"\n>>> 実行中: {model} ...", flush=True)
        try:
            res = openai_generate(openai_key, model, system, prompt, args.max_output_tokens)
            res["model"] = model
            res["evaluation"] = evaluate_script(res["text"], "daily")
            script, _ = split_generated_script_output(res["text"])
            res["dialogue_analysis"] = analyze_dialogue_structure(script, role_plan["navigator"], role_plan["explainer"])
            results[label] = res
            print(f"    完了: {len(res['text'])}字, {res['latency_ms']/1000:.1f}s, tokens: in={res['input_tokens']} out={res['output_tokens']} reasoning={res['reasoning_tokens']}")
        except Exception as exc:
            errors[label] = redact(f"{type(exc).__name__}: {exc}", openai_key)
            print(f"    [エラー] {errors[label]}")

    # 出力保存
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) / f"canary_1002_ab_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "input_system.txt").write_text(system, encoding="utf-8")
    (out_dir / "input_prompt.txt").write_text(prompt, encoding="utf-8")
    for label, result in results.items():
        fname = f"output_{label.replace(':', '_')}.txt"
        (out_dir / fname).write_text(result["text"], encoding="utf-8")

    report = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "input_characters": {"system": len(system), "prompt": len(prompt)},
        "role_plan": role_plan,
        "results": {
            k: {
                "model": v["model"],
                "latency_ms": v["latency_ms"],
                "input_tokens": v["input_tokens"],
                "output_tokens": v["output_tokens"],
                "reasoning_tokens": v["reasoning_tokens"],
                "total_tokens": v["total_tokens"],
                "char_count": len(v["text"]),
                "dialogue_analysis": v["dialogue_analysis"],
                "evaluation": v["evaluation"],
            }
            for k, v in results.items()
        },
        "errors": errors,
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("\n" + "=" * 60)
    print("=== A/B カナリア比較サマリー ===")
    print("=" * 60)

    for label in [f"openai:{m}" for m in models]:
        res = results.get(label)
        if not res:
            print(f"\n{label}: 失敗 ({errors.get(label)})")
            continue
        da = res["dialogue_analysis"]
        ev = res["evaluation"]
        length = ev.get("length", {})
        print(f"\n【{res['model']}】")
        print(f"  台本文字数: {length.get('character_count', len(res['text']))}字 (所要時間: {res['latency_ms']/1000:.1f}s)")
        print(f"  トータルトークン: {res['total_tokens']} (in={res['input_tokens']}, out={res['output_tokens']}, reasoning={res['reasoning_tokens']})")
        print(f"  ナビゲーター({da['navigator']}) 発話数: {da['nav_line_count']} / 質問発話数: {da['nav_question_count']} (質問率: {da['nav_question_ratio']*100:.0f}%)")
        print(f"  解説者({da['explainer']}) 発話数: {da['exp_line_count']} / 質問発話数: {da['exp_question_count']} (質問率: {da['exp_question_ratio']*100:.0f}%)")
        print(f"  ナビゲーターの質問サンプル:")
        for q in da["nav_sample_questions"][:5]:
            print(f"    - 「{q[:60]}」")
        if len(da["nav_sample_questions"]) > 5:
            print(f"    - ... 他 {len(da['nav_sample_questions']) - 5} 件")

    print(f"\n詳細ログと台本を保存しました:\n  {out_dir}")
    return 0


if __name__ == "__main__":
    main()
