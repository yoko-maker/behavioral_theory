# データ辞書

保存される全項目の定義。`src/cogexp/storage/schema.py` と一致していることを `dev.py check` が検査する。
表の形式（列名をバッククォートで囲む・型・欠損「可/不可」・説明）を崩さないこと。

- 時刻（datetime）はすべて UTC の ISO 8601 で保存する。
- `*_client_ms` はブラウザ側の `performance.now()` 基準の相対ミリ秒で、サーバー時刻とは別系列（概要書 §6.3）。
- 型：`str` / `int` / `float` / `bool` / `datetime` / `json`

## participants

| 列名 | 型 | 欠損 | 説明 |
| --- | --- | --- | --- |
| `participant_id` | str | 不可 | 仮名化した参加者ID（ランダム生成。個人と対応付ける表は別管理） |
| `experiment_id` | str | 不可 | 実験定義のID（`experiments/*.yaml`） |
| `condition_id` | str | 不可 | 割り当てられた条件ID |
| `order_index` | int | 不可 | 本課題の出題順（ラテン方格の回転番号、0始まり）。均等化しない実験では 0 |
| `assignment_method` | str | 不可 | 割当方法。`balanced_cells`（条件 × 出題順のセルのうち最少人数のセル、同数なら seed で無作為） |
| `assignment_seed` | int | 不可 | 同数セルからの選択に使った乱数 seed |
| `consent_status` | str | 不可 | 常に `agreed`。参加者レコードは同意時にのみ作成し、同意前・不同意の参加者は保存しない（§12.1） |
| `consented_at` | datetime | 可 | 同意した時刻 |
| `status` | str | 不可 | `in_progress` / `completed` / `aborted`。再読み込み・別タブで中断した場合は `aborted`。タブを閉じて戻らなかった参加者は `in_progress` のまま残る（割当の集計では実験定義の `abandon_after_min` を過ぎると数えない） |
| `created_at` | datetime | 不可 | 参加者レコード作成時刻 |
| `completed_at` | datetime | 可 | 終了画面に到達した時刻 |
| `aborted_at` | datetime | 可 | 中断を検知した時刻（再読み込み後に同じURLが開かれた時刻） |
| `abort_reason` | str | 可 | 中断の理由。`reload`（再読み込み・別タブ） |
| `app_version` | str | 不可 | 実施時のアプリバージョン |
| `config_hash` | str | 不可 | 実施時の実験定義・問題文の内容ハッシュ（再現用） |

## trials

| 列名 | 型 | 欠損 | 説明 |
| --- | --- | --- | --- |
| `trial_id` | str | 不可 | 試行ID |
| `submission_id` | str | 不可 | 回答送信の冪等キー。同一キーの再送は行を増やさない |
| `participant_id` | str | 不可 | 参加者ID |
| `experiment_id` | str | 不可 | 実験ID |
| `condition_id` | str | 不可 | 条件ID |
| `task_id` | str | 不可 | 問題ID（例：`linda`） |
| `variant_id` | str | 不可 | 版の種類（例：`standard`、`frequency`） |
| `task_version` | int | 不可 | 問題文バージョン。`task_id/variant_id@task_version` で提示内容を復元できる |
| `presentation_order` | int | 不可 | 参加者内での提示順（1始まり） |
| `is_practice` | bool | 不可 | 練習課題なら true（分析から除外） |
| `response_format` | str | 不可 | `choice` / `numeric` |
| `time_limit_sec` | float | 可 | この試行に適用した制限時間（秒）。制限なし・見直しは空 |
| `show_countdown` | bool | 不可 | 残り時間を表示したか（制限の有無とは独立）。見直しでは false |
| `attempt` | str | 不可 | `initial`（初回回答）/ `revised`（見直し後の回答。見直しあり条件のみ） |
| `initial_trial_id` | str | 可 | 見直し後の行で、対応する初回回答の `trial_id`。初回の行では空 |
| `shown_at_server` | datetime | 不可 | サーバー側で問題を表示した時刻 |
| `submitted_at_server` | datetime | 可 | サーバー側で回答を受信した時刻。時間切れは空 |
| `shown_at_client_ms` | float | 可 | ブラウザ側の表示時刻（相対ms）。取得できない場合は空 |
| `submitted_at_client_ms` | float | 可 | ブラウザ側の回答確定時刻（相対ms） |
| `response_time_ms` | float | 可 | 表示から回答確定までの時間。フェーズ1はサーバー側の単調時計で計測し、通信・再描画の遅延を含む。時間切れは空 |
| `outcome` | str | 不可 | `answered` / `timeout` / `skipped` / `aborted`。時間切れ・未回答を誤答と区別する |
| `choice_id` | str | 可 | 選択式の回答。数値入力式・時間切れは空（制限時間後の送信も回答として扱わない） |
| `response_value` | float | 可 | 数値入力式の回答値（全角数字・桁区切り・「円」を正規化した値）。選択式・時間切れは空 |
| `is_correct` | bool | 可 | 正誤。`outcome=answered` かつ正答定義がある版のみ設定し、それ以外は空 |
| `confidence` | int | 可 | 確信度（1〜実験定義の `confidence_levels`）。取得しない条件・時間切れ・確信度画面で離脱した場合は空 |
| `confidence_timing` | str | 可 | `before` / `after`。取得しない条件では空 |
| `revision_count` | int | 可 | 選択式で、確定前に選択を変更した回数（最初の選択は数えない。見直しで初回回答が選択済みの場合は最初の変更から数える）。数値入力式はフェーズ1では計測できないため空（Enter 送信のためフォーム化しており、途中の入力がサーバーに届かない） |
| `duplicate_submission_count` | int | 不可 | 同一 `submission_id` で重複送信を検知した回数 |

## events

| 列名 | 型 | 欠損 | 説明 |
| --- | --- | --- | --- |
| `event_id` | str | 不可 | イベントID |
| `trial_id` | str | 不可 | 対応する試行ID |
| `participant_id` | str | 不可 | 参加者ID |
| `event_type` | str | 不可 | `mousemove` / `click` / `choice_change` / `focus` / `blur` / `visibility` など |
| `t_client_ms` | float | 不可 | ブラウザ側相対時刻（ms） |
| `x_norm` | float | 可 | 問題表示領域を基準に 0–1 へ正規化した X 座標 |
| `y_norm` | float | 可 | 同 Y 座標 |
| `target_id` | str | 可 | 対象要素（選択肢IDなど） |
| `payload` | json | 可 | 上記以外の付随情報。直接識別情報を入れない |

## experiment_status_log

受付状態の切替履歴（追記のみ）。実験ごとの最新の行が現在の状態。行がない実験は受付停止。

| 列名 | 型 | 欠損 | 説明 |
| --- | --- | --- | --- |
| `log_id` | str | 不可 | ログID |
| `experiment_id` | str | 不可 | 実験ID |
| `accepting` | bool | 不可 | true = 受付中、false = 停止 |
| `changed_at` | datetime | 不可 | 切り替えた時刻 |
