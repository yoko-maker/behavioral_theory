"""探索的分析の表（docs/plans/phase4.md §4）。

入力は ``preprocess.analysis_frame`` の結果。除外された試行（``included = False``）は使わない。
問題（task_id）ごとに分けて分析する。要因は ``factor_wording`` / ``factor_time_limit``。
"""

from __future__ import annotations

import math

import pandas as pd

from cogexp.analysis.stats import (
    logistic_2x2,
    mann_whitney,
    mcnemar_exact_p,
    mean_ci,
    median_ci,
    newcombe_diff_ci,
    wilson_ci,
)

WORDING = "factor_wording"
TIME_LIMIT = "factor_time_limit"
LEVELS = {WORDING: ("standard", "reworded"), TIME_LIMIT: ("none", "limited")}
LABELS = {
    "standard": "標準",
    "reworded": "言い換え",
    "none": "制限なし",
    "limited": "制限あり",
}


def has_factors(frame: pd.DataFrame) -> bool:
    return WORDING in frame.columns and TIME_LIMIT in frame.columns


def _initial(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[(frame["attempt"] == "initial") & frame["included"]]


def _keys(frame: pd.DataFrame) -> list[str]:
    return ["task_id", "condition_id"] + ([WORDING, TIME_LIMIT] if has_factors(frame) else [])


def accuracy_table(frame: pd.DataFrame) -> pd.DataFrame:
    """問題 × 条件の正答率・時間切れ率（Wilson の 95% 信頼区間）。"""
    rows = []
    for key, g in _initial(frame).groupby(_keys(frame), dropna=False):
        scorable = g[g["is_correct"].notna()]
        k = int(scorable["is_correct"].astype(bool).sum())
        n = len(scorable)
        timeouts = int((g["outcome"] == "timeout").sum())
        lo, hi = wilson_ci(k, n)
        tlo, thi = wilson_ci(timeouts, len(g))
        rows.append(
            dict(zip(_keys(frame), key, strict=True))
            | {
                "試行数": len(g),
                "判定可能": n,
                "正答": k,
                "正答率": k / n if n else math.nan,
                "正答率95%CI下限": lo,
                "正答率95%CI上限": hi,
                "時間切れ": timeouts,
                "時間切れ率": timeouts / len(g) if len(g) else math.nan,
                "時間切れ率95%CI下限": tlo,
                "時間切れ率95%CI上限": thi,
            }
        )
    return pd.DataFrame(rows)


def wording_differences(frame: pd.DataFrame) -> pd.DataFrame:
    """時間制限の水準ごとの、正答率の差（言い換え − 標準）と Newcombe の 95% 信頼区間。"""
    if not has_factors(frame):
        return pd.DataFrame()
    rows = []
    data = _initial(frame)
    data = data[data["is_correct"].notna()]
    for (task, limit), g in data.groupby(["task_id", TIME_LIMIT]):
        counts = {}
        for level in LEVELS[WORDING]:
            s = g[g[WORDING] == level]["is_correct"].astype(bool)
            counts[level] = (int(s.sum()), len(s))
        (k1, n1), (k2, n2) = counts["reworded"], counts["standard"]
        d, lo, hi = newcombe_diff_ci(k1, n1, k2, n2)
        rows.append(
            {
                "task_id": task,
                "時間制限": LABELS.get(str(limit), limit),
                "言い換え n": n1,
                "標準 n": n2,
                "正答率の差（言い換え−標準）": d,
                "95%CI下限": lo,
                "95%CI上限": hi,
            }
        )
    return pd.DataFrame(rows)


def logistic_by_task(frame: pd.DataFrame) -> dict[str, pd.DataFrame | str]:
    """問題ごとの ``正答 ~ 表現 × 時間制限``（参照：標準・制限なし）。"""
    if not has_factors(frame):
        return {}
    data = _initial(frame)
    data = data[data["is_correct"].notna()].assign(correct=lambda d: d["is_correct"].astype(bool))
    out: dict[str, pd.DataFrame | str] = {}
    for task, g in data.groupby("task_id"):
        result = logistic_2x2(g, "correct", WORDING, "standard", TIME_LIMIT, "none")
        if isinstance(result, pd.DataFrame):
            result = result.assign(項=result["項"].map(_term_label))
        out[str(task)] = result
    return out


def _term_label(term: str) -> str:
    if term == "Intercept":
        return "切片（標準・制限なし）"
    parts = []
    if "factor_wording" in term:
        parts.append("言い換え")
    if "factor_time_limit" in term:
        parts.append("制限あり")
    return " × ".join(parts) + ("（交互作用）" if len(parts) == 2 else "")


def rt_table(frame: pd.DataFrame) -> pd.DataFrame:
    """回答した試行の回答時間：問題 × 条件の中央値と 95% 信頼区間（順序統計量）。"""
    rows = []
    data = _initial(frame)
    data = data[data["outcome"] == "answered"]
    for key, g in data.groupby(_keys(frame), dropna=False):
        med, lo, hi = median_ci(g["rt_analysis_ms"].astype(float).tolist())
        rows.append(
            dict(zip(_keys(frame), key, strict=True))
            | {"n": len(g), "中央値_ms": med, "95%CI下限": lo, "95%CI上限": hi}
        )
    return pd.DataFrame(rows)


def rt_tests(frame: pd.DataFrame) -> pd.DataFrame:
    """時間制限の水準ごとに、表現間の回答時間を比較（Mann–Whitney）。

    時間制限あり／なしの間は比較しない（制限ありでは回答時間が打ち切られるため）。
    """
    if not has_factors(frame):
        return pd.DataFrame()
    rows = []
    data = _initial(frame)
    data = data[data["outcome"] == "answered"]
    for (task, limit), g in data.groupby(["task_id", TIME_LIMIT]):
        x = g[g[WORDING] == "reworded"]["rt_analysis_ms"].astype(float).tolist()
        y = g[g[WORDING] == "standard"]["rt_analysis_ms"].astype(float).tolist()
        res = mann_whitney(x, y)
        rows.append(
            {
                "task_id": task,
                "時間制限": LABELS.get(str(limit), limit),
                "言い換え n": len(x),
                "標準 n": len(y),
                "U": res.u if res else math.nan,
                "p値": res.p if res else math.nan,
                "順位双列相関（正：言い換えが遅い）": res.rank_biserial if res else math.nan,
            }
        )
    return pd.DataFrame(rows)


def confidence_table(frame: pd.DataFrame) -> pd.DataFrame:
    """問題 × 条件ごとの、正答・誤答別の確信度の平均と 95% 信頼区間、およびその差。"""
    rows = []
    data = _initial(frame)
    data = data[data["is_correct"].notna() & data["confidence"].notna()]
    for key, g in data.groupby(_keys(frame), dropna=False):
        row = dict(zip(_keys(frame), key, strict=True))
        means = {}
        for label, flag in (("正答", True), ("誤答", False)):
            vals = g[g["is_correct"].astype(bool) == flag]["confidence"].astype(float).tolist()
            m, lo, hi = mean_ci(vals)
            means[label] = m
            row |= {
                f"{label} n": len(vals),
                f"{label} 平均": m,
                f"{label} 95%CI下限": lo,
                f"{label} 95%CI上限": hi,
            }
        row["差（正答−誤答）"] = means["正答"] - means["誤答"]
        rows.append(row)
    return pd.DataFrame(rows)


def revision_table(frame: pd.DataFrame) -> pd.DataFrame:
    """見直しの対（初回・見直し後とも分析対象）の回答変化率と、正答率の変化（McNemar）。"""
    initial = frame[frame["attempt"] == "initial"].set_index("trial_id")
    revised = frame[frame["attempt"] == "revised"]
    revised = revised[revised["initial_trial_id"].isin(initial.index)]
    if revised.empty:
        return pd.DataFrame()
    first = initial.loc[revised["initial_trial_id"]].reset_index()
    pairs = pd.DataFrame(
        {
            "task_id": revised["task_id"].to_numpy(),
            "condition_id": revised["condition_id"].to_numpy(),
            "included": revised["included"].to_numpy() & first["included"].to_numpy(),
            "changed": _answer(first).to_numpy() != _answer(revised).to_numpy(),
            "before": first["is_correct"].to_numpy(),
            "after": revised["is_correct"].to_numpy(),
        }
    )
    pairs = pairs[pairs["included"]]
    rows = []
    for (task, cond), g in pairs.groupby(["task_id", "condition_id"]):
        k, n = int(g["changed"].sum()), len(g)
        lo, hi = wilson_ci(k, n)
        both = g[g["before"].notna() & g["after"].notna()]
        w2r = int(((both["before"] == False) & (both["after"] == True)).sum())  # noqa: E712
        r2w = int(((both["before"] == True) & (both["after"] == False)).sum())  # noqa: E712
        rows.append(
            {
                "task_id": task,
                "condition_id": cond,
                "対の数": n,
                "変更": k,
                "回答変化率": k / n if n else math.nan,
                "95%CI下限": lo,
                "95%CI上限": hi,
                "誤→正": w2r,
                "正→誤": r2w,
                "McNemar p値": mcnemar_exact_p(w2r, r2w),
            }
        )
    return pd.DataFrame(rows)


def _answer(df: pd.DataFrame) -> pd.Series:
    text = df["choice_id"].where(df["choice_id"].notna(), df["response_value"].astype(str))
    return text.where(df["outcome"] == "answered", "（" + df["outcome"].astype(str) + "）")


def metric_medians(frame: pd.DataFrame, metrics: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """操作ログの指標（試行ごと）を、問題 × 条件の中央値と 95% 信頼区間にまとめる。"""
    if metrics.empty:
        return pd.DataFrame()
    data = _initial(frame).merge(metrics, on="trial_id")
    rows = []
    for key, g in data.groupby(_keys(frame), dropna=False):
        row = dict(zip(_keys(frame), key, strict=True)) | {"n": len(g)}
        for col in columns:
            med, lo, hi = median_ci(g[col].astype(float).tolist())
            row |= {f"{col} 中央値": med, f"{col} 95%CI": _fmt_ci(lo, hi)}
        rows.append(row)
    return pd.DataFrame(rows)


def _fmt_ci(lo: float, hi: float) -> str:
    if math.isnan(lo) or math.isnan(hi):
        return "—（人数不足）"
    return f"{lo:,.4g}〜{hi:,.4g}"
