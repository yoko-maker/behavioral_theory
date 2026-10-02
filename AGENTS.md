# AGENTS.md — 認知・判断・行動分析アプリ

このファイルは「地図」です。詳細は `docs/` を正とし、ここには入口と絶対ルールだけを書きます。
サブディレクトリの `AGENTS.md` は、そのディレクトリ配下の作業時に追加で従うルールです（近い方が優先）。

## プロジェクト概要

Streamlit で実装する認知課題（リンダ問題・バットとボール問題）の実験・分析アプリ。
要件の一次資料は [認知・判断・行動分析アプリ_概要書.md](認知・判断・行動分析アプリ_概要書.md)（非公開のためリポジトリには含めない。ローカルにある場合のみ参照する。
ない場合は `docs/` とこのファイルの記述を正とする）。
研究用データを扱うため、**再現性・データ完全性・参加者保護**をコードの見た目より優先する。

## 地図

| 場所 | 役割 |
| --- | --- |
| `app/` | Streamlit UI 層（画面・セッション状態のみ）。→ `app/AGENTS.md` |
| `src/cogexp/domain/` | 純粋ロジック（モデル・採点・出題制御・時計）。→ `src/cogexp/domain/AGENTS.md` |
| `src/cogexp/service.py` | 参加者セッションの進行（app から呼ぶ唯一の入口） |
| `src/cogexp/config/` | `experiments/` の YAML と参加者向け文面（`experiments/texts/`）の読み込み |
| `src/cogexp/storage/` | 保存層（スキーマ・リポジトリ）。→ `src/cogexp/storage/AGENTS.md` |
| `src/cogexp/analysis/` | 集計・前処理（pandas）。UI 非依存 |
| `experiments/` | 問題文・条件設定（版管理対象）。→ `experiments/AGENTS.md` |
| `docs/architecture.md` | レイヤ構成と依存ルール |
| `docs/data_dictionary.md` | 全保存項目の定義（スキーマと同期必須） |
| `docs/plans/` | フェーズ別の実行計画。作業前に該当プランを読む |
| `docs/harness.md` | このハーネスの設計意図 |
| `scripts/dev.py` | 全開発コマンドの単一入口 |

## コマンド（すべて `scripts/dev.py` 経由）

```sh
uv sync                                   # 依存関係のインストール
uv run python scripts/dev.py fmt          # 整形 + 自動修正（変更後に必ず実行）
uv run python scripts/dev.py check        # 完了前の必須ゲート（整形確認・lint・型・構造チェック・テスト）
uv run python scripts/dev.py test -k xxx  # テストの部分実行
uv run python scripts/dev.py lock         # 新しい問題文バージョンをロックに登録
uv run python scripts/dev.py app          # アプリ起動
```

## 作業ルール

- 作業を「完了」と報告する前に `dev.py check` を実行し、全項目が PASS であることを確認する。失敗を残したまま完了扱いにしない。
- 振る舞いを変えたらテストを追加・更新する。UI フローは `streamlit.testing.v1.AppTest` でテストする。
- 構造チェック（`scripts/checks/`）が失敗したら、エラーメッセージの「対処」に従う。チェックを緩めて通すことはしない。ルール自体の変更が必要なら、理由を添えてユーザーに確認する。
- 保存項目を追加・変更したら `docs/data_dictionary.md` を同時に更新する。
- 大きな機能はまず `docs/plans/` のプランを更新し、チェックリストを進捗に合わせて更新する。

## 絶対ルール（研究データの完全性）

1. **同意前にデータを保存しない。** 同意状態の確認を経ずに trial/event を書き込むコードを作らない。
2. **問題文は版で管理する。** 既存の `task_id/variant_id@version` の内容を書き換えない。変更は version を上げて新規追加する（`check` が検出する）。
3. **時間切れ・未回答・中断を誤答と混同しない。** `outcome` で区別し、`is_correct` は判定可能な回答にのみ設定する。
4. **時刻・乱数は注入する。** 時刻は `cogexp.domain.clock`、乱数は seed 付きの割当モジュールからのみ取得する。
5. **直接識別情報を分析データに入れない。** 氏名・メール等の列を storage スキーマに追加しない。
6. **生データを書き換えない。** 前処理結果は別テーブル／別ファイルに出力する。除外は事前定義したルールでのみ行う。
7. 結果を「直感的思考」「能力」「性格」と断定する表示・文言を UI や分析出力に入れない（概要書 §1, §12.3）。
