"""分析の前処理：分析用の回答時間・非表示時間・除外の判定（docs/plans/phase4.md §3）。

除外基準はデータを見る前に固定している。結果を見てから閾値を変えないこと。
生データは変更せず、除外の判定は列として付け加える。
"""

from __future__ import annotations

import math

import pandas as pd

from cogexp.analysis.trajectory import hidden_ms, phase_events
from cogexp.domain.models import Experiment

HIDDEN_LIMIT_MS = 3_000.0  # E2：問題の表示中に非表示だった時間の合計がこれ以上なら除外
FAST_LIMIT_MS = 1_000.0  # E3：回答した試行で、分析用の回答時間がこれ未満なら除外

REASONS = {
    "E1": "中断・未完了の参加者",
    "E2": f"画面が {HIDDEN_LIMIT_MS / 1000:g} 秒以上非表示",
    "E3": f"回答時間が {FAST_LIMIT_MS / 1000:g} 秒未満",
}


def _hidden_by_trial(trials: pd.DataFrame, events: pd.DataFrame) -> dict[object, float]:
    answer = phase_events(events, "answer")
    grouped = dict(tuple(answer.groupby("trial_id"))) if not answer.empty else {}
    out: dict[object, float] = {}
    for _, t in trials.iterrows():
        if t["client_log_status"] != "ok":
            continue  # 判定不能（NaN のまま）
        ev = grouped.get(t["trial_id"], answer.iloc[0:0])
        end_ms = float(ev["t_client_ms"].max()) if len(ev) else 0.0
        out[t["trial_id"]] = hidden_ms(ev, end_ms)
    return out


def analysis_frame(
    experiment: Experiment,
    participants: pd.DataFrame,
    trials: pd.DataFrame,
    events: pd.DataFrame,
) -> pd.DataFrame:
    """実験の本課題の試行（初回・見直し）に、要因・分析用の回答時間・除外の判定を付ける。

    追加する列：
    - ``factor_<要因名>``：条件の要因の水準
    - ``rt_analysis_ms`` / ``rt_source``：分析用の回答時間と、その出どころ（client / server）
    - ``hidden_ms``：問題の表示中に非表示だった時間（操作ログがなければ NaN = 判定不能）
    - ``exclusion``：最初に該当した除外理由（E1〜E3）。該当なしは None
    """
    t = trials[(trials["experiment_id"] == experiment.experiment_id) & ~trials["is_practice"]]
    t = t.copy()
    status = participants.set_index("participant_id")["status"]
    t["participant_status"] = t["participant_id"].map(status)

    factors = {c.condition_id: c.factors for c in experiment.conditions}
    names = sorted({k for f in factors.values() for k in f})
    for name in names:
        t[f"factor_{name}"] = t["condition_id"].map(lambda c, n=name: factors.get(c, {}).get(n))

    client_rt = t["submitted_at_client_ms"] - t["shown_at_client_ms"]
    use_client = (t["client_log_status"] == "ok") & client_rt.notna()
    t["rt_analysis_ms"] = client_rt.where(use_client, t["response_time_ms"])
    t["rt_source"] = use_client.map({True: "client", False: "server"}).where(
        t["rt_analysis_ms"].notna()
    )

    t["hidden_ms"] = t["trial_id"].map(_hidden_by_trial(t, events)).astype(float)

    def reason(row: pd.Series) -> str | None:
        if row["participant_status"] != "completed":
            return "E1"
        h = row["hidden_ms"]
        if not (isinstance(h, float) and math.isnan(h)) and h >= HIDDEN_LIMIT_MS:
            return "E2"
        rt = row["rt_analysis_ms"]
        if row["outcome"] == "answered" and pd.notna(rt) and rt < FAST_LIMIT_MS:
            return "E3"
        return None

    t["exclusion"] = pd.Series(
        [reason(row) for _, row in t.iterrows()], index=t.index, dtype=object
    )
    t["included"] = t["exclusion"].isna()
    return t


def exclusion_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """条件ごとの除外件数（初回回答のみ）と、非表示時間を判定できなかった件数。"""
    initial = frame[frame["attempt"] == "initial"]
    rows = []
    for cond, g in initial.groupby("condition_id"):
        row: dict[str, object] = {"condition_id": cond, "試行数": len(g)}
        for code, label in REASONS.items():
            row[f"{code} {label}"] = int((g["exclusion"] == code).sum())
        row["分析対象"] = int(g["included"].sum())
        row["非表示時間を判定不能（ログなし・除外せず）"] = int(
            (g["included"] & g["hidden_ms"].isna()).sum()
        )
        rows.append(row)
    return pd.DataFrame(rows)
