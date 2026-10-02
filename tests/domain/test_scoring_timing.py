from __future__ import annotations

import pytest

from cogexp.domain.assignment import assign_condition
from cogexp.domain.clock import FakeClock
from cogexp.domain.models import Experiment, Outcome, TaskVariant
from cogexp.domain.scoring import parse_numeric, score
from cogexp.domain.timing import Deadline

CHOICE = TaskVariant.model_validate(
    {
        "task_id": "t",
        "variant_id": "c",
        "version": 1,
        "response_format": "choice",
        "prompt": "p",
        "choices": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
        "correct_choice_id": "a",
    }
)
NUMERIC = TaskVariant.model_validate(
    {
        "task_id": "t",
        "variant_id": "n",
        "version": 1,
        "response_format": "numeric",
        "prompt": "p",
        "correct_value": 50,
    }
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("50", 50.0), ("５０", 50.0), ("1,100", 1100.0), ("50円", 50.0), ("-3.5", -3.5)],
)
def test_parse_numeric_accepts(text: str, expected: float) -> None:
    assert parse_numeric(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "5 0 0x", "nan", "inf", "1e400"])
def test_parse_numeric_rejects(text: str) -> None:
    assert parse_numeric(text) is None


def test_score_choice_and_numeric() -> None:
    assert score(CHOICE, Outcome.ANSWERED, "a", None) is True
    assert score(CHOICE, Outcome.ANSWERED, "b", None) is False
    assert score(NUMERIC, Outcome.ANSWERED, None, 50.0) is True
    assert score(NUMERIC, Outcome.ANSWERED, None, 100.0) is False


@pytest.mark.parametrize("outcome", [Outcome.TIMEOUT, Outcome.SKIPPED, Outcome.ABORTED])
def test_score_is_none_unless_answered(outcome: Outcome) -> None:
    assert score(CHOICE, outcome, None, None) is None
    assert score(NUMERIC, outcome, None, None) is None


def test_score_without_correct_definition() -> None:
    v = CHOICE.model_copy(update={"correct_choice_id": None})
    assert score(v, Outcome.ANSWERED, "a", None) is None


def test_score_rejects_unknown_choice() -> None:
    with pytest.raises(ValueError):
        score(CHOICE, Outcome.ANSWERED, "zzz", None)


def test_deadline_boundary() -> None:
    clock = FakeClock()
    d = Deadline(started_ms=clock.monotonic_ms(), time_limit_sec=15)
    clock.advance_ms(14_999)
    assert not d.expired(clock.monotonic_ms())
    assert d.remaining_sec(clock.monotonic_ms()) == pytest.approx(0.001)
    clock.advance_ms(1)
    assert d.expired(clock.monotonic_ms())
    assert d.remaining_sec(clock.monotonic_ms()) == 0.0


def test_deadline_without_limit() -> None:
    d = Deadline(started_ms=0, time_limit_sec=None)
    assert not d.expired(10**9)
    assert d.remaining_sec(10**9) is None


def test_assignment_is_reproducible() -> None:
    exp = Experiment.model_validate(
        {
            "experiment_id": "e",
            "title": "e",
            "conditions": [{"condition_id": f"c{i}", "variants": ["t/c@1"]} for i in range(4)],
        }
    )
    picks = {assign_condition(exp, seed).condition_id for seed in range(200)}
    assert picks == {"c0", "c1", "c2", "c3"}
    assert all(assign_condition(exp, s) == assign_condition(exp, s) for s in range(50))
