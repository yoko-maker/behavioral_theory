# app/ — Streamlit UI 層

- この層は「表示」と「入力の受け渡し」だけを担う。採点・出題順・時間切れ判定・保存形式の決定は `cogexp.domain` / `cogexp.storage` に置き、ここから呼び出す。
- `sqlite3` / `csv` を直接 import しない。保存は `cogexp.storage` のリポジトリ経由で行う（`check` が検出する）。
- `st.session_state` のキーは `app/state.py` に定数として集約し、文字列リテラルを散在させない。
- Streamlit は操作のたびにスクリプト全体を再実行する。回答確定・保存処理は冪等にし、`submission_id` で二重送信を検出できるようにする（概要書 §6.2）。
- 実験条件間で見た目が変わらないようにする。条件による差分は条件設定（YAML）由来の項目に限定する。
- 実験者画面はアクセス制限を前提に実装する（参加者フローから到達できないこと）。
- 画面フローを変えたら `tests/app/` の AppTest を更新する。
- 課題画面は `components/trial_panel.*`（JavaScript の部品）で描画する。部品からの送信値は未検証の入力なので、`cogexp.service.ParticipantService.handle_client` に渡して検証させる。app 側で中身を解釈しない。
- 部品が送るイベント種別を増やすときは `cogexp.domain.client_log.EVENT_TYPES` とデータ辞書も更新する（`tests/harness/test_trial_panel_js.py` が不一致を検出する）。数値の解釈規則を変えるときは JS とサーバーの両方を変える（同テストが一致を検査する）。
- 部品内の文字列は `textContent` で表示する。`innerHTML` に問題文などを入れない。
