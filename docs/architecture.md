# アーキテクチャ

## レイヤと依存方向

```text
app/ (Streamlit UI)
  │  画面描画・入力・session_state
  ▼
cogexp.service（参加者セッションの進行：採点・時間切れ判定・保存行の組み立て）
  │
  ▼
cogexp.config ──► cogexp.domain ◄── cogexp.storage ◄── cogexp.analysis
 YAML読込          純粋ロジック        保存スキーマ         集計・前処理
                   (pydantic のみ)     リポジトリ           (pandas)
```

- 矢印は「import してよい方向」。`domain` はどこにも依存しない。
- `app/` だけが `streamlit` を import できる。参加者フローの app は `cogexp.service` を呼んで描画するだけにする。
- 依存ルールは `scripts/checks/architecture.py` が強制する（`dev.py check` に含まれる）。

| ルールID | 内容 |
| --- | --- |
| `domain-purity` | domain は標準ライブラリと pydantic のみ |
| `no-ui-in-core` | `src/cogexp/` で streamlit を import しない |
| `storage-independent` | storage は analysis / config に依存しない |
| `app-uses-repository` | app から `sqlite3` / `csv` を直接使わない |
| `injected-clock` | 現在時刻は `domain/clock.py` の Clock 経由のみ |
| `seeded-random` | 乱数は `domain/assignment.py` のみ（seed を保存） |

## 主要な設計判断

### 問題文の版管理

問題は `task_id/variant_id@version` で一意。`experiments/versions.lock.json` に内容ハッシュを記録し、
公開済みの版の書き換え・削除を `check` で検出する。保存データの `task_version` から提示内容を必ず復元できる。

### 時刻

- 記録用のサーバー時刻（UTC）と、ブラウザ側の相対時刻（`performance.now()`）を別列で保存する。
- 時間切れ判定は domain のロジックで行い、Clock を注入してテストする。
- Streamlit はサーバー往復でしか状態が更新されないため、カウントダウン表示や正確な回答時間の取得は
  フェーズ3のカスタムコンポーネント（JavaScript）で補う。フェーズ1ではサーバー時刻ベースで記録し、
  その限界をデータ辞書と分析出力に明記する。

### Streamlit の再実行モデルへの対処

- 画面遷移は domain の状態機械（説明→同意→操作説明→練習→本課題→確信度→終了）で表現し、
  app はその状態を `st.session_state` に保持して描画するだけにする。
- 回答確定は `submission_id` による冪等書き込みで、再実行・二重クリックによる重複行を防ぐ。

### 保存

フェーズ1は SQLite（`data/` 配下、git 管理外）。リポジトリ関数のインターフェースを保てば
PostgreSQL 等への移行は storage 層の差し替えで済む。CSV 出力は analysis 層から行う。
