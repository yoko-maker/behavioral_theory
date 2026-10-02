"""参加者に提示する項目の並び（練習 + 本課題）。"""

from __future__ import annotations

from dataclasses import dataclass

from cogexp.domain.models import Condition, Experiment, VariantRef


@dataclass(frozen=True)
class PlannedItem:
    ref: VariantRef
    is_practice: bool
    presentation_order: int  # 練習を含む通し番号（1始まり）


def build_plan(experiment: Experiment, condition: Condition) -> tuple[PlannedItem, ...]:
    refs = [(r, True) for r in experiment.practice_refs()]
    refs += [(r, False) for r in condition.variant_refs()]
    return tuple(
        PlannedItem(ref=r, is_practice=p, presentation_order=i)
        for i, (r, p) in enumerate(refs, start=1)
    )
