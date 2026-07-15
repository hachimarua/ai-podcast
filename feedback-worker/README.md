# AI radio feedback Worker

Apple WatchのSiriから起動する3本のショートカット向けに、`new` / `known` / `tried`だけを受け付ける専用Cloudflare Workerです。凪など他プロジェクトのWorker・D1とは共有しません。生成AI APIは使用しません。

本番URL: `https://ai-radio-feedback.hachiotsssg.workers.dev`

## API

- `GET /health`: 認証不要の生存確認
- `POST /v1/reactions`: Bearer認証と`X-Idempotency-Key`必須
- `POST /v1/reactions/new|known|tried`: ショートカット専用。Bearer認証必須、本文不要、確認文をplain textで返す
- `GET /v1/reactions/recent?limit=20`: Bearer認証必須の確認用読み取り

送信例:

```json
{
  "reaction": "new",
  "occurred_at": "2026-07-15T07:00:00+09:00"
}
```

`new` / `known`は公開RSSの最新回へ対応させます。`tried`はD1内で直近の`new`へ対応させ、候補がなければ記録しません。リクエスト再送は同一の`X-Idempotency-Key`で重複登録されません。

## 初回セットアップ（2026-07-15完了）

1. `npm install`
2. `npx wrangler login`
3. `npx wrangler d1 create ai-radio-feedback`
4. 出力された`database_id`を`wrangler.jsonc`へ設定
5. `npx wrangler d1 migrations apply AI_RADIO_FEEDBACK_DB --remote`
6. `openssl rand -hex 32`等で専用トークンを生成
7. `npx wrangler secret put FEEDBACK_TOKEN`
8. `npm test && npm run deploy`

トークン値とCloudflare認証情報はGitへ保存しないでください。`database_id`はWrangler設定に必要な非機密メタデータとして`wrangler.jsonc`で管理します。

## Appleショートカットの共通構成

3本とも次の順序にします。違いはURL末尾だけです。

1. 「URL」に`https://ai-radio-feedback.hachiotsssg.workers.dev/v1/reactions/<reaction>`を設定
2. 「URLの内容を取得」をPOSTにし、Header `Authorization: Bearer <専用トークン>`を設定
3. 返された確認文を「テキストを読み上げる」へ渡す

固定名と反応コード:

| ショートカット名 | URL末尾 |
|---|---|
| AIラジオ 初耳 | `/v1/reactions/new` |
| AIラジオ 知ってた | `/v1/reactions/known` |
| AIラジオ 試した | `/v1/reactions/tried` |

ショートカット専用エンドポイントは受信時刻を使用し、同じ反応の同一分内再送を1件へまとめます。

ショートカットはApple Watchに表示する設定を有効にし、まず各名称を静かな環境5回、歩行または屋外5回試します。

2026-07-15にMacで3本を作成し、`new / known / tried`の本番疎通と`tried`の紐付けを確認しました。試験データは削除済みで、Apple Watchの実機試験だけが残っています。
