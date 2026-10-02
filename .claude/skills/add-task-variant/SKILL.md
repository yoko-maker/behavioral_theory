---
name: add-task-variant
description: 問題（task）・言い換え版（variant）・問題文の改訂・実験条件を追加するときの手順。experiments/ の YAML を編集するときに使う。
---

# 問題・版・条件の追加

## 新しい言い換え版・新しい問題を追加する

1. `experiments/tasks/<task_id>.yaml` にエントリを追加する（新しい問題なら新規ファイル）。
   - 項目の定義は `src/cogexp/domain/models.py` の `TaskVariant`。
   - 正答を定義できない版（推定値の整合性で評価する等）は `correct_choice_id` / `correct_value` を書かない。
2. 実験定義（`experiments/*.yaml`）の条件から `task/variant@version` で参照する。
3. `uv run python scripts/dev.py lock` で版をロックに登録する。
4. `uv run python scripts/dev.py check` を実行する。

## 既存の問題文を直す

- 一度でもロックに登録された版は書き換えない。`version` を +1 した新しいエントリを追加し、
  実験定義の参照を新しい版に切り替える。古いエントリは残す。
- 予備実験前で一度もデータを取っていない版でも、原則は同じ。例外にしたい場合はユーザーに確認する。

## 新しい回答形式・新しい要因が必要な場合

`ResponseFormat` や `Condition` の拡張はスキーマ変更を伴う。次を同じ変更で行う：

1. `domain/models.py` の拡張とバリデーション、`tests/domain/` のテスト
2. 保存列が増えるなら `storage/schema.py` と `docs/data_dictionary.md`
3. UI の出し分け（`app/`）と AppTest
4. `docs/plans/` の該当プランに決定事項を記録
