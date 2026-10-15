# MacからSarashinaへ日本語の候補を依頼する

2026-10-15 本人承認。アプリ開発中のAIが、ボタン・空状態・確認文・説明文の候補をMacから依頼するための道具。日次Podcast・アプリ実行時の依存には加えない。

1. 実装担当AIが、公開して差し支えない文言だけを小さなJSONに抜き出す。コード全体・設定・認証情報・利用者の記録・医療情報を送らない。
2. 各項目に `id` / `context` / `original` / `facts` を指定する。`facts` に保存状態・数値・取り消し可否など残すべき意味を書く。
3. このMacのKeychainに保存済みの `sarashina-api` / `ai-podcast-canary` で1回呼ぶ。1回10件・入力10,000文字まで。キーを入力JSONや環境ファイルへ書かない。
4. 実装担当AIが3案を読み、意味の欠落・追加、ボタンと操作の一致、プロジェクトの文体を確認して採否を決める。候補は原稿として扱い、Sarashinaの回答を自動適用しない。
5. 採用した文言を通常の実装・画面確認・CIへ進める。呼び出し失敗時は元の文言を維持する。

入力例（架空）:

```json
[
  {
    "id": "save_failed",
    "context": "通信エラーで保存に失敗。入力内容は画面に残っている。",
    "original": "保存処理の実行に失敗しました。再試行してください。",
    "facts": ["保存は完了していない", "入力内容は画面に残っている", "もう一度保存できる"]
  }
]
```

このMacの既存Python環境から呼ぶ例。日常利用では利用者がターミナルを操作せず、実装担当AIが実行する。

```sh
'/Users/sakiya/Documents/Antigravity 2.0/AI news knowledge learning system/venv/bin/python' '/Users/sakiya/Documents/Antigravity 2.0/AI news knowledge learning system/scripts/sarashina_copy_review.py' --input /tmp/ui-copy-input.json --output /tmp/ui-copy-candidates.json
```

出力ファイルは新規作成のみ。原文・アプリのファイルは編集しない。構造の検査は行うが、意味を保ったかどうかは実装担当の確認が必要。ベータAPIの入力は改善に使われる場合があるため、送信する文言を実装担当が事前に確認する。

開く:

```sh
open '/Users/sakiya/Documents/Antigravity 2.0/AI news knowledge learning system/docs/developer/SARASHINA_LOCAL_COPY.md'
```
