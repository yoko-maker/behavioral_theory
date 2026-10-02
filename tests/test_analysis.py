from __future__ import annotations

import pandas as pd
import pytest

from cogexp.analysis.summary import (
    answer_distribution,
    condition_summary,
    participation_summary,
    to_csv_bytes,
    to_frame,
)


def _trial(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "condition_id": "c",
        "task_id": "linda",
        "variant_id": "standard",
        "task_version": 1,
        "is_practice": False,
        "outcome": "answered",
        "choice_id": "single",
        "response_value": None,
        "is_correct": True,
        "response_time_ms": 1000.0,
        "confidence": 3,
    }
    return base | kw


def test_condition_summary_separates_timeout_from_errors() -> None:
    trials = to_frame(
        "trials",
        [
            _trial(),
            _trial(is_correct=False, choice_id="conjunction"),
            _trial(outcome="timeout", is_correct=None, choice_id=None, response_time_ms=None),
            _trial(is_practice=True, is_correct=False),
        ],
    )
    [row] = condition_summary(trials).to_dict("records")
    assert row["試行数"] == 3  # 練習は除外
    assert row["時間切れ数"] == 1
    assert row["判定可能数"] == 2
    assert row["正答率"] == pytest.approx(0.5)


def test_empty_trials() -> None:
    assert condition_summary(to_frame("trials", [])).empty


def test_participation_summary() -> None:
    p = pd.DataFrame({"status": ["completed", "in_progress", "completed"]})
    assert participation_summary(p)["完了"] == 2


def test_answer_distribution_numeric() -> None:
    trials = to_frame(
        "trials",
        [_trial(choice_id=None, response_value=100.0), _trial(choice_id=None, response_value=50.0)],
    )
    assert set(answer_distribution(trials)["answer"]) == {"100.0", "50.0"}


def test_csv_has_bom() -> None:
    assert to_csv_bytes(pd.DataFrame({"a": ["あ"]})).startswith(b"\xef\xbb\xbf")
