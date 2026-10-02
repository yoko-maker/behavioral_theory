"""参加者フローの状態機械（概要書 §5）。

説明 → 同意 → 操作説明 → 練習（+確信度） → 遷移画面 → 本課題（+確信度）… → 終了

課題画面には同意（AGREE）を経由しないと到達できない。許されない遷移は例外にする。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class Stage(StrEnum):
    INTRO = "intro"
    CONSENT = "consent"
    DECLINED = "declined"
    INSTRUCTIONS = "instructions"
    TRIAL = "trial"
    CONFIDENCE = "confidence"
    TRANSITION = "transition"
    END = "end"


class Event(StrEnum):
    START = "start"
    AGREE = "agree"
    DECLINE = "decline"
    CONTINUE = "continue"
    ANSWER = "answer"
    TIMEOUT = "timeout"
    RATE = "rate"


class InvalidTransitionError(Exception):
    pass


_PRE_CONSENT = frozenset({Stage.INTRO, Stage.CONSENT, Stage.DECLINED})


@dataclass(frozen=True)
class FlowState:
    """``item_index`` は練習を含む提示項目の通し番号（0始まり）。"""

    stage: Stage = Stage.INTRO
    item_index: int = 0
    n_items: int = 0
    n_practice: int = 0
    collect_confidence: bool = False

    @property
    def consented(self) -> bool:
        return self.stage not in _PRE_CONSENT

    @property
    def in_practice(self) -> bool:
        return self.item_index < self.n_practice

    def configure(self, *, n_items: int, n_practice: int, collect_confidence: bool) -> FlowState:
        """同意時に割り当てた条件の内容を設定する。"""
        if n_items - n_practice < 1:
            raise ValueError("本課題が1題以上必要")
        if not 0 <= n_practice < n_items:
            raise ValueError("n_practice が不正")
        return replace(
            self, n_items=n_items, n_practice=n_practice, collect_confidence=collect_confidence
        )


def _after_item(state: FlowState) -> FlowState:
    i = state.item_index
    if i == state.n_practice - 1:
        return replace(state, stage=Stage.TRANSITION)
    if i + 1 < state.n_items:
        return replace(state, stage=Stage.TRIAL, item_index=i + 1)
    return replace(state, stage=Stage.END)


def advance(state: FlowState, event: Event) -> FlowState:
    match state.stage, event:
        case Stage.INTRO, Event.START:
            return replace(state, stage=Stage.CONSENT)
        case Stage.CONSENT, Event.AGREE:
            return replace(state, stage=Stage.INSTRUCTIONS)
        case Stage.CONSENT, Event.DECLINE:
            return replace(state, stage=Stage.DECLINED)
        case Stage.INSTRUCTIONS, Event.CONTINUE:
            if state.n_items < 1:
                raise InvalidTransitionError("条件が設定されていない（configure 未実行）")
            return replace(state, stage=Stage.TRIAL, item_index=0)
        case Stage.TRIAL, Event.ANSWER:
            if state.collect_confidence:
                return replace(state, stage=Stage.CONFIDENCE)
            return _after_item(state)
        case Stage.TRIAL, Event.TIMEOUT:
            # 回答がないため確信度は尋ねない
            return _after_item(state)
        case Stage.CONFIDENCE, Event.RATE:
            return _after_item(state)
        case Stage.TRANSITION, Event.CONTINUE:
            return replace(state, stage=Stage.TRIAL, item_index=state.item_index + 1)
    raise InvalidTransitionError(f"{state.stage} で {event} は受け付けない")
