"""回答の解釈と正誤判定。"""

from __future__ import annotations

import math
import re
import unicodedata

from cogexp.domain.models import Outcome, ResponseFormat, TaskVariant

_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")


def parse_numeric(text: str) -> float | None:
    """数値入力欄の文字列を数値にする。全角数字・桁区切り・単位「円」を許容する。

    解釈できない場合は None（UI で入力し直してもらう）。
    """
    s = unicodedata.normalize("NFKC", text).strip()
    s = s.replace(",", "").replace("円", "").replace(" ", "").replace("−", "-")
    if not _NUMBER.match(s):
        return None
    value = float(s)
    return value if math.isfinite(value) else None


def score(
    variant: TaskVariant,
    outcome: Outcome,
    choice_id: str | None,
    value: float | None,
) -> bool | None:
    """正誤を返す。判定できない場合（時間切れ・未回答・正答定義なし）は None。"""
    if outcome is not Outcome.ANSWERED:
        return None
    if variant.response_format is ResponseFormat.CHOICE:
        if choice_id is None:
            raise ValueError(f"{variant.ref}: 回答済みなのに choice_id がない")
        if choice_id not in {c.id for c in variant.choices}:
            raise ValueError(f"{variant.ref}: 未定義の choice_id {choice_id!r}")
        if variant.correct_choice_id is None:
            return None
        return choice_id == variant.correct_choice_id
    if value is None:
        raise ValueError(f"{variant.ref}: 回答済みなのに数値がない")
    if variant.correct_value is None:
        return None
    return abs(value - variant.correct_value) <= variant.tolerance
