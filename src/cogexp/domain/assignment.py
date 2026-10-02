"""条件割当。乱数はこのモジュールに閉じ込め、seed から結果を再現できるようにする。

フェーズ1は seed による単純無作為割当。カウンターバランス・出題順の入れ替えはフェーズ2で追加する。
"""

from __future__ import annotations

import random

from cogexp.domain.models import Condition, Experiment


def new_seed() -> int:
    return random.SystemRandom().randrange(1, 2**31)


def assign_condition(experiment: Experiment, seed: int) -> Condition:
    return random.Random(seed).choice(experiment.conditions)
