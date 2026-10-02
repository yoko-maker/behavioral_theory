from __future__ import annotations

import pytest

from cogexp.domain.flow import Event, FlowState, InvalidTransitionError, Stage, advance


def _consented(
    n_items: int = 4, n_practice: int = 2, confidence: bool = True, revision: bool = False
) -> FlowState:
    s = advance(advance(FlowState(), Event.START), Event.AGREE)
    return s.configure(
        n_items=n_items,
        n_practice=n_practice,
        collect_confidence=confidence,
        allow_revision=revision,
    )


def _run(state: FlowState, *events: Event) -> FlowState:
    for e in events:
        state = advance(state, e)
    return state


def test_decline_never_reaches_trial() -> None:
    s = _run(FlowState(), Event.START, Event.DECLINE)
    assert s.stage is Stage.DECLINED
    assert not s.consented
    for e in Event:
        with pytest.raises(InvalidTransitionError):
            advance(s, e)


@pytest.mark.parametrize("event", [Event.CONTINUE, Event.ANSWER, Event.TIMEOUT, Event.RATE])
def test_cannot_skip_consent(event: Event) -> None:
    s = advance(FlowState(), Event.START)
    with pytest.raises(InvalidTransitionError):
        advance(s, event)


def test_instructions_require_configure() -> None:
    s = _run(FlowState(), Event.START, Event.AGREE)
    with pytest.raises(InvalidTransitionError):
        advance(s, Event.CONTINUE)


def test_full_path_with_practice_and_confidence() -> None:
    s = advance(_consented(), Event.CONTINUE)
    assert (s.stage, s.item_index, s.in_practice) == (Stage.TRIAL, 0, True)
    s = _run(s, Event.ANSWER, Event.RATE)
    assert (s.stage, s.item_index) == (Stage.TRIAL, 1)
    s = _run(s, Event.ANSWER, Event.RATE)
    assert s.stage is Stage.TRANSITION
    s = advance(s, Event.CONTINUE)
    assert (s.stage, s.item_index, s.in_practice) == (Stage.TRIAL, 2, False)
    s = _run(s, Event.ANSWER, Event.RATE, Event.ANSWER, Event.RATE)
    assert s.stage is Stage.END


def test_timeout_skips_confidence() -> None:
    s = advance(_consented(n_items=2, n_practice=0), Event.CONTINUE)
    s = advance(s, Event.TIMEOUT)
    assert (s.stage, s.item_index) == (Stage.TRIAL, 1)


def test_without_confidence() -> None:
    s = advance(_consented(n_items=1, n_practice=0, confidence=False), Event.CONTINUE)
    assert advance(s, Event.ANSWER).stage is Stage.END


def test_configure_requires_main_item() -> None:
    with pytest.raises(ValueError):
        FlowState().configure(n_items=2, n_practice=2, collect_confidence=True)


def test_review_after_main_items() -> None:
    s = advance(_consented(n_items=3, n_practice=1, revision=True), Event.CONTINUE)
    s = _run(s, Event.ANSWER, Event.RATE, Event.CONTINUE)  # 練習 → 遷移
    s = _run(s, Event.TIMEOUT, Event.ANSWER, Event.RATE)  # 本課題2問
    assert s.stage is Stage.REVIEW_INTRO
    s = advance(s, Event.CONTINUE)
    assert (s.stage, s.reviewing, s.current_item_index) == (Stage.REVIEW, True, 1)
    assert not s.in_practice
    s = _run(s, Event.ANSWER, Event.RATE)
    assert (s.stage, s.current_item_index) == (Stage.REVIEW, 2)
    s = _run(s, Event.ANSWER, Event.RATE)
    assert s.stage is Stage.END


def test_review_has_no_timeout() -> None:
    s = advance(
        _consented(n_items=1, n_practice=0, confidence=False, revision=True), Event.CONTINUE
    )
    s = _run(s, Event.ANSWER, Event.CONTINUE)
    with pytest.raises(InvalidTransitionError):
        advance(s, Event.TIMEOUT)


def test_no_review_without_revision() -> None:
    s = advance(_consented(n_items=1, n_practice=0, confidence=False), Event.CONTINUE)
    assert advance(s, Event.ANSWER).stage is Stage.END


@pytest.mark.parametrize("first", [[], [Event.START]])
def test_close_before_consent(first: list[Event]) -> None:
    s = _run(FlowState(), *first, Event.CLOSE)
    assert s.stage is Stage.CLOSED and not s.consented
    for e in Event:
        with pytest.raises(InvalidTransitionError):
            advance(s, e)
