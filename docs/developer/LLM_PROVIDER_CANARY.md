# LLM プロバイダ カナリア（Gemini / OpenAI 比較）

最終更新: 2026-09-07

`scripts/llm_canary.py` は、**本番と同じプロンプト**を Gemini と OpenAI へ同時に投げて挙動を並べる試験回路。
配信パイプラインからは完全に独立している（`main.py` からimportされず、エピソード公開・manifest・RSS の書き込みなし、Notion は読むだけ）。
出力先の `comparisons/` は `.gitignore` 済み。

## なぜ作ったか

OpenAI API の Data Sharing ON Project に付与される無料日次枠を、**公開情報しか扱わない AI Podcast News で試す**ため。
本番導入を前提にせず、まず「キーが生きているか」「usage がどう計上されるか」「出力がどう違うか」を観察することが目的。

## 使い方

```bash
cd "/Users/sakiya/Documents/Antigravity 2.0/AI news knowledge learning system"

# 1. キーから見えるモデル一覧（生成しないのでトークン消費ゼロ）
./venv/bin/python scripts/llm_canary.py --list-models

# 2. 単純なカナリア: 学習トピック1つを両方に解説させる
./venv/bin/python scripts/llm_canary.py --topic "冪等性" --openai-model gpt-5.5

# 3. 本番と同じ入力: 実ニュース -> ラジオ台本（推奨）
./venv/bin/python scripts/llm_canary.py --openai-model gpt-5.5

# 同日中に別題材で回す（先頭N件を捨ててから選ぶ）
./venv/bin/python scripts/llm_canary.py --news-offset 3 --openai-model gpt-5.5

# Notion の学習メモを使わず公開ニュースだけで走らせる
./venv/bin/python scripts/llm_canary.py --no-notion --openai-model gpt-5.5
```

必要な環境変数は `.env` の `OPENAI_API_KEY` と `GEMINI_API_KEY`。
OpenAI 側は SDK を使わず素の HTTP（`/v1/responses` を試し、失敗したら `/v1/chat/completions`）。
usage の生ペイロードをそのまま見たいのと、依存を増やさないため。

出力は `comparisons/canary_<timestamp>/` に
`input_system.txt` / `input_prompt.txt` / `output_gemini.txt` / `output_openai.txt` / `report.json`。

## 2026-09-07 の測定結果（n=3）

同一プロンプト・同一日・題材3種。OpenAI は `gpt-5.5`、Gemini は `gemini-3.7-flash`（`thinking_level="high"`）。

| 3回平均 | Gemini 3.7 Flash | OpenAI gpt-5.5 |
|---|---|---|
| 台本文字数（目標 1,200〜1,400） | **1,367字** | 1,747字 |
| 総トークン | 8,580 | **6,415** |
| うち reasoning | 4,411 | **796** |
| レイテンシ | **16.4s** | 24.9s |
| 本番ゲート（文字数・定型・反復・役割） | 3/3 全通過 | 3/3 全通過 |

### 分かったこと

- **無料日次枠は実際に機能する。** 3回投げて Platform の Usage は $0、トークン量とリクエスト回数も一致。
- **枠は制約にならない。** 1エピソード約6,400トークン。250,000/day なら1日39本ぶん。毎日1本の運用では消費率 2.5%。
- **日本語のトークン効率は Gemini が約25%上**（1.86字/token vs 1.48字/token）。
  ただし Gemini は `thinking_level="high"` で reasoning を平均4,411焚くため、**合計では OpenAI の方が少ない**。
- **reasoning は output に加算される**が、usage に内訳が出るので事後に正確に測れる。
- OpenAI の usage には `cached_tokens` / `cache_write_tokens` が含まれる。
  system instruction は毎日ほぼ同一（5,178字）なので、プロンプトキャッシュが効けばさらに下がる余地がある。

### 出力の性格

- **Gemini** — 事実の確認範囲を丁寧に区切る。「記事のテキストからは確認できません」を明示的に繰り返す。
  文字数が目標のど真ん中に収まる。堅実だが実務への落とし込みは薄め。
- **OpenAI** — ニュース2件を接続し、抽象化を挟んで具体的な行動（記録の型など）まで持っていく。
  情報密度と実用性は明確に上。ただし話が広がる分、目標文字数を超えやすい（平均1,747字 / ハード上限2,000字）。

### 積み残し: 固有名詞のカタカナ化

`SYSTEM_INSTRUCTION` は英語固有名詞をカタカナ表記へ統一するよう指示しているが、**両モデルとも完全には守らない**。
`audio_generator.apply_pronunciation_dict()` が TTS 直前に置換するので実害は減るが、辞書に無い語は素通りする。

| 読み上げ本文に残るラテン文字（AI除く・3回平均） | 辞書適用前 | 辞書適用後 |
|---|---|---|
| Gemini | 3.7箇所 | 2.7箇所 |
| OpenAI | 11.7箇所 | 6.0箇所 |

残る語の性質が違う。

- Gemini の取りこぼしは `Google` `Google AI Blog` `Flash` という**定番語** → 辞書に足せば恒久的に解決する
- OpenAI の取りこぼしはそれに加えて `Fable 5.1` `Mythos 5.1` `Flash Cyber` という**発表されたばかりの製品名**
  → 静的辞書では原理的に追いつけない

これは **OpenAI 固有の欠陥ではなく、現行の Gemini 運用にも存在する穴**。
自前 TTS へ移っても解決しない（読み間違いではなく「その語を知らなかった」問題）ため、
対策は辞書の拡充と、辞書未知のラテン文字を検出する決定論ゲートの追加が筋。

## 現時点の判断

台本生成は OpenAI でも本番投入可能な水準（ゲート全通過）。
ただし**いま置き換える理由はない**。Gemini で安定稼働しているため、これは試験回路として維持し、
他のトライアルの結果を見てから改めて検討する。
