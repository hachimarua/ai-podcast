# LLM プロバイダ カナリア（Gemini / OpenAI 比較）

最終更新: 2026-09-18

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

# 複数モデルを同じ入力で並走（Gemini 1本 + OpenAI N本）
./venv/bin/python scripts/llm_canary.py --openai-model gpt-5.6-terra,gpt-5.6-luna

# 日曜の AI実装ラボ形式
./venv/bin/python scripts/llm_canary.py --format lab --openai-model gpt-5.6-terra

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

## 2026-09-18 の測定結果（gpt-5.6-terra / luna / Gemini）

formats-v10（Daily 目標 1,550〜1,750字・上限 4,200字、長い分は warning のみ）で測定。
Daily 3題材＋日曜ラボ1本、各回3モデルに同一プロンプト。

| Daily 3回平均 | Gemini 3.7 Flash | **gpt-5.6-terra** | gpt-5.6-luna |
|---|---|---|---|
| 台本文字数 | 1,734字 | **1,699字** | 1,996字 |
| 総トークン | 8,153 | **6,022** | 6,410 |
| うち reasoning | 3,520 | **199** | 393 |
| レイテンシ | 19.3s | 24.5s | 20.5s |
| 辞書適用後に残る英字 | 7.3箇所 | 6.3箇所 | 10.3箇所 |

| 日曜ラボ（目標 3,000〜3,500字） | Gemini | terra | luna |
|---|---|---|---|
| 台本文字数 | 3,021字 | 3,502字 | 4,487字 |

- 全12本が本番ゲートを通過。v10 の非対称ゲートにより、9/7 時点で懸念した「OpenAI は長い」は問題でなくなった
- **luna は1本で、システム指示の書式見本 `ケンジ：[セリフ]` を全19行に写した。** 本番ゲートはこれを検出できなかった
  → 書式マーカーの除去と、プレースホルダ検出ゲートを追加した
- terra は目標文字数に収まり、reasoning が極端に少ない。英字の取りこぼしも Gemini と同程度

## 現時点の判断

**2026-09-18 から、台本生成は `gpt-5.6-terra`、失敗時は Gemini 3.7 Flash へ自動フォールバック、音声監査は Gemini のまま。**

- 書く側（OpenAI）と聞く側（Gemini）が別ベンダーになり、生成と監査の独立性が上がる
- Gemini の API 枠を料理支援アプリの音声対話へ回せる（ただし枠と課金はプロジェクト単位なので、アプリ側は別プロジェクト・別キーにする）
- 切り戻しは workflow の `SCRIPT_PROVIDER: "gemini"` だけでよい（コード変更不要）
- フォールバックの発生は各 manifest の `deterministic_checks.script_generation` に記録される
  （`provider` / `model` / `fallback_used` / `fallback_count` / `calls[].fallback_reason` / トークン数）

### フォールバック理由の一覧

| `fallback_reason` | 意味 |
|---|---|
| `openai_unconfigured` | `OPENAI_API_KEY` が未設定（Secret 未登録など） |
| `openai_quota` | 残高・枠切れ（429 insufficient_quota）。待っても戻らないので再試行しない |
| `openai_auth` | 401/403。キー失効など |
| `openai_bad_request` | 400/404 等。モデル名の誤りなど |
| `openai_transient_exhausted` | 429/5xx/タイムアウトが4回続いた |
| `openai_incomplete` | 出力が途中で止まった（台本が切れているので使わない） |
| `openai_empty_output` | 本文が空 |
| `openai_error` | 上記以外 |
