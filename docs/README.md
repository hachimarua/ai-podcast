# AI学習ラジオ ドキュメント入口

人がプロジェクトのフォルダ構造を覚えなくても、ここから企画・図・実装資料へ移動できるようにする。

## まず見るもの

- [次チャット申し送り](./HANDOFF_NEXT_CHAT.md)
- [図解一覧](./visuals/README.md)
- [学習ノート取り込み（Gem → Obsidian → Notion → 放送）](./developer/LEARNING_NOTE_INTAKE.md)
- [Phase 7 編集品質ロードマップ](./developer/PHASE7_EDITORIAL_ROADMAP.md)
- [LLMプロバイダ カナリア（Gemini / OpenAI 比較）](./developer/LLM_PROVIDER_CANARY.md)
- [Siriフィードバック導線 実装仕様](./developer/SIRI_FEEDBACK_IMPLEMENTATION.md)
- [配信基盤の実装ロードマップ](./developer/IMPLEMENTATION_ROADMAP.md)

## 管理方針

- 人向けの入口は、この `docs/README.md` に固定する。
- 図の正本は各プロジェクトの `docs/visuals/` に置く。
- 図は原則としてMermaidを埋め込んだMarkdownで管理し、コード変更と同じように差分を追跡する。
- SVGやPNGは、スライドなどで必要な場合だけ書き出す。編集可能な正本にはしない。
- 複数プロジェクトを横断する一覧は共有記憶層に置き、図そのものは複製せず、この正本へのリンクだけを登録する。
