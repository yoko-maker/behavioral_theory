from __future__ import annotations

import pandas as pd
import pytest

from cogexp.analysis.summary import (
    answer_distribution,
    cell_summary,
    condition_summary,
    participation_summary,
    revision_crosstab,
    revision_summary,
    to_csv_bytes,
    to_frame,
)


def _trial(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "trial_id": None,
        "attempt": "initial",
        "initial_trial_id": None,
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


def test_revised_rows_are_excluded_from_condition_summary() -> None:
    trials = to_frame(
        "trials",
        [_trial(trial_id="a"), _trial(trial_id="b", attempt="revised", initial_trial_id="a")],
    )
    [row] = condition_summary(trials).to_dict("records")
    assert row["試行数"] == 1


def test_revision_summary_and_crosstab() -> None:
    trials = to_frame(
        "trials",
        [
            _trial(trial_id="a", choice_id="conjunction", is_correct=False),
            _trial(trial_id="a2", attempt="revised", initial_trial_id="a"),
            _trial(trial_id="b"),
            _trial(trial_id="b2", attempt="revised", initial_trial_id="b"),
            _trial(trial_id="c", outcome="timeout", choice_id=None, is_correct=None),
            _trial(trial_id="c2", attempt="revised", initial_trial_id="c"),
        ],
    )
    [row] = revision_summary(trials).to_dict("records")
    assert (row["対の数"], row["変更数"]) == (3, 2)  # 誤→正、時間切れ→回答 が変更
    table = revision_crosstab(trials)
    assert table.loc["誤答", "正答"] == 1
    assert table.loc["判定不能", "正答"] == 1


def test_revision_summary_empty() -> None:
    assert revision_summary(to_frame("trials", [_trial(trial_id="a")])).empty


def test_cell_summary_counts_status() -> None:
    p = pd.DataFrame(
        {
            "condition_id": ["x", "x", "y"],
            "order_index": [0, 0, 1],
            "status": ["completed", "aborted", "completed"],
        }
    )
    rows = cell_summary(p).to_dict("records")
    assert rows[0] == {
        "condition_id": "x",
        "order_index": 0,
        "completed": 1,
        "aborted": 1,
        "in_progress": 0,
    }
