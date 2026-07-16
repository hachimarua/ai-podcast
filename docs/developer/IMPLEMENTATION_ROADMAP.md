# AI学習ラジオ 改良ロードマップ

最終更新: 2026-07-05  
対象リポジトリ: `hachimarua/ai-podcast`  
目的: 毎朝の配信を止めずに、重複防止・音声品質監査・人間承認付き改善を段階導入する。

## この文書の役割

この文書は、会話の短縮や担当エージェントの交代後も作業を再開できるようにするための一次資料である。

再開時は必ず次の順序で確認する。

1. このロードマップを読む。
2. `git status --short --branch` と `git log -5 --oneline --all` を確認する。
3. 未コミット変更を保護する。
4. 「現在フェーズ」と「次の一手」を確認してからコードを変更する。
5. 各フェーズの完了条件を満たし、検証結果をこの文書へ追記する。

## 図

- [現行システム構造](./01_current_system.svg)
- [推奨システム構成](./02_recommended_system.svg)

## 現在の確認済み状態

- GitHub Actionsが毎日JST 4:00に起動する。
- Notion Inbox整理、復習項目選出、ニュース収集、Gemini台本生成、Edge TTS、BGM合成、RSS更新、GitHub Pages配信を行う。
- `origin/main` では2026-07-05放送まで配信済み。
- ローカル`main`は確認時点で公開版より4コミット遅れていた。
- `script_generator.py`にユーザー側の未コミット変更がある。上書き・破棄しない。
- 過去放送にはMP3と汎用RSS情報しか残らず、採用テーマ・台本・品質評価の永続履歴がない。
- 復習項目は復習回数の少ない候補からランダム選出され、過去3回との重複判定がない。
- Python 12ファイルのAST解析と現仮想環境の`pip check`は成功済み。
- Antigravity 2.0.10とAntigravity IDE 2.1.1がMacにインストール済み。

## 設計原則

1. **放送系とフィードバック系を分離する。** MacやAntigravityが閉じていてもGitHub Actions上の放送は継続する。
2. **まず決定論、必要な箇所だけAI。** ハッシュ、URL、音量、無音、長さ、完全一致はPython/FFmpegで判定する。
3. **AIは監査と提案を担当する。** GeminiによるMP3監査結果だけでソースコードを自動変更しない。
4. **人間承認を境界にする。** Agreed後のみ設定反映または実装タスク化し、Disagreeは理由とともに履歴化する。
5. **フェイルクローズ。** NotionやGeminiの障害時にモック内容を本番配信しない。
6. **既存資産を優先する。** GitHub、Notion、Antigravity、macOSを使い、新規外部サービスは追加しない。
7. **機密を配信面へ置かない。** `.env`、APIキー、Notionの生データをGitHub Pagesや品質レポートへ出さない。

## 目標アーキテクチャ

### クラウド側（放送を止めない）

GitHub Actionsが次を実行する。

1. 入力取得と妥当性確認
2. 過去3回の履歴を使った候補選出
3. 台本生成前の重複ゲート
4. 台本生成後の意味的重複ゲート
5. TTS・BGM合成
6. 決定論的音声検査
7. GeminiによるMP3監査
8. 公開判定
9. MP3、RSS、episode manifest、品質レポートを保存

### Mac側（確認は後からでよい）

Antigravity Sidecarが軽量スクリプトで未判断レポートだけを確認する。

- 問題なし: 何もしない。
- 新しい改善提案あり: Antigravityプロジェクトへ確認用会話を1件作成する。
- Agreed: 決定を記録し、安全な設定変更は次回放送へ反映する。
- Disagree: 却下理由を記録する。
- Later: 未判断のまま保持し、同じ通知を連打しない。

## モデル利用方針

| 処理 | 手段 | 方針 |
|---|---|---|
| 完全一致、URL重複、採用回数 | Python | AIを使わない |
| 音量、無音、長さ、クリッピング | FFmpeg/ffprobe | AIを使わない |
| 台本の類似度一次判定 | 正規化テキスト＋集合類似度 | AIを使わない |
| 境界例の意味的重複判定 | Gemini Flash | 閾値付近だけ呼ぶ |
| MP3の聞感・話者・読み上げ監査 | Gemini 3.5 Flash | 1放送につき最大1回 |
| 通知対象の有無 | Sidecarスクリプト | AIを使わない |
| 改善提案の表示 | Antigravity会話 | 問題がある場合だけ作成 |
| コード実装・高リスク変更 | Codex | 承認後のみ |

## データ設計

### Episode Manifest

各放送に対応するJSONを`episode_manifests/`へ保存する。

必須項目:

- `schema_version`
- `episode_id`
- `broadcast_date`
- `generated_at`
- `selected_term_keys`（NotionページIDのSHA-256短縮キー。生IDは保存しない）
- `primary_topic`
- `topic_fingerprint`
- `news_urls`
- `script_sha256`
- `audio_sha256`
- `duration_seconds`
- `deterministic_checks`
- `gemini_qa_summary`
- `publish_status`
- `pipeline_version`

Notion本文、完全な台本、APIレスポンス全文は公開manifestへ保存しない。台本保存が必要な場合は公開範囲と個人情報を確認して別途決める。

### Review Proposal

`quality_reports/pending/`に、ユーザー確認が必要な提案だけをJSONで保存する。

必須項目:

- `proposal_id`
- `episode_id`
- `severity`
- `category`
- `evidence`
- `timestamp_ranges`
- `suggested_change`
- `safe_auto_apply`
- `status`: `pending | agreed | disagreed | later | applied`
- `decision_reason`
- `created_at`
- `decided_at`
- `application`（適用済みの場合のみ。Level、適用日時、変更ファイル、検証結果）

## 重複防止ポリシー v1

- 過去3回の主要テーマは原則として再採用しない。
- 過去3回で使用した同一ニュースURLは再利用しない。
- 補助テーマは候補不足時に最大1件まで再利用できる。
- 台本生成後に過去3回との類似度を再計算する。
- 主要テーマ完全一致または高類似の場合は、公開前に1回だけ候補を再選出して再生成する。
- 再生成後も高類似なら、無理に繰り返さず「新着不足用の別企画」へ切り替える。
- 候補不足をNotion障害と混同しない。Notion障害時は本番生成を中止する。

## 段階実装

### Phase 0: ベースライン保護と安全修正

目的: 既存配信を壊さず、危険なフェイルオープンを先に閉じる。

実装候補:

- ローカル変更を保護したまま`origin/main`を取り込む。
- Notion API失敗時の本番モックフォールバックを廃止する。
- `requests`へtimeout、限定リトライ、明示的エラーを追加する。
- GitHub Actionsへ`concurrency`を追加する。
- 同日エピソードの冪等キーを導入する。
- ローカルHTTPサーバーの公開ルートを専用`public/`へ限定し、`.env`を配信しない。
- Inbox処理と本番生成の失敗を正しい終了コードで伝播する。

完了条件:

- Notion障害時にMP3・RSS・復習履歴が更新されない。
- 同日の再実行でエピソードが重複作成されない。
- ローカルサーバーから`.env`へアクセスできない。
- 単体テストと主要失敗系テストが成功する。

### Phase 1: 履歴と重複防止

目的: 過去3回の内容を参照し、連続重複を防ぐ。

実装候補:

- Episode Manifestのスキーマと読み書きを追加する。
- 既存直近3MP3を一度だけ文字起こしし、初期履歴を作る。
- 候補選出をランダム方式からスコア方式へ変更する。
- 台本生成前後の二段階重複ゲートを追加する。
- 候補不足時の別企画フォールバックを追加する。

完了条件:

- 同じ主要テーマが2日連続で公開されない。
- 過去3回との採用項目・URL・類似度がmanifestから説明できる。
- 固定fixtureを使った選出テストが再現可能である。

### Phase 2: 音声品質ゲート

目的: MP3を公開前に機械検査し、壊れた音声を防ぐ。

実装候補:

- ffprobeによる長さ・デコード可否確認。
- 無音、クリッピング、ラウドネス、極端な短尺の検出。
- MP3バイナリ結合をFFmpeg concatへ置き換える。
- 台本行数と生成セグメント数の整合確認。

完了条件:

- 破損、無音、1分未満などのfixtureを公開不可にできる。
- 正常な過去MP3が誤って停止されない。

### Phase 3: Gemini MP3監査（シャドー運用）

目的: 聞感、話者、読み上げ、会話品質を構造化評価する。

実装候補:

- 構造化レスポンススキーマを定義する。
- 1放送1回の音声監査を追加する。
- タイムスタンプ付き問題、重大度、改善案を保存する。
- 最初の1〜2週間は明確な破損以外で配信を止めない。

完了条件:

- 同じMP3を再評価した際に重大判定が大きく揺れない。
- 人間が問題箇所をタイムスタンプから確認できる。
- API障害時の挙動が明示されている。

### Phase 4: Antigravity通知とAgreed/Disagree

目的: Notionやブラウザを開かず、Antigravityで判断できるようにする。

実装候補:

- 未判断レポートを確認する決定論的スクリプトを追加する。
- Antigravity Sidecar設定案を作る。
- `agentapi new-conversation`で確認会話を作成する。
- `Agreed / Disagree / Later`の判断を記録する。
- 同一proposalの重複通知を防ぐ。
- SidecarはAntigravity 2.0起動中のみ通知担当とし、放送系から分離する。

完了条件:

- 問題なしの日は会話を作らない。
- 問題ありの日は同一proposalにつき1会話だけ作る。
- Macが閉じていても放送は継続する。
- 次回起動時に未判断proposalを検出できる。

### Phase 5: 承認済み改善の反映

目的: 小さな改善を安全にPDCAへ戻す。

反映レベル:

- Level A: 閾値、禁止期間、音量などの設定変更。Agreed後にAntigravityが反映する。
- Level B: プロンプト変更。Agreed後にAntigravityが差分とテストを作り、反映する。
- Level C: Python変更のうち局所的で小規模なものはAntigravityが担当する。Workflow、権限、Secrets、依存関係、破壊的データ変更、大きな設計変更、本番コード4ファイル以上の変更はCodexへエスカレーションする。

運用上の役割分担:

- Antigravityは日常運用の実務担当とし、ユーザーとの提案確認、Agreed後の修正、検証、適用記録、commit、push、完了報告まで同じ会話で行う。
- Codexは通常経路へ自動接続しない。Antigravityが明示的な高リスク条件または解消不能な問題を報告し、ユーザーが依頼した場合だけ監修・実装を担当する。
- 「対応可能」という自己申告だけで進めず、変更範囲とテスト結果を完了判定の根拠にする。

完了条件:

- どの提案がいつ何へ反映されたか追跡できる。
- Disagreeされた提案が再提案され続けない。
- コード変更が承認なしで自動生成・pushされない。
- Agreed後の日常修正は、別途Codexへ依頼せずAntigravity内で完了する。

### Phase 6: Obsidian Inbox連携（別トラック）

目的: 入力頻度を上げ、候補不足そのものを減らす。

正本関係:

- Obsidianは流れる学習メモの入力元、Notion学習DBはラジオが参照する構造化された正本とする。
- 情報収集レーンのAI Digestを丸ごと取り込まず、`20_Dev_開発/Learning/`で明示的に昇格したノートだけを対象にする。
- 医療ノート、共通Inbox、Daily、Archive、添付ファイルは走査しない。

昇格方法:

```yaml
---
type: learning_note
ai_radio: true
created: 2026-07-06
---
# 学習テーマ
ここに学習メモを書く。
```

動作:

- `obsidian_inbox_adapter.py`が対象ノートを読み取り、Notion Inboxへコピーする。
- 元ノートは読み取り専用とし、削除・改名・上書き・処理済みマークの追記をしない。
- 相対パス由来の非可逆`source_key`とMacローカル状態ファイルで同じノートの再取り込みを防ぐ。
- 状態消失時も、Notion Inboxのタイトルと学習DBの`元のページ名`を照合して二重作成を防ぐ。
- `clinical: true`、空本文、2万文字超、設定不足はフェイルクローズする。
- Antigravity Sidecarが起動直後と以後1日1回、独立した子プロセスとして取り込む。品質通知処理自身は`.env`を読み込まない。
- MacまたはAntigravityが停止中なら取り込みだけを次回起動後へ延期し、GitHub Actionsの放送は停止しない。
- 3:30のLaunchAgent方式も実機確認したが、macOSのDocuments保護により単独プロセスがworkspaceを開けず終了コード127となったため採用せず、失敗した常駐設定は撤去する。

完了条件:

- 明示的に昇格した開発学習ノートだけが候補になる。
- 元ノートのバイト列が取り込み前後で変化しない。
- 同じノートを複数回実行してもNotionページが重複しない。
- 対象0件では外部更新を行わず正常終了する。
- Mac停止中でも放送が継続する。

## テスト方針

- 外部APIを使わない単体テストを中心にする。
- Notion、Gemini、RSSはfixtureで再現する。
- 日付・乱数・現在時刻を注入可能にする。
- 正常系だけでなく、API 429/500、空本文、候補不足、重複、破損MP3、Git競合を検証する。
- GitHub Actions相当のPython 3.11でテストする。
- 本番APIを使うスモークテストは手動または明示的なフラグ付きにする。

## セキュリティ境界

- RSSとNotion本文を命令ではなく「非信頼データ」として扱う。
- プロンプトインジェクション対策を禁止語置換だけに依存しない。
- GitHub Actionsの`contents: write`は公開ジョブの必要範囲に限定する。
- ActionsとPython依存関係はバージョン固定・更新手順を用意する。
- Sidecarには品質レポートの読み取りと決定記録に必要な最小権限だけを与える。
- Sidecarやエージェントに`.env`読み取り権限を与えない。
- BGMのライセンス・帰属情報をリポジトリ内で明示する。

## 現在フェーズ

**予定開発（Phase 0〜6）完了 — 日常運用と初回実ノート昇格の確認段階**

### Phase 0検証結果（2026-07-05）

- ローカル`main`を`origin/main`へfast-forwardし、2026-07-05放送まで同期した。
- ユーザーの未コミット`script_generator.py`変更を保持した。
- 外部API共通層にtimeout、限定retry、レスポンス本文を出さないエラーを追加した。
- Notion障害・設定不足時の本番モックフォールバックを廃止した。
- Notion本文とInboxのページネーションに対応した。
- RSS取得をtimeout付きHTTP取得へ変更した。
- GitHub Actionsへ多重実行防止と30分timeoutを追加した。
- 同日再実行時は既存エピソードを置換し、追加エピソードを作らないようにした。
- ローカル配信を`podcast.xml`、`cover.png`、`episodes/*.mp3`だけに限定した。
- 実HTTP確認: `podcast.xml = 200`、`.env = 404`、`main.py = 404`。
- RSS・Notion入力を非信頼データとしてGeminiへ渡す境界指示を追加した。
- 直接依存関係を完全固定し、`pydantic`を明示した。
- 自動テスト10件、`pip check`、Python AST解析に成功した。

### Phase 1検証結果（2026-07-05）

- 公開用Episode Manifestスキーマと原子的保存を実装した。
- NotionページIDはSHA-256短縮キーへ変換し、本文と生IDをmanifestへ保存しない。
- 過去3manifestの採用項目、主要テーマ、ニュースURL、台本MinHashを読み込む。
- Notionの最終復習日が直近3日以内の項目を導入初日から除外する。
- 選出をランダム方式から再現可能な決定論的順序へ変更した。
- 過去3回で使用済みのニュースURLを除外する。
- 新しい復習項目がなければ最新ニュース特集へ切り替える。
- 台本類似度が閾値以上ならニュース特集として1回だけ再生成する。
- 再生成後も高類似なら公開前に安全停止する。
- 初回Actionsでmanifestが空の場合だけ、直近3MP3をGemini 2.5 Flashで解析するステップを追加した。
- ローカル`.env`はプレースホルダーのためブートストラップは安全停止した。GitHub Secretsを使うbootstrap-only Actionsは成功した。
- 2026-07-03〜05の3manifestを生成し、Notion生ID・本文・秘密情報が含まれないことを確認した。
- 主要テーマ解析により、7月4日「Cloudflare D1とその活用、セキュリティ」と7月5日「Cloudflare D1とAIを活用した情報管理の効率化」の重複を確認した。
- 台本文字列MinHashは表現差により0.172だったため、主要テーマの文字bigram類似度ゲートを追加した。上記2件は0.361となり、閾値0.30で検出できる。
- 自動テストは22件へ増加し、重複時のニュース再生成とCloudflare D1実例のテーマ除外を確認した。

### Phase 2検証結果（2026-07-05）

- MP3セグメントの生バイナリ結合を廃止し、FFmpeg concat demuxerへ置き換えた。
- セグメントと結合音声を実行ごとの一時ディレクトリへ隔離した。
- ffprobeでデコード可否と再生時間を確認する公開前ゲートを追加した。
- FFmpegで平均音量、最大音量、2秒以上の長時間無音を測定するゲートを追加した。
- 本番閾値は長さ180〜600秒、平均音量-28〜-10dB、最大音量-0.1dB以下、長時間無音15%以下とした。
- 品質検査結果をEpisode Manifestの`deterministic_checks.audio_quality`へ保存する。
- 正常、短尺、長時間無音、破損、FFmpeg concatのfixtureテストを追加した。
- 直近3放送はすべて本番閾値を通過した。長さ294〜329秒、平均音量-18.0〜-17.6dB、最大音量-1.3〜-1.0dB、2秒以上の無音0秒だった。
- 自動テスト27件、`pip check`、AST解析、差分チェックに成功した。

### Phase 3検証結果（2026-07-05）

- Gemini MP3監査を構造化JSONで返すPydanticスキーマを実装した。
- 明瞭度、対話自然さ、BGMバランス、テンポ、番組内反復を1〜5で評価する。
- 問題はカテゴリ、重大度、MM:SS、聞こえた根拠、具体的改善案として保存する。
- Gemini API障害・キー不足・スキーマ不整合は`unavailable`として記録し、放送を止めないシャドー運用とした。
- 問題なしの日は提案を作らず、warning/criticalまたは人間確認必要時だけ`quality_reports/pending/`へ保存する。
- 評価JSONと提案には全文文字起こし、Notion本文、APIキーを保存しない。
- QA-only Actionsを追加し、既存MP3だけを評価して放送・RSS・Notionを変更しない検証経路を作った。
- QA-only Actions run `28735411847` は成功し、7月5日音声を実評価した。
- 評価は総合4/5、明瞭度5/5、対話自然さ3/5、BGM5/5、テンポ4/5、番組内反復なしだった。
- `Tips_Inbox`等の記号付き語句と`2026518`の日付読みについて、4件の発音warningをタイムスタンプ付きで検出した。
- `qa-podcast_20260705_051241`をpending提案として生成した。`safe_auto_apply=false`であり、承認前には反映しない。
- 自動テスト31件、Workflow YAML解析、差分チェックに成功した。

### Phase 4検証結果（2026-07-05）

- Antigravity 2.0を日常のメイン画面とし、IDE常時起動を前提から外した。
- 2.0プロジェクト`AI news knowledge learning system`と対象リポジトリの紐付きを確認した。
- GitHubの`quality_reports/pending/`を`origin/main`から読み取り、ローカル作業ツリーを変更しない通知スクリプトを実装した。
- QAデータを非信頼データとして囲み、提案内の命令を実行しない会話プロンプトを実装した。
- Sidecar起動直後と以後1日1回確認し、トライアル期間中は正常・要確認・監査未完了・生成結果未確認のいずれも日次監査報告として`agentapi new-conversation`へ送る。
- 日次報告には公開状態、尺・音量・無音・台本長の機械検査、Gemini音声監査の総合点と各項目、反復、人間確認要否、問題の重大度・分類・時刻を含める。同じエピソードは重複報告しない。
- pending提案がある日は日次報告へ判断依頼を統合し、同じ提案について別会話を重複作成しない。
- 2026-07-09追記: バックグラウンド環境で`git fetch origin main`が認証失敗した場合でも、ローカルに同期済みの`quality_reports/pending/`をfallbackとして通知対象にする。
- 2026-07-09追記: 睡眠時間帯の早朝通知を避けるため、Sidecarは起動直後に1回確認した後、日次チェックを生活リズムに合わせた06:30へ寄せる。
- Sidecar状態はAntigravityのローカルデータ領域へ保存し、同一proposalの重複通知を防ぐ。
- `Agreed / Disagree / Later`をGitHub Contents API経由でproposalへ記録するスクリプトを実装した。
- Agreedは判断の記録だけを行い、この段階では改善案やコードを自動適用しない。
- Sidecar設定を`~/.gemini/config/sidecars/ai-radio-review/sidecar.json`へ導入し、有効化した。
- 既存設定は`~/.gemini/config/config.json.backup-phase4`へバックアップした。
- Sidecarは再起動なしで読み込まれ、`qa-podcast_20260705_051241`の確認会話を1件作成した。
- 同じ実状態で再確認し、通知作成0件となることを確認した。
- 自動テスト35件、JSON検証、差分チェックに成功した。

### Phase 5検証結果（2026-07-05）

- GitHub上の`qa-podcast_20260705_051241`が`agreed`、判断日時と理由が記録済みであることを確認した。
- この提案は`safe_auto_apply=false`のため、Level Aの自動設定変更ではなくLevel Bの台本生成プロンプト改善として処理した。
- 台本生成指示へ、アンダースコア等を含む技術識別子の自然な言い換え、日付と識別番号の読み分け、途中で切れた英単語を残さない規則、出力後の音読点検を追加した。
- Agreed済みproposalだけを`applied`へ遷移させる`improvement_application.py`を追加した。
- Level Aは`safe_auto_apply=true`の場合だけ許可し、Level B/Cは変更ファイルと検証結果がなければ適用記録を作れないようにした。
- `qa-podcast_20260705_051241`へLevel B、適用日時、変更ファイル、検証結果を記録し、`applied`へ更新した。
- Disagreeは既存の決定状態として残り、Sidecarは`pending`だけを通知するため、同一proposalを再通知・適用しない。
- 適用ツールはローカルJSONの検証と記録だけを行い、コード生成、commit、pushは実行しない。
- 初回は大規模改修の見本としてCodexが実装したが、今後の日常修正はAgreed後にAntigravityが同じ会話で実装から完了報告まで担当する運用へ変更した。
- Antigravityの会話指示へ、ローカル同期、最小実装、テスト、`applied`記録、commit、push、完了報告の手順を追加した。
- Workflow・権限・Secrets・依存関係・破壊的データ変更・大きな設計変更・本番コード4ファイル以上を機械的なエスカレーション条件にし、対応可否を自己申告だけで判断しないようにした。
- 自動テスト39件、`pip check`、Python AST解析、Workflow YAML解析、JSON検証、差分チェックに成功した。

### Phase 6検証結果（2026-07-06）

- MainVaultの`AGENTS.md`、`_RULES.md`、開発・Learning・AI DigestのREADMEを読み、既存の「情報収集レーンと学習レーンを分け、学びたい概念だけ昇格する」方針を正本関係へ採用した。
- `20_Dev_開発/Learning/`内でfrontmatterに`ai_radio: true`または`ready`があるMarkdownだけを読む`obsidian_inbox_adapter.py`を追加した。
- Vault全体、医療ノート、共通Inbox、Daily、Archive、添付ファイルを走査対象から除外した。
- 元ノートを変更せずNotion Inboxへコピーし、Notion学習DBをラジオ入力の正本として維持した。
- Macローカル状態とNotion上の二重照合により、同じノートの再実行・状態消失時の重複作成を防ぐ。
- `clinical: true`、空本文、2万文字超、Notion設定不足を安全停止させる。
- LaunchAgent単独実行はmacOSのDocuments保護により終了コード127となったため撤去し、既存Antigravity Sidecarから独立子プロセスとして起動する構成へ切り替えた。
- Sidecar子プロセス経由の実Vault確認は`discovered=0 pending=0 imported=0 skipped=0`で正常終了し、外部更新を行わなかった。
- Sidecarを再起動し、新しいプロセスで起動直後と以後1日1回の取り込みが有効になったことを確認した。
- 自動テスト44件、`pip check`、Python AST解析、JSON検証、差分チェックに成功した。

### 次の一手

### ニュースソース多様化（2026-07-12）

- 毎朝の放送は従来どおり**5分のラジオ1本**とし、別番組を2本作らない。
- 収集元にITmedia AI+とAI Watchを追加し、RSS取得を事前確認した。Ledge.aiは想定RSSが404だったため採用しない。
- 台本へ渡すニュースは最大2件。Notion復習用語との一致を最優先しつつ、2件目は14日以内の日本語AI報道を優先する。候補が古い・ない場合は、異なる海外または研究ソースへフォールバックする。
- 異なる候補がある限り同一放送で同じ媒体を2件採らず、manifestの`deterministic_checks.news_selection`へ候補数・採用媒体・選出理由だけを保存する。本文やNotionデータは保存しない。
- 日本の導入・提供開始・活用事例は、記事本文で明確な場合だけ放送内でそのように説明する。媒体が日本語であることだけを根拠に国内事例と推測しない。

1. 学習したい開発概念を`20_Dev_開発/Learning/`へ置き、frontmatterへ`ai_radio: true`を付ける。
2. Antigravity Sidecarの次回確認でNotion Inboxへ1件だけ入り、元ノートが不変であることを実データで確認する。
3. 次回GitHub ActionsでNotion学習DBへ清書され、後日のテーマ候補に入ることを確認する。
4. 新しい品質proposalが出た場合は、Antigravityとの会話でAgreed後の実装から完了報告までを確認する。

## 変更履歴

- 2026-07-05: 初版作成。現行構造、推奨構成、Phase 0〜6、完了条件を定義。
- 2026-07-05: Phase 0完了。フェイルクローズ、通信安全化、同日冪等性、限定ローカル配信、10テストを追加。
- 2026-07-05: Phase 1実装完了。Episode Manifest、過去3回参照、ニュースURL除外、台本MinHash、再生成ゲート、初回音声ブートストラップ、20テストを追加。
- 2026-07-05: bootstrap-only Actions成功。3manifestを生成し、実例からテーマ類似度ゲートを追加。Phase 1完了、22テスト成功。
- 2026-07-05: Phase 2完了。FFmpeg concat、デコード・長さ・音量・無音ゲート、音響fixtureを追加。27テスト成功。
- 2026-07-05: Phase 3完了。Gemini MP3シャドー監査、QA-only Actions、pending提案を実装。実音声で4件の発音warningを検出、31テスト成功。
- 2026-07-05: Phase 4実装完了。Antigravity 2.0 Sidecar、重複通知防止、Agreed/Disagree/Later記録を追加。初回確認会話を作成、35テスト成功。
- 2026-07-05: Phase 5完了。初回Agreed提案をLevel Bとして台本生成ルールへ反映し、適用履歴と安全レベル検証を追加。39テスト成功。
- 2026-07-05: 日常運用の担当をAntigravityへ移管。Agreed後は同じ会話内で実装・検証・push・完了報告まで行い、Codexは高リスク案件の監修先とする役割分担へ更新。
- 2026-07-06: Phase 6実装完了。Obsidian Learningの明示的昇格ノートだけを読み取り専用でNotion Inboxへ渡すアダプター、二重取り込み防止、Antigravity Sidecar連携を追加。44テスト成功。
- 2026-07-06: Sidecarの確認頻度を15分ごとから起動直後＋1日1回へ変更。Phase 0〜6の予定開発を完了扱いとし、日常運用へ移行。
