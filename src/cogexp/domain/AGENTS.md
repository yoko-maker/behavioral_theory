# src/cogexp/domain/ — 純粋ロジック

- 標準ライブラリと `pydantic` 以外に依存しない。`streamlit` / `pandas` / `sqlite3` / 他の `cogexp` サブパッケージを import しない（`check` が検出する）。
- 現在時刻は `clock.Clock` を引数で受け取る。`time.time()` や `datetime.now()` を直接呼ばない。
- 乱数（条件割当・出題順・選択肢順）は seed を受け取る関数に閉じ込め、seed を保存できる形にする。`random` の import は割当モジュール（`assignment.py`）に限定する。
- 時間切れ・未回答・中断は `Outcome` で区別する。誤答 (`is_correct=False`) に畳み込まない。
- ここに追加したロジックには必ず単体テスト（`tests/domain/`）を書く。UI なしでテストできることがこの層の存在理由。
