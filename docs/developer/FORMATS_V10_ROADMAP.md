# formats-v10 開発ロードマップ

最終更新: 2026-09-08  
状態: **設計確定・実装前**  
対象ブランチ: `feature/formats-v10-editorial-flexibility`

## 目的

AI学習ラジオを、当初の「毎日5分なら継続できる」ことを最優先する設計から、すでに定着した聴取習慣を前提として「毎回の情報価値と聞きがいを最大化する」設計へ更新する。

formats-v10 では、生成モデルには狭い目標を与えて出力分布の中心を安定させる一方、公開監査は広く許容する。特に長尺は直ちに失敗とせず、情報密度・反復・事実性が保たれている限り公開を優先する。

## 設計原則

1. **生成目標と公開許容を分離する**
   - LLMには明確な目標尺・目標文字量を与える。
   - 目標からの逸脱そのものを品質失敗とみなさない。
   - Hard Stopは、短すぎる、極端に長い、反復、水増し、音声品質異常など、番組成立性に関わる異常へ限定する。

2. **ニュース件数ではなく情報密度を守る**
   - 「主ニュース1件固定」は廃止方向とする。
   - 1件で十分なら1件だけ扱う。
   - 重要な独立ニュースが複数あり、それぞれを十分説明できる場合は2〜3件以上を許容する。
   - 件数を満たすための追加、箇条書きダイジェスト、薄い紹介は禁止する。

3. **文字数は目的ではなく制御量として扱う**
   - 一次目標は音声秒数。
   - TTS実測の文字/秒との関係を用いてLLM向け文字数目標へ変換する。
   - 尺合わせだけを目的とした言い換え・反復・水増しは禁止する。

4. **長尺は非対称に扱う**
   - 短尺は情報不足・生成不足の可能性があるためHard Gateを維持する。
   - 長尺は内容が良ければ公開する。
   - 通常上限を超えた場合はWarningとしてmanifestへ残し、極端な長尺だけHard Stop候補とする。

5. **再生成回数を増やさない**
   - Gemini等のAPI usageを守るため、台本再生成の総予算は原則1回を維持する。
   - 長尺だけを理由に再生成しない。
   - 反復・品質異常・明確な短尺など、修復価値が高いケースへ再生成予算を使う。

## 平日: Daily Brief

### 役割

Notionの継続学習と最新AIニュースを接続する毎朝の通常版。

### 生成目標

- target duration: **約240秒**
- LLMには「約4分」を明確な中心値として指定する。
- 現行Edge TTS +10%の実測約6.8文字/秒を参照し、台本は**約1,600〜1,650文字中心**を初期値とする。
- 文字数は厳格な到達目標ではなく、TTS尺を安定させる制御量とする。

### ニュース構成

- Notionとの関連が強いニュースを優先する。
- 1件で十分な価値があれば1件だけでよい。
- 独立した重要ニュースが複数ある場合は、各ニュースについて最低限「何が起きたか」「なぜ重要か」「利用者・開発への意味または制約」を説明できる範囲で複数件を許容する。
- 「ニュース2は最大2発話」の現行制約は撤廃する。
- 重要ニュースを削って240秒へ押し込まない。

### 尺監査案

- `< 180秒`: Hard Stop / 再生成候補
- `180〜360秒`: normal
- `> 360秒`: long-duration warning、公開継続
- `> 600秒`: extreme durationとしてHard Stop候補

## 日曜: Weekly AI Review

### 役割

Notion復習とは独立した「今週のAI界隈で知っておく価値のある内容」を編集する週末版。

現行の `lab` 内部キーは互換性のため当面維持してよいが、編集上の意味は「AI実装ラボ」から **Weekly AI Review / 週刊AIレビュー** へ更新する。

### 選定方針

- Notion学習内容との関連は要求しない。
- 「バイブコーダー向け実装テーマ」に限定しない。
- モデル・エージェント・研究・サービス・デバイス・インフラ・重要な業界変化など、今週知る価値を優先する。
- 公式一次ソースは高く評価するが、主テーマが必ず公式ソースであることは要求しない。
- reporting / researchも、信頼済みホワイトリストで本文根拠がある限り候補にできる。
- 1テーマ固定をやめ、内容に応じて1〜複数テーマを許容する。
- 通常の資金調達ニュースは低優先とするが、業界構造へ影響する大型買収・提携・インフラ投資等は候補から一律除外しない方向で再設計する。

### 生成目標

- target duration: **約480秒（8分）** を初期中心値とする。
- 8分を達成するための水増しは禁止。
- 情報量が少なければ短く終了してよい。
- 情報量が豊富なら10〜15分以上へ自然に延びてもよい。

### 尺監査案

- `< 210秒`: Hard Stop候補
- `210〜900秒`: normal
- `> 900秒`: long-duration warning、公開継続
- `> 1200秒`: extreme durationとしてHard Stop候補

## 水増し・品質監査

現行の以下は維持する。

- 3-gram Jaccardによる決定論的repetition gate
- Gemini Audio QAの反復・堂々巡り検知
- duplicate similarity gate
- dialogue style / register gate
- pronunciation normalization
- 事実根拠を入力ソースへ限定するハルシネーション対策

長尺許容後は「尺が長いか」より「同じ内容を繰り返していないか」を重要な品質指標とする。

## duration telemetry

manifestへ少なくとも以下を保存する。

- `target_duration_seconds`
- `duration_warning_seconds`
- `hard_min_duration_seconds`
- `hard_max_duration_seconds`
- `actual_duration_seconds`
- `duration_headroom_seconds = actual - hard_min`
- `long_duration_warning`
- `script_character_count`
- `script_regenerations_used`
- `format_config_version`
- model名（公開安全性を確認できる場合）

将来は全generation attemptを記録し、同一モデル・同一format version単位で実測分布を評価する。published成功例だけから失敗率を推定しない。

## 実装フェーズ

### Phase 1 — format schema / prompt policy

- `config/episode_formats.json` を `formats-v10` へ更新
- target duration / warning duration / hard maxを明示
- Daily promptを「約240秒中心、情報価値があれば自然に延長」へ変更
- Weekly promptを「Notion非依存の週刊AIレビュー」へ変更
- 文字数を中心値として扱い、尺合わせの水増し禁止を明示

### Phase 2 — news selection

- Dailyの「主ニュースと関連する候補だけ」という決定論的制約を緩和
- 最大候補数を増やし、LLMが情報密度に基づいて採否を決められる入力を用意
- Weeklyのpractical-pattern必須、official-primary必須、one-theme関連制約を撤廃またはsoft preference化
- business noise filterをformat別に分離する

### Phase 3 — asymmetric duration gate

- warning thresholdとhard maximumを分離
- long durationはmanifestのdegradation/warningへ記録して公開継続
- extreme durationのみ停止
- 長尺を理由とした再生成は禁止

### Phase 4 — telemetry

- target / actual / headroom / warningをmanifestへ記録
- 後続の分布解析でformats-v9以前と混在しないようconfig versionを必ず残す
- 将来的なrolling chars/sec推定の入口を作る

### Phase 5 — tests / canary

- format config回帰テスト
- Dailyで独立ニュース複数件を許容するテスト
- Weeklyでreporting/researchのみでも成立可能なテスト
- 360秒超Dailyがwarning付きで公開可能なテスト
- 600秒超Dailyが停止するテスト
- Weekly長尺warningテスト
- repetition gateが長尺でも機能する回帰テスト
- CI全件pass後に本番マージ

## 完了条件

- Dailyは240秒付近を中心に生成されるが、良質な長尺回は停止しない。
- 重要ニュースが複数ある日に、件数制約のため情報を削らない。
- WeeklyはNotionや実装テーマに縛られず、今週の重要AIニュースを自由に編集できる。
- 1件しか情報がない日に尺合わせの反復を生成しない。
- 長尺だけを理由とした再生成を行わない。
- 台本再生成総予算は原則1回を維持する。
- manifestから尺の中心・余裕・warningを後日統計解析できる。
- 既存の安全性・重複・発音・音声品質監査を後退させない。
