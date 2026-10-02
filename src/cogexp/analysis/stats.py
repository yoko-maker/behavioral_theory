"""探索的分析で使う統計関数（docs/plans/phase4.md §4）。

再計算で値が変わらないよう、乱数を使う手法（ブートストラップ等）は使わない。
推定できない場合（人数不足・完全分離など）は例外で止めず、NaN や理由の文字列を返す。
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats as sps

Z95 = 1.959963984540054


def wilson_ci(k: int, n: int) -> tuple[float, float]:
    """割合の Wilson の 95% 信頼区間。n = 0 なら (NaN, NaN)。"""
    if n <= 0:
        return math.nan, math.nan
    p = k / n
    denom = 1 + Z95**2 / n
    center = (p + Z95**2 / (2 * n)) / denom
    half = Z95 * math.sqrt(p * (1 - p) / n + Z95**2 / (4 * n**2)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def newcombe_diff_ci(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float, float]:
    """割合の差 p1 − p2 と、Newcombe（Wilson 法、method 10）の 95% 信頼区間。"""
    if n1 <= 0 or n2 <= 0:
        return math.nan, math.nan, math.nan
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson_ci(k1, n1)
    l2, u2 = wilson_ci(k2, n2)
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return d, lo, hi


def median_ci(values: Sequence[float]) -> tuple[float, float, float]:
    """中央値と、順序統計量による 95% 信頼区間（分布を仮定しない）。

    区間が作れない少人数（n < 6）では区間は (NaN, NaN)。
    """
    x = np.sort(np.asarray([v for v in values if not math.isnan(v)], dtype=float))
    n = len(x)
    if n == 0:
        return math.nan, math.nan, math.nan
    med = float(np.median(x))
    # 下側の順位 j（1始まり）：P(B <= j − 1) <= 0.025 となる最大の j（B ~ Bin(n, 0.5)）
    # ppf は P(B <= k) >= 0.025 となる最小の k なので P(B <= k − 1) < 0.025。等号のときだけ +1
    j = int(sps.binom.ppf(0.025, n, 0.5))
    if sps.binom.cdf(j, n, 0.5) <= 0.025:
        j += 1
    if j < 1:
        return med, math.nan, math.nan
    return med, float(x[j - 1]), float(x[n - j])


def mean_ci(values: Sequence[float]) -> tuple[float, float, float]:
    """平均と、t 分布による 95% 信頼区間。n < 2 なら区間は NaN。"""
    x = np.asarray([v for v in values if not math.isnan(v)], dtype=float)
    n = len(x)
    if n == 0:
        return math.nan, math.nan, math.nan
    m = float(x.mean())
    if n < 2:
        return m, math.nan, math.nan
    half = float(sps.t.ppf(0.975, n - 1)) * float(x.std(ddof=1)) / math.sqrt(n)
    return m, m - half, m + half


@dataclass(frozen=True)
class MannWhitney:
    u: float
    p: float
    rank_biserial: float  # (x が y より大きい確率 − 小さい確率)。正なら x が大きい傾向


def mann_whitney(x: Sequence[float], y: Sequence[float]) -> MannWhitney | None:
    """両側の Mann–Whitney の U 検定。どちらかが空なら None。"""
    xa = [v for v in x if not math.isnan(v)]
    ya = [v for v in y if not math.isnan(v)]
    if not xa or not ya:
        return None
    res = sps.mannwhitneyu(xa, ya, alternative="two-sided")
    u = float(res.statistic)
    return MannWhitney(u=u, p=float(res.pvalue), rank_biserial=2 * u / (len(xa) * len(ya)) - 1)


def mcnemar_exact_p(b: int, c: int) -> float:
    """McNemar の正確検定（両側）の p 値。b, c は不一致の対の数。不一致がなければ NaN。"""
    if b + c == 0:
        return math.nan
    return float(sps.binomtest(min(b, c), b + c, 0.5).pvalue)


def logistic_2x2(
    data: pd.DataFrame, outcome: str, factor_a: str, ref_a: str, factor_b: str, ref_b: str
) -> pd.DataFrame | str:
    """``outcome ~ A * B`` のロジスティック回帰（処理対比、参照水準を指定）。

    返り値はオッズ比・95% 信頼区間・p 値の表。推定できない場合は理由の文字列。
    """
    import statsmodels.formula.api as smf

    d = data[[outcome, factor_a, factor_b]].dropna()
    if d[factor_a].nunique() < 2 or d[factor_b].nunique() < 2:
        return "推定できない（要因の水準がそろっていない）"
    cells = d.groupby([factor_a, factor_b])[outcome].agg(["count", "sum"])
    if len(cells) < 4 or (cells["count"] == 0).any():
        return "推定できない（空の条件がある）"
    if ((cells["sum"] == 0) | (cells["sum"] == cells["count"])).any():
        return "推定できない（ある条件で全員正答または全員誤答：完全分離）"
    formula = (
        f"{outcome} ~ C({factor_a}, Treatment('{ref_a}')) * C({factor_b}, Treatment('{ref_b}'))"
    )
    d = d.assign(**{outcome: d[outcome].astype(int)})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            fit = smf.logit(formula, data=d).fit(disp=False)
        except Exception as exc:  # 特異行列など
            return f"推定できない（{type(exc).__name__}）"
    bse = np.asarray(fit.bse, dtype=float)
    converged = bool(fit.mle_retvals.get("converged", False))
    if (
        not converged
        or not np.all(np.isfinite(bse))
        or any("separation" in str(w.message).lower() for w in caught)
    ):
        return "推定できない（収束しない・完全分離）"
    ci = fit.conf_int()
    out = pd.DataFrame(
        {
            "項": [str(i) for i in fit.params.index],
            "オッズ比": np.exp(fit.params.to_numpy()),
            "95%CI下限": np.exp(ci[0].to_numpy()),
            "95%CI上限": np.exp(ci[1].to_numpy()),
            "p値": fit.pvalues.to_numpy(),
        }
    )
    return out
