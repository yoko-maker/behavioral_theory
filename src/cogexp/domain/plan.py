"""参加者に提示する項目の並び（練習 + 本課題）。"""

from __future__ import annotations

from dataclasses import dataclass

from cogexp.domain.models import Condition, Experiment, VariantRef


@dataclass(frozen=True)
class PlannedItem:
    ref: VariantRef
    is_practice: bool
    presentation_order: int  # 練習を含む通し番号（1始まり）


def rotate[T](items: tuple[T, ...], order_index: int) -> tuple[T, ...]:
    """ラテン方格の回転。order_index = k なら k 番目の項目から始める。"""
    if not items:
        return items
    k = order_index % len(items)
    return items[k:] + items[:k]


def build_plan(
    experiment: Experiment, condition: Condition, order_index: int = 0
) -> tuple[PlannedItem, ...]:
    refs = [(r, True) for r in experiment.practice_refs()]
    refs += [(r, False) for r in rotate(condition.variant_refs(), order_index)]
    return tuple(
        PlannedItem(ref=r, is_practice=p, presentation_order=i)
        for i, (r, p) in enumerate(refs, start=1)
    )
