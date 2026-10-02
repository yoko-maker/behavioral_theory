# ハーネス設計

コーディングエージェント（Claude Code / Codex）が、このリポジトリで安全かつ自律的に
実装を進められるようにするための仕組みの設計書。`openai/codex` リポジトリの構成を参考にしている。

## 基本方針

1. **ルールは文章で伝え、機械で強制する。** AGENTS.md に書いたルールのうち検査可能なものは
   `scripts/checks/` で検査し、違反時のエラーに「対処」を書く。エージェントはエラーを読めば自力で直せる。
2. **検証の入口を1つにする。** 人間・エージェント・CI が同じ `dev.py check` を実行する。
3. **指示は作業場所の近くに置く。** ルートの AGENTS.md は地図に留め、詳細は各ディレクトリの AGENTS.md と `docs/` に置く。
4. **研究固有のリスクを優先して守る。** 一般的なコード品質より、データ完全性・再現性・参加者保護の検査を厚くする。

## Codex との対応

| Codex の仕組み | Codex での例 | 本プロジェクト |
| --- | --- | --- |
| 階層的 AGENTS.md | ルート + `codex-rs/tui/src/bottom_pane/AGENTS.md`（状態機械とドキュメントの同期ルール） | ルート `AGENTS.md`（地図＋絶対ルール）+ `app/`・`domain/`・`storage/`・`experiments/` の AGENTS.md |
| コマンドの単一入口 | `justfile`（`fmt` / `fmt-check` / `clippy` / `test`）、Python 製の shell | `scripts/dev.py`（Windows でも動くよう Python のみ） |
| 境界チェックスクリプト | `.github/scripts/verify_tui_core_boundary.py` ほか `verify_*.py` | `scripts/checks/architecture.py`（レイヤ依存・時刻注入・seed 付き乱数） |
| ドキュメントと実装の同期 | bottom_pane の「docs をコードと同期させる」ルール | `scripts/checks/data_dictionary.py`（スキーマ⇔データ辞書）|
| スナップショット/統合テスト | `insta` による TUI スナップショット | `streamlit.testing.v1.AppTest` による画面フローテスト |
| 失敗を隠さない集約 | `blocking-ci.yml` の `required` ジョブ、`nextest --no-fail-fast` | `dev.py check` は全項目を実行して最後に PASS/FAIL を一覧表示 |
| ハーネス自体のテスト | `just test-github-scripts`（CI 用スクリプトの unittest） | `tests/harness/test_checks.py`（違反例を与えて検出されることを確認） |
| クリーンな作業ツリーの確認 | `check-clean-worktree` アクション | CI の `git diff --exit-code` |
| レビュー用スキル | `skills/.../review-agent/SKILL.md`（P0–P3、欠陥優先） | `.claude/skills/review/SKILL.md`（研究データ観点を追加） |

## 本プロジェクト固有の仕組み

### 問題文バージョンのロック（`scripts/checks/experiments.py`）

概要書 §15「条件ID・問題ID・問題文バージョンから実施内容を追跡できる」を保証する。

- `experiments/versions.lock.json` に `task/variant@version → 内容ハッシュ` を記録。
- 公開済みの版の書き換え・削除を `check` が失敗させる。新しい版は `dev.py lock` で明示的に登録する。
- 実験条件は版を `task/variant@version` で明示参照する（暗黙の「最新版」を使わない）。

### 時刻と乱数の注入（`architecture.py` の `injected-clock` / `seeded-random`）

時間切れ判定・条件割当を決定的にテストできるようにし、割当 seed を保存して実施内容を再現できるようにする。

### 直接識別情報の列名検査（`data_dictionary.py`）

`name` / `email` / `phone` などを含む列名がスキーマに入ると失敗する（概要書 §12.2）。

## エージェントの作業ループ

```text
docs/plans/ の該当プランを読む
  → 変更（.py は保存時にフックで自動整形）
  → uv run python scripts/dev.py check
  → FAIL ならエラーの「対処」に従い修正して再実行
  → 全 PASS でプランのチェックを更新し、完了を報告
```

## 構成ファイル一覧

| ファイル | 役割 |
| --- | --- |
| `AGENTS.md` / `CLAUDE.md` | エージェントへの指示（CLAUDE.md は AGENTS.md を取り込む） |
| `*/AGENTS.md` | ディレクトリ固有ルール |
| `scripts/dev.py` | コマンド入口 |
| `scripts/checks/*.py` | 構造チェック |
| `scripts/hooks/format_changed.py` | Claude Code の編集後自動整形 |
| `.claude/settings.json` | フック・許可コマンド |
| `.claude/skills/` | review / add-task-variant |
| `.github/workflows/ci.yml` | CI で `dev.py check` |
| `docs/plans/` | フェーズ別実行計画（進捗チェックリスト＋決定事項ログ） |

## 今後の拡張候補

- フェーズ3：JavaScript コンポーネント用のテスト（ブラウザ時刻・軌跡バッファ）を `dev.py check` に追加。
- 模擬参加者による通し実行（`dev.py simulate`）：AppTest で N 人を完走させ、出力 CSV の欠損・重複を検査。
- エクスポート CSV の列スナップショット（意図しない列追加・削除の検出）。
