"""統計関数を既知の値で固定する（docs/plans/phase4.md M3）。"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from cogexp.analysis.stats import (
    logistic_2x2,
    mann_whitney,
    mcnemar_exact_p,
    mean_ci,
    median_ci,
    newcombe_diff_ci,
    wilson_ci,
)


def test_wilson_known_values() -> None:
    assert wilson_ci(8, 10) == pytest.approx((0.4902, 0.9433), abs=1e-4)
    assert wilson_ci(0, 10) == pytest.approx((0.0, 0.2775), abs=1e-4)
    assert all(math.isnan(v) for v in wilson_ci(0, 0))


def test_newcombe_published_example() -> None:
    # Newcombe (1998) Statistics in Medicine 17:873 の例：56/70 − 48/80
    d, lo, hi = newcombe_diff_ci(56, 70, 48, 80)
    assert d == pytest.approx(0.2)
    assert (lo, hi) == pytest.approx((0.0524, 0.3339), abs=1e-4)


def test_median_ci_order_statistics() -> None:
    # n = 10 の 95% 区間は 2 番目と 9 番目の値（被覆確率 97.9%）
    assert median_ci([float(v) for v in range(1, 11)]) == (5.5, 2.0, 9.0)
    # n = 6 は 1 番目と 6 番目、n = 5 では作れない
    assert median_ci([float(v) for v in range(1, 7)]) == (3.5, 1.0, 6.0)
    med, lo, hi = median_ci([1.0, 2.0, 3.0, 4.0, 5.0])
    assert med == 3.0 and math.isnan(lo) and math.isnan(hi)
    assert math.isnan(median_ci([])[0])


def test_mean_ci_t_interval() -> None:
    assert mean_ci([1.0, 2.0, 3.0, 4.0, 5.0]) == pytest.approx((3.0, 1.0368, 4.9632), abs=1e-4)
    m, lo, _ = mean_ci([4.0])
    assert m == 4.0 and math.isnan(lo)


def test_mann_whitney_direction_and_effect() -> None:
    r = mann_whitney([10.0, 11.0, 12.0], [1.0, 2.0, 3.0])
    assert r is not None and r.rank_biserial == 1.0 and r.u == 9.0
    assert mann_whitney([], [1.0]) is None


def test_mcnemar_exact() -> None:
    assert mcnemar_exact_p(1, 9) == pytest.approx(0.021484375)
    assert math.isnan(mcnemar_exact_p(0, 0))


def _cells(spec: dict[tuple[str, str], tuple[int, int]]) -> pd.DataFrame:
    rows = []
    for (wording, limit), (correct, n) in spec.items():
        rows += [{"y": i < correct, "w": wording, "t": limit} for i in range(n)]
    return pd.DataFrame(rows)


def test_logistic_matches_cell_odds() -> None:
    data = _cells(
        {
            ("standard", "none"): (5, 10),  # odds 1
            ("reworded", "none"): (8, 10),  # odds 4
            ("standard", "limited"): (3, 10),  # odds 3/7
            ("reworded", "limited"): (6, 10),  # odds 1.5
        }
    )
    table = logistic_2x2(data, "y", "w", "standard", "t", "none")
    assert isinstance(table, pd.DataFrame)
    odds = dict(zip(table["項"], table["オッズ比"], strict=True))
    wording = next(v for k, v in odds.items() if "reworded" in k and ":" not in k)
    limit = next(v for k, v in odds.items() if "limited" in k and ":" not in k)
    interaction = next(v for k, v in odds.items() if ":" in k)
    assert wording == pytest.approx(4.0, rel=1e-4)
    assert limit == pytest.approx(3 / 7, rel=1e-4)
    assert interaction == pytest.approx((1.5 / (3 / 7)) / 4, rel=1e-4)


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ({("standard", "none"): (5, 10), ("reworded", "none"): (8, 10)}, "水準"),
        (
            {
                ("standard", "none"): (5, 10),
                ("reworded", "none"): (10, 10),
                ("standard", "limited"): (3, 10),
                ("reworded", "limited"): (6, 10),
            },
            "完全分離",
        ),
    ],
)
def test_logistic_reports_why_not_estimable(
    spec: dict[tuple[str, str], tuple[int, int]], message: str
) -> None:
    result = logistic_2x2(_cells(spec), "y", "w", "standard", "t", "none")
    assert isinstance(result, str) and message in result
