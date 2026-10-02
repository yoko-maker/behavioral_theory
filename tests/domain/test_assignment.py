from __future__ import annotations

from collections import Counter

from cogexp.domain.assignment import Cell, cells, choose_cell
from cogexp.domain.models import Experiment
from cogexp.domain.plan import build_plan, rotate


def _exp(counterbalance: bool = True, n_conditions: int = 4) -> Experiment:
    return Experiment.model_validate(
        {
            "experiment_id": "e",
            "title": "e",
            "practice": ["p/a@1"],
            "counterbalance_order": counterbalance,
            "conditions": [
                {"condition_id": f"c{i}", "variants": ["t/x@1", "t/y@1"]}
                for i in range(n_conditions)
            ],
        }
    )


def test_cells_cross_conditions_and_orders() -> None:
    assert len(cells(_exp())) == 8
    assert len(cells(_exp(counterbalance=False))) == 4


def test_choose_cell_fills_evenly() -> None:
    exp = _exp()
    counts: Counter[Cell] = Counter()
    for seed in range(8):
        counts[choose_cell(exp, counts, seed)] += 1
    assert set(counts.values()) == {1} and len(counts) == 8
    for seed in range(8, 16):
        counts[choose_cell(exp, counts, seed)] += 1
    assert set(counts.values()) == {2}


def test_choose_cell_prefers_fewest_and_is_reproducible() -> None:
    exp = _exp()
    counts = {c: 3 for c in cells(exp)} | {Cell("c2", 1): 1, Cell("c3", 0): 1}
    picks = {choose_cell(exp, counts, seed) for seed in range(50)}
    assert picks == {Cell("c2", 1), Cell("c3", 0)}
    assert all(choose_cell(exp, counts, s) == choose_cell(exp, counts, s) for s in range(20))


def test_rotation_orders_main_items_only() -> None:
    exp = _exp()
    cond = exp.condition("c0")
    first = [str(i.ref) for i in build_plan(exp, cond, 0)]
    second = [str(i.ref) for i in build_plan(exp, cond, 1)]
    assert first == ["p/a@1", "t/x@1", "t/y@1"]
    assert second == ["p/a@1", "t/y@1", "t/x@1"]
    assert [i.presentation_order for i in build_plan(exp, cond, 1)] == [1, 2, 3]


def test_rotate_is_latin_square() -> None:
    items = ("a", "b", "c")
    rows = [rotate(items, k) for k in range(3)]
    # 各項目が各位置にちょうど1回ずつ現れる
    for pos in range(3):
        assert sorted(r[pos] for r in rows) == ["a", "b", "c"]
