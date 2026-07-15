# Siriフィードバック導線 実装仕様

最終更新: 2026-07-15

状態: **専用Worker・D1・Bearer認証と3本のショートカットは実装済み。Watch実機試験が残っている。**

## 採用構成

- 同じCloudflare契約内に`ai-radio-feedback`専用Workerと専用D1を作る。
- 凪、Gabor Care、Workout TrackerのWorker・D1・Secretsは共有しない。
- 受付処理は閉じた3値、RSS解析、D1書き込みだけで構成し、生成AI APIは呼ばない。
- `FEEDBACK_TOKEN`はWorker Secretと個人用ショートカットだけに保持する。
- `new` / `known`は公開RSSの最新回、`tried`は直近の`new`へ対応させる。
- 2026-07-15に会話上で報告された`初耳`は、未保存データとして後付け登録しない。

## 保存するデータ

- `episode_id`
- `reaction` (`new` / `known` / `tried`)
- `occurred_at`
- 再送防止用ID
- サーバー受信時刻
- `tried`が参照した`new`の内部ID

メール、自由記述、氏名、端末ID、Notion原文は保存しない。

## セキュリティ境界

- Bearer tokenがない書き込み・読み取りは拒否する。
- 公開するのは`/health`の固定応答だけ。
- 入力サイズ、反応コード、時刻範囲、再送防止キーを検証する。
- エラー応答とログへToken、D1行、RSS本文を出さない。Wrangler設定に必要な`database_id`だけは非機密メタデータとしてGit管理する。
- 同一再送防止キーで異なる反応を送った場合は409で停止する。
- ショートカット専用の3エンドポイントは本文不要とし、同じ反応の同一分内再送をWorker側で1件へまとめる。

## 完了条件

1. Worker単体テストが成功する。
2. 専用D1へmigrationが適用される。
3. 本番`/health`が200を返す。
4. 3反応を試験登録し、`episode_id`・反応・時刻が正しい。
5. 同一キー再送で行数が増えない。
6. `tried`に対応する`new`がない場合は保存せず通知する。
7. 3本のショートカットがApple Watchへ同期される。
8. 各名称10回中9回以上成功し、3種の取り違えが0件。

## 2026-07-15 本番反映結果

- Worker: `https://ai-radio-feedback.hachiotsssg.workers.dev`
- D1: `ai-radio-feedback`（APAC、他プロジェクトと分離）
- migration `0001_create_reactions.sql`: remote適用成功
- `GET /health`: 200
- tokenなしの書き込み: 401
- tokenありの読み取り: 200
- 本番D1の保存件数: 0件。Macの3ショートカットで作成した試験4件は確認後に削除した
- ローカル統合試験: `new`登録、同一キー再送、`tried`紐付け、直近一覧を確認
- 本番統合試験: `new / known / tried`の3種と`tried`→直近`new`の紐付けを確認
- `AIラジオ 初耳 / 知ってた / 試した`をMacのiCloud同期対象一覧で確認
- Node単体テスト7件、既存Pythonテスト100件、Worker dry-run成功
- Wrangler 4.110.0へ更新後、npm audit 0件
- macOS補助アクセスと各ショートカットの初回ネットワーク接続はユーザー許可済み
- Header以外へ一時的に入ったToken文字列は除去し、Token本文を一時ファイルとクリップボードから消去した
- 残作業はApple Watchへの同期確認とSiri音声認識の実機試験

## API節約方針

この導線はAI判断を必要としないため、軽量モデルへ回す処理もありません。週次集計を追加する場合も、まずSQL集計で完結させ、自由記述の要約が必要になった時だけ軽量モデルを検討します。
