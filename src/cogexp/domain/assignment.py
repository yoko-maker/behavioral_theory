"""条件割当。乱数はこのモジュールに閉じ込め、seed から結果を再現できるようにする。

割当の単位はセル（条件 × 出題順の回転番号）。割当人数が最も少ないセルを選び、
同数のセルが複数あれば seed による無作為で決める（概要書 §4.3 カウンターバランス）。
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass

from cogexp.domain.models import Experiment

ASSIGNMENT_METHOD = "balanced_cells"


@dataclass(frozen=True, order=True)
class Cell:
    condition_id: str
    order_index: int


def new_seed() -> int:
    return random.SystemRandom().randrange(1, 2**31)


def n_orders(experiment: Experiment, condition_id: str) -> int:
    if not experiment.counterbalance_order:
        return 1
    return len(experiment.condition(condition_id).variants)


def cells(experiment: Experiment) -> tuple[Cell, ...]:
    return tuple(
        Cell(c.condition_id, k)
        for c in experiment.conditions
        for k in range(n_orders(experiment, c.condition_id))
    )


def choose_cell(experiment: Experiment, counts: Mapping[Cell, int], seed: int) -> Cell:
    """割当人数が最少のセルを選ぶ。counts にないセルは 0 人とみなす。"""
    all_cells = cells(experiment)
    fewest = min(counts.get(c, 0) for c in all_cells)
    candidates = sorted(c for c in all_cells if counts.get(c, 0) == fewest)
    return random.Random(seed).choice(candidates)
