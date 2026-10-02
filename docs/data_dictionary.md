# データ辞書

保存される全項目の定義。`src/cogexp/storage/schema.py` と一致していることを `dev.py check` が検査する。
表の形式（列名をバッククォートで囲む・型・欠損「可/不可」・説明）を崩さないこと。

- 時刻（datetime）はすべて UTC の ISO 8601 で保存する。
- `*_client_ms` と `events.t_client_ms` はブラウザ側の `performance.now()`（ページを開いた時点からの ms）で、サーバー時刻とは別系列（概要書 §6.3）。同じ参加者のページ内では比較できる。
- ブラウザ側の回答時間は `submitted_at_client_ms - shown_at_client_ms` で求める（通信遅延を含まない）。
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
| `shown_at_client_ms` | float | 可 | ブラウザ側で問題画面を表示した時刻。ブラウザから何も届かなかった場合は空 |
| `submitted_at_client_ms` | float | 可 | ブラウザ側で回答を確定した時刻。時間切れは空 |
| `response_time_ms` | float | 可 | 表示から回答確定までの時間。フェーズ1はサーバー側の単調時計で計測し、通信・再描画の遅延を含む。時間切れは空 |
| `outcome` | str | 不可 | `answered` / `timeout` / `skipped` / `aborted`。時間切れ・未回答を誤答と区別する |
| `choice_id` | str | 可 | 選択式の回答。数値入力式・時間切れは空（制限時間後の送信も回答として扱わない） |
| `response_value` | float | 可 | 数値入力式の回答値（全角数字・桁区切り・「円」を正規化した値）。選択式・時間切れは空 |
| `is_correct` | bool | 可 | 正誤。`outcome=answered` かつ正答定義がある版のみ設定し、それ以外は空 |
| `confidence` | int | 可 | 確信度（1〜実験定義の `confidence_levels`）。取得しない条件・時間切れ・確信度画面で離脱した場合は空 |
| `confidence_timing` | str | 可 | `before` / `after`。取得しない条件では空 |
| `confidence_rt_client_ms` | float | 可 | 確信度の画面を表示してから確信度を確定するまでの時間（ブラウザ側で計測）。確信度を取得しない場合・ブラウザから届かなかった場合は空 |
| `confidence_revision_count` | int | 可 | 確信度の画面で、最初の選択後に選び直した回数 |
| `confidence_client_log_status` | str | 可 | 確信度の画面の操作ログの状態（`ok` / `missing`）。確信度を取得しない場合は空 |
| `confidence_n_events` | int | 可 | 確信度の画面で保存した操作イベントの数 |
| `revision_count` | int | 可 | ブラウザで数えた変更回数。選択式は最初の選択後に選択を変えた回数（見直しで初回回答が選択済みの場合は最初の変更から数える）。数値入力式は文字を削除した操作の回数。ブラウザから届かなかった場合は空（2026-10-02 以前のデータでは数値入力式は常に空） |
| `duplicate_submission_count` | int | 不可 | 同一 `submission_id` で重複送信を検知した回数 |
| `client_log_status` | str | 不可 | `ok`（ブラウザから操作ログが届いた）/ `missing`（届かずサーバー側だけで記録した。例：ブラウザの時間切れ通知が届かないままサーバーが時間切れにした） |
| `n_events` | int | 不可 | この試行で保存した操作イベントの数 |
| `browser_family` | str | 可 | ブラウザの種類（`chrome` / `edge` / `firefox` / `safari` / `other`）。識別文字列全体は保存しない |
| `os_family` | str | 可 | OS の種類（`windows` / `macos` / `ios` / `android` / `linux` / `other`） |
| `pointer_types` | str | 可 | この試行で使われた入力の種類（`mouse` / `touch` / `pen` をカンマ区切り） |
| `viewport_w` | int | 可 | ブラウザの表示領域の幅（CSS px） |
| `viewport_h` | int | 可 | 同 高さ |
| `panel_w` | int | 可 | 問題領域（座標正規化の基準）の幅（CSS px） |
| `panel_h` | int | 可 | 同 高さ |
| `device_pixel_ratio` | float | 可 | 画素比（高解像度画面で 2 など） |

## events

| 列名 | 型 | 欠損 | 説明 |
| --- | --- | --- | --- |
| `event_id` | str | 不可 | イベントID |
| `trial_id` | str | 不可 | 対応する試行ID |
| `participant_id` | str | 不可 | 参加者ID |
| `phase` | str | 不可 | どの画面の操作か。`answer`（回答の画面）/ `confidence`（確信度の画面）。確信度の画面の操作も評価対象の試行の `trial_id` で保存するため、集計では必ずこの列で分ける |
| `event_type` | str | 不可 | `layout`（表示直後の要素位置）/ `move`（画面更新ごとの移動）/ `pointerdown` / `choice_change` / `choice_enter` / `choice_leave` / `key`（種類のみ）/ `input_edit` / `invalid_submit` / `visibility` / `window_blur` / `window_focus` / `submit` / `timeout`。許可リストは `src/cogexp/domain/client_log.py` |
| `t_client_ms` | float | 不可 | ブラウザ側相対時刻（ms） |
| `x_norm` | float | 可 | 問題領域を基準に 0–1 へ正規化した X 座標（領域外は 0 未満・1 超）。座標を持たないイベントは空 |
| `y_norm` | float | 可 | 同 Y 座標 |
| `target_id` | str | 可 | 対象要素（選択肢ID、確信度の画面では段階の数字 `1`〜、`input` / `submit` など） |
| `payload` | json | 可 | 種別ごとの付随情報（`layout` の要素矩形、`key` の種類、`input_edit` の操作、`pointerdown` の入力の種類など）。キーの内容・入力した文字は入れない |

## experiment_status_log

受付状態の切替履歴（追記のみ）。実験ごとの最新の行が現在の状態。行がない実験は受付停止。

| 列名 | 型 | 欠損 | 説明 |
| --- | --- | --- | --- |
| `log_id` | str | 不可 | ログID |
| `experiment_id` | str | 不可 | 実験ID |
| `accepting` | bool | 不可 | true = 受付中、false = 停止 |
| `changed_at` | datetime | 不可 | 切り替えた時刻 |
