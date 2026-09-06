#!/usr/bin/env python3
"""Run one podcast script through Gemini and OpenAI side by side, and report what came back.

This is a test circuit, not a step of the pipeline.  Nothing here is imported by
main.py, no episode is published, no manifest or RSS is written, and Notion is
only ever read.  Output goes to comparisons/, which is gitignored.

The point is to watch behaviour, not to decide anything: which models the key can
actually see, what the usage payload looks like, how the two outputs differ on the
same prompt.

    python scripts/llm_canary.py --list-models      # what the OpenAI key can see
    python scripts/llm_canary.py --topic "冪等性"     # a plain learning topic, both providers
    python scripts/llm_canary.py                    # the real thing: live news -> radio script

No SDK is used on the OpenAI side.  Plain HTTP keeps the raw usage payload visible,
which is most of what we want to look at, and adds no dependency.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

OPENAI_BASE = "https://api.openai.com/v1"
TIMEOUT = (10, 180)


class CanaryError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# secret hygiene
# --------------------------------------------------------------------------

def redact(text: str, *secrets: str | None) -> str:
    """Remove key material from anything that might be printed or written to disk."""
    out = str(text)
    for secret in secrets:
        if secret and len(secret) > 8:
            out = out.replace(secret, "***REDACTED***")
    return out


def require_key(name: str) -> str:
    value = os.getenv(name, "")
    if not value or value.startswith("YOUR_"):
        raise CanaryError(
            f"{name} が未設定です（.env の値がプレースホルダのままの可能性があります）"
        )
    return value


# --------------------------------------------------------------------------
# OpenAI
# --------------------------------------------------------------------------

def openai_list_models(api_key: str) -> list[dict]:
    response = requests.get(
        f"{OPENAI_BASE}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        raise CanaryError(
            f"モデル一覧を取得できませんでした (HTTP {response.status_code}): "
            + redact(response.text[:400], api_key)
        )
    return response.json().get("data", [])


def _openai_text_from_responses(payload: dict) -> str:
    """Pull the assistant text out of a Responses API payload."""
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    chunks = []
    for item in payload.get("output", []):
        for part in item.get("content", []) or []:
            if part.get("type") in {"output_text", "text"} and part.get("text"):
                chunks.append(part["text"])
    return "\n".join(chunks)


def openai_generate(api_key: str, model: str, system: str, prompt: str,
                    max_output_tokens: int) -> dict:
    """Try the Responses API, fall back to Chat Completions if it is not available."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    started = time.monotonic()
    response = requests.post(
        f"{OPENAI_BASE}/responses",
        headers=headers,
        json={
            "model": model,
            "instructions": system,
            "input": prompt,
            "max_output_tokens": max_output_tokens,
        },
        timeout=TIMEOUT,
    )
    if response.status_code == 200:
        body = response.json()
        usage = body.get("usage", {})
        return {
            "endpoint": "/v1/responses",
            "text": _openai_text_from_responses(body),
            "latency_ms": int((time.monotonic() - started) * 1000),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "reasoning_tokens": (usage.get("output_tokens_details") or {}).get("reasoning_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "raw_usage": usage,
            "status": body.get("status"),
        }

    first_error = f"HTTP {response.status_code}: {redact(response.text[:400], api_key)}"

    started = time.monotonic()
    response = requests.post(
        f"{OPENAI_BASE}/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_completion_tokens": max_output_tokens,
        },
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        raise CanaryError(
            "OpenAIの2経路とも失敗しました。\n"
            f"  /v1/responses        -> {first_error}\n"
            f"  /v1/chat/completions -> HTTP {response.status_code}: "
            + redact(response.text[:400], api_key)
        )
    body = response.json()
    usage = body.get("usage", {})
    return {
        "endpoint": "/v1/chat/completions",
        "text": (body["choices"][0]["message"].get("content") or ""),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "raw_usage": usage,
        "status": body["choices"][0].get("finish_reason"),
        "responses_endpoint_error": first_error,
    }


# --------------------------------------------------------------------------
# Gemini
# --------------------------------------------------------------------------

def gemini_generate(api_key: str, model: str, system: str, prompt: str) -> dict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    started = time.monotonic()
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            thinking_config=types.ThinkingConfig(thinking_level="high"),
        ),
    )
    latency_ms = int((time.monotonic() - started) * 1000)
    usage = getattr(response, "usage_metadata", None)

    def field(*names):
        for name in names:
            value = getattr(usage, name, None)
            if value is not None:
                return value
        return None

    return {
        "endpoint": "google-genai SDK",
        "text": response.text or "",
        "latency_ms": latency_ms,
        "input_tokens": field("prompt_token_count"),
        "output_tokens": field("candidates_token_count"),
        "reasoning_tokens": field("thoughts_token_count"),
        "total_tokens": field("total_token_count"),
        "raw_usage": (usage.model_dump() if hasattr(usage, "model_dump") else str(usage)),
        "status": "ok",
    }


# --------------------------------------------------------------------------
# prompts
# --------------------------------------------------------------------------

def build_topic_prompt(topic: str) -> tuple[str, str]:
    """A deliberately plain canary: one learning topic, no pipeline machinery."""
    system = (
        "あなたは非エンジニアの個人開発者に技術用語を教える解説者です。"
        "確認できる事実だけを述べ、推測で補わないでください。日本語で答えます。"
    )
    prompt = (
        f"「{topic}」について、次の3点を順に説明してください。\n"
        "1. ひとことで言うと何か\n"
        "2. 仕組みと、なぜそれが要るのか\n"
        "3. 個人開発でどう関係するか、使わない方がよい条件\n"
        "全体で600〜800文字。箇条書きを使いすぎず、地の文で書いてください。"
    )
    return system, prompt


def build_pipeline_prompt(use_notion: bool, news_offset: int = 0) -> tuple[str, str, dict]:
    """Reuse the real production prompt builders so the A/B is not a toy.

    ``news_offset`` drops the first N candidates before selection, so repeated
    runs on the same day can be given genuinely different source material.
    """
    from episode_formats import load_episode_formats
    from news_collector import collect_latest_news, match_news_with_words, select_news_for_broadcast
    from script_generator import build_prompt_content, build_system_instruction

    spec = load_episode_formats().formats["daily"]
    role_plan = {"navigator": "ケンジ", "explainer": "アミ"}

    print("  ニュースを取得中（RSS・APIキー不要）...", flush=True)
    news = collect_latest_news()
    if news_offset:
        news = news[news_offset:]
    if not news:
        raise CanaryError("ニュースを取得できませんでした")

    terms = []
    if use_notion:
        try:
            from notion_helper import select_terms_for_review

            print("  Notionから復習用語を1件取得中...", flush=True)
            terms = select_terms_for_review(count=spec.max_review_terms)
        except Exception as exc:
            print(f"  [注意] Notion読み込みをスキップ: {type(exc).__name__}", flush=True)

    matched, unmatched = match_news_with_words(news, terms)
    broadcast_news, _ = select_news_for_broadcast(
        matched, unmatched, [], max_items=spec.max_news_items
    )
    if not broadcast_news:
        raise CanaryError("採用できるニュースがありませんでした")

    selected_matched = [n for n in broadcast_news if n["_matched_for_review"]]
    selected_general = [n for n in broadcast_news if not n["_matched_for_review"]]

    system = build_system_instruction("daily", spec, role_plan)
    prompt = build_prompt_content(
        terms, selected_matched, selected_general,
        episode_format="daily", spec=spec, role_plan=role_plan,
    )
    context = {
        "news": [{"source": n["source"], "title": n["title"], "url": n.get("link", "")}
                 for n in broadcast_news],
        "notion_terms": [t.get("name") for t in terms],
        "target_characters": [spec.prompt_character_min, spec.prompt_character_max],
    }
    return system, prompt, context


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def evaluate_script(text: str) -> dict:
    """Score one generated script with the production gates plus TTS readability.

    The Latin-script count is the part the deterministic gates do not cover today:
    the system instruction requires English proper nouns to be written in katakana
    so the Japanese TTS voice reads them cleanly, and nothing enforces it.
    """
    import re

    from episode_formats import EpisodeFormatError, load_episode_formats, validate_script_length
    from script_generator import (
        split_generated_script_output,
        validate_dialogue_roles,
        validate_dialogue_style,
        validate_script_repetition,
    )

    spec = load_episode_formats().formats["daily"]
    role_plan = {"navigator": "ケンジ", "explainer": "アミ"}
    script, public_title = split_generated_script_output(text)

    out: dict = {"public_title": public_title}

    try:
        out["length"] = validate_script_length(script, spec)
    except EpisodeFormatError as exc:
        out["length"] = {"passed": False, "error": str(exc), "character_count": len(script)}

    out["style"] = validate_dialogue_style(script, enforce=False)
    out["repetition"] = validate_script_repetition(script, enforce=False)
    out["roles"] = validate_dialogue_roles(script, role_plan, enforce=False)

    # Spoken text only: the display title is never read aloud.
    spoken = "\n".join(
        re.sub(r"^(?:ケンジ|アミ)\s*[:：]\s*", "", line.strip())
        for line in script.splitlines()
        if re.match(r"^(?:ケンジ|アミ)\s*[:：]", line.strip())
    )
    found = [m.strip() for m in re.findall(r"[A-Za-z][A-Za-z0-9.\- ]{1,30}", spoken)]
    found = [m for m in found if len(m) > 1]
    # "AI" is idiomatic in written Japanese and reads correctly; everything else
    # is a proper noun the instruction asks to be written in katakana.
    unconverted = [m for m in found if m != "AI"]
    out["tts_readability"] = {
        "latin_total": len(found),
        "latin_excluding_ai": len(unconverted),
        "unconverted_terms": sorted(set(unconverted)),
        "passed": not unconverted,
    }
    return out


def summarise(label: str, result: dict | None, error: str | None) -> str:
    if error:
        return f"  {label:<8} 失敗: {error.splitlines()[0]}"
    chars = len(result["text"])
    return (
        f"  {label:<8} {chars:>5}字  "
        f"in {str(result['input_tokens'] or '?'):>6} / "
        f"out {str(result['output_tokens'] or '?'):>5} "
        f"(reasoning {result['reasoning_tokens'] if result['reasoning_tokens'] is not None else '-'})  "
        f"total {str(result['total_tokens'] or '?'):>6}  "
        f"{result['latency_ms'] / 1000:.1f}s  [{result['endpoint']}]"
    )


def main() -> int:
    load_dotenv(WORKSPACE / ".env")

    parser = argparse.ArgumentParser(description="Gemini と OpenAI を同じ入力で並走させる試験回路")
    parser.add_argument("--list-models", action="store_true",
                        help="OpenAIキーで見えるモデル一覧を表示して終了する")
    parser.add_argument("--topic", help="単純なカナリア: この学習トピックを両方に解説させる")
    parser.add_argument("--openai-model", default=os.getenv("OPENAI_CANARY_MODEL"),
                        help="使用するOpenAIモデル（未指定なら OPENAI_CANARY_MODEL）")
    parser.add_argument("--gemini-model", default=os.getenv("GEMINI_MODEL_NAME", "gemini-3.7-flash"))
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--news-offset", type=int, default=0,
                        help="ニュース候補の先頭N件を捨ててから選ぶ。同日中に別題材で回すため")
    parser.add_argument("--no-notion", action="store_true",
                        help="Notionの学習メモを使わず、公開ニュースだけで走らせる")
    parser.add_argument("--out-dir", default=str(WORKSPACE / "comparisons"))
    args = parser.parse_args()

    try:
        openai_key = require_key("OPENAI_API_KEY")
    except CanaryError as exc:
        print(f"[停止] {exc}", file=sys.stderr)
        return 1

    if args.list_models:
        models = openai_list_models(openai_key)
        print(f"\nOpenAIキーで見えるモデル: {len(models)} 件\n")
        for m in sorted(models, key=lambda x: x.get("id", "")):
            created = datetime.fromtimestamp(m.get("created", 0), timezone.utc).strftime("%Y-%m-%d")
            print(f"  {m.get('id',''):<44} owned_by={m.get('owned_by','?'):<18} created={created}")
        print("\n※ この一覧は「キーから見えるモデル」であって、無料日次枠の対象かどうかは")
        print("   Platform画面の eligibility 表示側で確認してください。")
        return 0

    if not args.openai_model:
        print("[停止] OpenAIモデルが未指定です。--openai-model か OPENAI_CANARY_MODEL を指定してください。",
              file=sys.stderr)
        print("       候補は  python scripts/llm_canary.py --list-models  で確認できます。", file=sys.stderr)
        return 1

    # ---- build the shared input -------------------------------------------
    if args.topic:
        mode = f"topic:{args.topic}"
        system, prompt = build_topic_prompt(args.topic)
        context = {"topic": args.topic}
    else:
        mode = f"pipeline:daily+{args.news_offset}"
        try:
            system, prompt, context = build_pipeline_prompt(
                use_notion=not args.no_notion, news_offset=args.news_offset
            )
        except CanaryError as exc:
            print(f"[停止] {exc}", file=sys.stderr)
            return 1

    print(f"\n=== カナリア実行 ({mode}) ===")
    print(f"  入力: system {len(system)}字 + prompt {len(prompt)}字 = {len(system) + len(prompt)}字")
    if context.get("news"):
        for n in context["news"]:
            print(f"    - [{n['source']}] {n['title'][:60]}")
    if context.get("notion_terms"):
        print(f"    復習用語: {context['notion_terms']}")
    print()

    results: dict[str, dict] = {}
    errors: dict[str, str] = {}

    print(f"  OpenAI ({args.openai_model}) 実行中...", flush=True)
    try:
        results["openai"] = openai_generate(
            openai_key, args.openai_model, system, prompt, args.max_output_tokens
        )
    except Exception as exc:
        errors["openai"] = redact(f"{type(exc).__name__}: {exc}", openai_key)

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_key or gemini_key.startswith("YOUR_"):
        errors["gemini"] = "GEMINI_API_KEY が未設定（.env がプレースホルダのまま）"
        print("  Gemini はキー未設定のためスキップします。", flush=True)
    else:
        print(f"  Gemini ({args.gemini_model}) 実行中...", flush=True)
        try:
            results["gemini"] = gemini_generate(gemini_key, args.gemini_model, system, prompt)
        except Exception as exc:
            errors["gemini"] = redact(f"{type(exc).__name__}: {exc}", gemini_key, openai_key)

    if not args.topic:
        for label, result in results.items():
            try:
                result["evaluation"] = evaluate_script(result["text"])
            except Exception as exc:
                result["evaluation"] = {"error": f"{type(exc).__name__}: {exc}"}

    print("\n--- 結果 ---")
    for label in ("gemini", "openai"):
        print(summarise(label, results.get(label), errors.get(label)))
        ev = (results.get(label) or {}).get("evaluation") or {}
        tts = ev.get("tts_readability")
        if tts:
            mark = "OK" if tts["passed"] else "NG"
            terms = "、".join(tts["unconverted_terms"]) or "なし"
            print(f"           カタカナ化 {mark}  未変換 {tts['latin_excluding_ai']}箇所: {terms}")
        gates = [
            ("文字数", (ev.get("length") or {}).get("passed")),
            ("定型", (ev.get("style") or {}).get("passed")),
            ("反復", (ev.get("repetition") or {}).get("passed")),
            ("役割", (ev.get("roles") or {}).get("passed")),
        ]
        if any(v is not None for _, v in gates):
            line = "  ".join(f"{n}{'OK' if v else 'NG'}" for n, v in gates)
            chars = (ev.get("length") or {}).get("character_count")
            print(f"           ゲート {line}   台本{chars}字")

    # ---- persist ----------------------------------------------------------
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) / f"canary_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "input_system.txt").write_text(system, encoding="utf-8")
    (out_dir / "input_prompt.txt").write_text(prompt, encoding="utf-8")
    for label, result in results.items():
        (out_dir / f"output_{label}.txt").write_text(result["text"], encoding="utf-8")

    report = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "context": context,
        "input_characters": {"system": len(system), "prompt": len(prompt)},
        "providers": {
            label: {k: v for k, v in result.items() if k != "text"}
            | {"output_characters": len(result["text"])}
            for label, result in results.items()
        },
        "errors": errors,
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"\n保存しました: {out_dir}")
    for label in ("gemini", "openai"):
        if label in results:
            print(f"  出力を読む:  open '{out_dir / f'output_{label}.txt'}'")
    return 0 if results else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CanaryError as exc:
        print(f"[停止] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
