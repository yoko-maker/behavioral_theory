"""操作ログ（events）から試行ごとの指標とログ取得状況を求める（概要書 §10）。

指標は回答形式で分ける（docs/plans/phase3.md）。
- 選択式：マウス軌跡の指標（``choice_metrics``）
- 数値入力式：キー操作の時間の指標（``numeric_metrics``）。カーソルは入力欄に向かうだけで、
  軌跡から判断の過程はほとんど読み取れないため

指標の定義は docs/plans/phase3.md に固定している。結果を見てから定義を変えないこと。
軌跡長は問題領域の大きさ（panel_w / panel_h）を掛けて CSS px に戻してから求める
（x と y で正規化の基準が異なるため）。
"""

from __future__ import annotations

import math
from itertools import pairwise

import numpy as np
import pandas as pd

X_FLIP_MIN_STEP = 0.01  # x 方向の移動をこれ未満なら無視する（正規化座標）

NUMERIC_METRIC_COLUMNS = [
    "trial_id",
    "最初の入力まで_ms",
    "入力中の最長の間_ms",
    "最後の入力から確定まで_ms",
    "入力操作数",
    "削除操作数",
    "非表示時間_ms",
]

# 確信度の画面の指標（定義は docs/plans/confidence_metrics_definition.md で確定）
DWELL_MIN_MS = 200.0  # T_dwell：この時間以上止まっていたら「立ち止まった」
STOP_MAX_PX_PER_S = 50.0  # V_stop：この速さ未満を「止まっている」とみなす（CSS px/秒）

CONFIDENCE_METRIC_COLUMNS = [
    "trial_id",
    "確信度",
    # 主
    "選び直し",
    "確信度の回答時間_ms",
    "回答時間_本人比",
    # 補助
    "立ち止まった段階の数",
    "立ち止まり_本人差",
    # 記述のみ
    "他の段階への進入",
    "x方向転換",
    "移動点数",
    "手の動きの量_px毎秒",
]

METRIC_COLUMNS = [
    "trial_id",
    "移動点数",
    "軌跡長_px",
    "x方向転換",
    "初動時間_ms",
    "選択肢への進入",
    "最終回答以外への進入",
    "非表示時間_ms",
]


def phase_events(events: pd.DataFrame, phase: str) -> pd.DataFrame:
    """回答の画面（answer）または確信度の画面（confidence）の操作だけを取り出す。

    確信度の画面の操作も評価対象の試行と同じ trial_id で保存しているため、集計では必ず分ける。
    """
    return events[events["phase"] == phase]


def moves_of(events: pd.DataFrame, trial_id: str, phase: str = "answer") -> pd.DataFrame:
    """1試行の移動点（時刻順）。"""
    events = phase_events(events, phase)
    ev = events[(events["trial_id"] == trial_id) & (events["event_type"] == "move")]
    ev = ev.dropna(subset=["x_norm", "y_norm"])
    return ev.sort_values("t_client_ms")[["t_client_ms", "x_norm", "y_norm"]]


def layout_of(events: pd.DataFrame, trial_id: str) -> dict[str, list[float]]:
    """回答の画面の表示直後に記録した要素の矩形（正規化座標 [x0, y0, x1, y1]）。"""
    events = phase_events(events, "answer")
    ev = events[(events["trial_id"] == trial_id) & (events["event_type"] == "layout")]
    for payload in ev["payload"]:
        if isinstance(payload, dict) and isinstance(payload.get("rects"), dict):
            return {str(k): list(v) for k, v in payload["rects"].items()}
    return {}


def _x_flips(xs: np.ndarray) -> int:
    flips = 0
    direction = 0
    for dx in np.diff(xs):
        if abs(dx) < X_FLIP_MIN_STEP:
            continue
        d = 1 if dx > 0 else -1
        if direction and d != direction:
            flips += 1
        direction = d
    return flips


def hidden_ms(ev: pd.DataFrame, end_ms: float) -> float:
    hidden_since: float | None = None
    total = 0.0
    for _, row in ev[ev["event_type"] == "visibility"].sort_values("t_client_ms").iterrows():
        state = row["payload"].get("state") if isinstance(row["payload"], dict) else None
        if state == "hidden" and hidden_since is None:
            hidden_since = float(row["t_client_ms"])
        elif state == "visible" and hidden_since is not None:
            total += float(row["t_client_ms"]) - hidden_since
            hidden_since = None
    if hidden_since is not None:
        total += max(0.0, end_ms - hidden_since)
    return total


def _logged(trials: pd.DataFrame, response_format: str) -> pd.DataFrame:
    return trials[
        (trials["client_log_status"] == "ok") & (trials["response_format"] == response_format)
    ]


def _by_trial(events: pd.DataFrame, phase: str = "answer") -> dict[object, pd.DataFrame]:
    events = phase_events(events, phase)
    return dict(tuple(events.groupby("trial_id"))) if not events.empty else {}


def numeric_metrics(trials: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """数値入力式の試行（ログあり）ごとのキー操作の時間の指標。"""
    rows: list[dict[str, object]] = []
    grouped = _by_trial(events)
    for _, t in _logged(trials, "numeric").iterrows():
        ev = grouped.get(t["trial_id"], events.iloc[0:0])
        edits = ev[ev["event_type"] == "input_edit"].sort_values("t_client_ms")
        times = edits["t_client_ms"].to_numpy(dtype=float)
        ops = [p.get("op") if isinstance(p, dict) else None for p in edits["payload"]]
        shown = t["shown_at_client_ms"]
        submit = ev[ev["event_type"] == "submit"]["t_client_ms"]
        end_ms = float(ev["t_client_ms"].max()) if len(ev) else 0.0
        rows.append(
            {
                "trial_id": t["trial_id"],
                "最初の入力まで_ms": (
                    float(times[0]) - float(shown) if len(times) and pd.notna(shown) else math.nan
                ),
                "入力中の最長の間_ms": float(np.max(np.diff(times)))
                if len(times) >= 2
                else math.nan,
                "最後の入力から確定まで_ms": (
                    float(submit.max()) - float(times[-1])
                    if len(times) and len(submit) and t["outcome"] == "answered"
                    else math.nan
                ),
                "入力操作数": len(times),
                "削除操作数": sum(op == "delete" for op in ops),
                "非表示時間_ms": hidden_ms(ev, end_ms),
            }
        )
    return pd.DataFrame(rows, columns=NUMERIC_METRIC_COLUMNS)


def _scale_rects(ev: pd.DataFrame) -> dict[str, list[float]]:
    """確信度の画面の各段階の枠（段階の数字 -> 正規化座標の矩形）。"""
    for payload in ev[ev["event_type"] == "layout"]["payload"]:
        if isinstance(payload, dict) and isinstance(payload.get("rects"), dict):
            return {
                str(k).split(":", 1)[1]: list(v)
                for k, v in payload["rects"].items()
                if str(k).startswith("choice:")
            }
    return {}


def _box_at(x: float, y: float, rects: dict[str, list[float]]) -> str | None:
    for label, (x0, y0, x1, y1) in rects.items():
        if x0 <= x <= x1 and y0 <= y <= y1:
            return label
    return None


def count_dwells(
    moves: pd.DataFrame, rects: dict[str, list[float]], panel_w: float, panel_h: float
) -> dict[str, int]:
    """段階ごとの「立ち止まった」回数。

    同じ枠の中で、速さ STOP_MAX_PX_PER_S 未満の移動が合計 DWELL_MIN_MS 以上続いたら1回。
    速くなる・枠を出ると数え直す（同じ枠で2回止まれば2回）。カーソルが静止している間は
    移動が記録されないため、次の移動までの時間も「止まっていた時間」に含まれる。
    """
    counts: dict[str, int] = {}
    current: str | None = None
    held = 0.0
    counted = False
    pts = list(zip(moves["t_client_ms"], moves["x_norm"], moves["y_norm"], strict=True))
    for (t0, x0, y0), (t1, x1, y1) in pairwise(pts):
        dt = float(t1) - float(t0)
        if dt <= 0:
            continue
        speed = math.hypot((x1 - x0) * panel_w, (y1 - y0) * panel_h) / (dt / 1000.0)
        box = _box_at(x0, y0, rects)
        if speed < STOP_MAX_PX_PER_S and box is not None and box == _box_at(x1, y1, rects):
            if box != current:
                current, held, counted = box, 0.0, False
            held += dt
            if held >= DWELL_MIN_MS and not counted:
                counts[box] = counts.get(box, 0) + 1
                counted = True
        else:
            current, held, counted = None, 0.0, False
    return counts


def confidence_metrics(trials: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """確信度の画面の操作ログがある試行ごとの指標。

    定義と位置づけ（主・補助・記述のみ）は docs/plans/confidence_metrics_definition.md。
    迷いと関係しうる手がかりであり、迷いそのものの測定ではない。手の動きの個人差を減らすため、
    同じ参加者の練習課題の確信度の画面を基準にした補正値も出す。
    移動が1件もない（キーボード・タッチのみ等）場合、軌跡由来の指標は欠損（0 ではない）。
    """
    rows: list[dict[str, object]] = []
    grouped = _by_trial(events, "confidence")
    logged = trials[trials["confidence_client_log_status"] == "ok"]
    for _, t in logged.iterrows():
        ev = grouped.get(t["trial_id"], events.iloc[0:0])
        mv = ev[ev["event_type"] == "move"].dropna(subset=["x_norm", "y_norm"])
        mv = mv.sort_values("t_client_ms")
        chosen = str(int(t["confidence"])) if pd.notna(t["confidence"]) else None
        w, h = t["confidence_panel_w"], t["confidence_panel_h"]
        measurable = len(mv) > 0
        dwell_count = math.nan
        path_px = math.nan
        if measurable and pd.notna(w) and pd.notna(h):
            dwells = count_dwells(mv, _scale_rects(ev), float(w), float(h))
            dwell_count = float(sum(n for k, n in dwells.items() if k != chosen))
            xs = mv["x_norm"].to_numpy(dtype=float)
            ys = mv["y_norm"].to_numpy(dtype=float)
            path_px = float(np.sum(np.hypot(np.diff(xs) * float(w), np.diff(ys) * float(h))))
        enters = ev[ev["event_type"] == "choice_enter"]
        rows.append(
            {
                "trial_id": t["trial_id"],
                "participant_id": t["participant_id"],
                "is_practice": bool(t["is_practice"]),
                "確信度": t["confidence"],
                "選び直し": t["confidence_revision_count"],
                "確信度の回答時間_ms": t["confidence_rt_client_ms"],
                "立ち止まった段階の数": dwell_count,
                "他の段階への進入": (
                    int((enters["target_id"] != chosen).sum()) if measurable else math.nan
                ),
                "x方向転換": (
                    _x_flips(mv["x_norm"].to_numpy(dtype=float)) if measurable else math.nan
                ),
                "移動点数": len(mv),
                "_path_px": path_px,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=CONFIDENCE_METRIC_COLUMNS)

    # 本人の基準：同じ参加者の練習課題の確信度の画面（定義 §5・§6）
    practice = df[df["is_practice"]].groupby("participant_id")
    rt_base = practice["確信度の回答時間_ms"].mean()
    dwell_base = practice["立ち止まった段階の数"].mean()
    movement = practice["_path_px"].sum(min_count=1) / (
        practice["確信度の回答時間_ms"].sum(min_count=1) / 1000.0
    )
    pid = df["participant_id"]
    main = ~df["is_practice"]
    df["回答時間_本人比"] = (df["確信度の回答時間_ms"] / pid.map(rt_base)).where(main)
    df["立ち止まり_本人差"] = (df["立ち止まった段階の数"] - pid.map(dwell_base)).where(main)
    df["手の動きの量_px毎秒"] = pid.map(movement)
    return df[CONFIDENCE_METRIC_COLUMNS]


def choice_metrics(trials: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """選択式の試行（ログあり）ごとのマウス軌跡の指標。"""
    rows: list[dict[str, object]] = []
    ok = _logged(trials, "choice")
    grouped = _by_trial(events)
    for _, t in ok.iterrows():
        ev = grouped.get(t["trial_id"], events.iloc[0:0])
        mv = ev[ev["event_type"] == "move"].dropna(subset=["x_norm", "y_norm"])
        mv = mv.sort_values("t_client_ms")
        xs = mv["x_norm"].to_numpy(dtype=float)
        ys = mv["y_norm"].to_numpy(dtype=float)
        w, h = t["panel_w"], t["panel_h"]
        if len(xs) >= 2 and pd.notna(w) and pd.notna(h):
            length = float(np.sum(np.hypot(np.diff(xs) * w, np.diff(ys) * h)))
        else:
            length = 0.0 if len(xs) < 2 else math.nan
        shown = t["shown_at_client_ms"]
        first_move = (
            float(mv["t_client_ms"].iloc[0]) - float(shown)
            if len(mv) and pd.notna(shown)
            else math.nan
        )
        enters = ev[ev["event_type"] == "choice_enter"]
        final = t["choice_id"]
        end_ms = float(ev["t_client_ms"].max()) if len(ev) else 0.0
        rows.append(
            {
                "trial_id": t["trial_id"],
                "移動点数": len(mv),
                "軌跡長_px": length,
                "x方向転換": _x_flips(xs),
                "初動時間_ms": first_move,
                "選択肢への進入": len(enters),
                "最終回答以外への進入": (
                    int((enters["target_id"] != final).sum()) if pd.notna(final) else len(enters)
                ),
                "非表示時間_ms": hidden_ms(ev, end_ms),
            }
        )
    return pd.DataFrame(rows, columns=METRIC_COLUMNS)


def log_quality(trials: pd.DataFrame) -> pd.DataFrame:
    """ブラウザ・OS・入力の種類ごとのログ取得状況（概要書 §13 フェーズ3）。"""
    if trials.empty:
        return pd.DataFrame(
            columns=[
                "browser_family",
                "os_family",
                "pointer_types",
                "試行数",
                "ログ取得率",
                "イベント数中央値",
            ]
        )
    df = trials.assign(
        ok=trials["client_log_status"] == "ok",
        browser_family=trials["browser_family"].fillna("（不明）"),
        os_family=trials["os_family"].fillna("（不明）"),
        pointer_types=trials["pointer_types"].fillna("（不明）").replace("", "（なし）"),
    )
    g = df.groupby(["browser_family", "os_family", "pointer_types"])
    out = pd.DataFrame(
        {
            "試行数": g.size(),
            "ログ取得率": g["ok"].mean(),
            "イベント数中央値": g["n_events"].median(),
        }
    )
    return out.reset_index()
