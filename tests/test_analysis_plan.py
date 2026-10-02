"""分析計画（docs/plans/phase4.md §3・§4）の前処理と表をテストで固定する。"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from cogexp.analysis.inference import (
    accuracy_table,
    logistic_by_task,
    revision_table,
    rt_tests,
    wording_differences,
)
from cogexp.analysis.preprocess import (
    FAST_LIMIT_MS,
    HIDDEN_LIMIT_MS,
    analysis_frame,
    exclusion_summary,
)
from cogexp.analysis.summary import to_frame
from cogexp.domain.models import Experiment

EXP = Experiment.model_validate(
    {
        "experiment_id": "e",
        "title": "e",
        "conditions": [
            {
                "condition_id": f"{w}_{t}",
                "factors": {"wording": w, "time_limit": t},
                "variants": ["linda/standard@1"],
            }
            for w in ("standard", "reworded")
            for t in ("none", "limited")
        ],
    }
)


def _p(pid: str, status: str = "completed") -> dict[str, object]:
    return {"participant_id": pid, "status": status}


def _t(tid: str, pid: str = "p1", cond: str = "standard_none", **kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "trial_id": tid,
        "participant_id": pid,
        "experiment_id": "e",
        "condition_id": cond,
        "task_id": "linda",
        "is_practice": False,
        "attempt": "initial",
        "initial_trial_id": None,
        "outcome": "answered",
        "choice_id": "single",
        "response_value": None,
        "is_correct": True,
        "confidence": 4,
        "response_time_ms": 5000.0,
        "shown_at_client_ms": 1000.0,
        "submitted_at_client_ms": 6000.0,
        "client_log_status": "ok",
    }
    return base | kw


def _vis(tid: str, hidden_from: float, hidden_to: float) -> list[dict[str, object]]:
    def ev(t: float, state: str) -> dict[str, object]:
        return {
            "trial_id": tid,
            "phase": "answer",
            "event_type": "visibility",
            "t_client_ms": t,
            "payload": {"state": state},
        }

    return [
        ev(hidden_from, "hidden"),
        ev(hidden_to, "visible"),
        {"trial_id": tid, "phase": "answer", "event_type": "submit", "t_client_ms": 6000.0},
    ]


def _frame(participants: list, trials: list, events: list | None = None) -> pd.DataFrame:
    return analysis_frame(
        EXP,
        to_frame("participants", participants),
        to_frame("trials", trials),
        to_frame("events", events or []),
    )


def test_exclusion_rules_and_boundaries() -> None:
    trials = [
        _t("ok"),
        _t("aborted", pid="p2"),
        _t("hidden_at_limit"),
        _t("hidden_below"),
        _t("fast", submitted_at_client_ms=1000.0 + FAST_LIMIT_MS - 1),
        _t("at_fast_limit", submitted_at_client_ms=1000.0 + FAST_LIMIT_MS),
        _t(
            "timeout",
            outcome="timeout",
            is_correct=None,
            submitted_at_client_ms=None,
            response_time_ms=None,
        ),
        _t("no_log", client_log_status="missing", response_time_ms=800.0),
        _t("practice", is_practice=True),
    ]
    events = _vis("hidden_at_limit", 2000, 2000 + HIDDEN_LIMIT_MS) + _vis(
        "hidden_below", 2000, 2000 + HIDDEN_LIMIT_MS - 1
    )
    f = _frame([_p("p1"), _p("p2", "aborted")], trials, events).set_index("trial_id")
    assert "practice" not in f.index
    assert pd.isna(f.loc["ok", "exclusion"])
    assert f.loc["aborted", "exclusion"] == "E1"
    assert f.loc["hidden_at_limit", "exclusion"] == "E2"  # ちょうど 3,000 ms は除外
    assert pd.isna(f.loc["hidden_below", "exclusion"])
    assert f.loc["fast", "exclusion"] == "E3"
    assert pd.isna(f.loc["at_fast_limit", "exclusion"])  # ちょうど 1,000 ms は残す
    assert pd.isna(f.loc["timeout", "exclusion"])  # 時間切れは E3 の対象外
    # ログなし：非表示は判定不能（除外しない）、回答時間はサーバー側を使う
    assert math.isnan(f.loc["no_log", "hidden_ms"])
    assert f.loc["no_log", "rt_source"] == "server"
    assert f.loc["no_log", "exclusion"] == "E3"  # サーバー側 800 ms < 1,000 ms
    assert f.loc["ok", "rt_source"] == "client" and f.loc["ok", "rt_analysis_ms"] == 5000.0
    assert f.loc["ok", "factor_wording"] == "standard"


def test_exclusion_summary_counts() -> None:
    trials = [_t("a"), _t("b", pid="p2"), _t("c", client_log_status="missing")]
    s = exclusion_summary(_frame([_p("p1"), _p("p2", "in_progress")], trials))
    [row] = s.to_dict("records")
    assert (row["試行数"], row["分析対象"]) == (3, 2)
    assert row["E1 中断・未完了の参加者"] == 1
    assert row["非表示時間を判定不能（ログなし・除外せず）"] == 1


def _design(counts: dict[str, tuple[int, int]]) -> pd.DataFrame:
    participants, trials = [], []
    for cond, (correct, n) in counts.items():
        for i in range(n):
            pid = f"{cond}_{i}"
            participants.append(_p(pid))
            trials.append(
                _t(
                    pid,
                    pid=pid,
                    cond=cond,
                    is_correct=i < correct,
                    submitted_at_client_ms=1000.0 + 2000 + i * 100,
                )
            )
    return _frame(participants, trials)


def test_accuracy_and_differences() -> None:
    f = _design(
        {
            "standard_none": (5, 10),
            "reworded_none": (8, 10),
            "standard_limited": (3, 10),
            "reworded_limited": (6, 10),
        }
    )
    acc = accuracy_table(f).set_index("condition_id")
    assert acc.loc["reworded_none", "正答率"] == 0.8
    assert acc.loc["reworded_none", "正答率95%CI下限"] == pytest.approx(0.4902, abs=1e-4)
    diff = wording_differences(f).set_index("時間制限")
    assert diff.loc["制限なし", "正答率の差（言い換え−標準）"] == pytest.approx(0.3)
    model = logistic_by_task(f)["linda"]
    assert isinstance(model, pd.DataFrame)
    assert "言い換え × 制限あり（交互作用）" in set(model["項"])
    tests = rt_tests(f)
    assert set(tests["時間制限"]) == {"制限なし", "制限あり"}  # 制限の水準間は比較しない


def test_revision_pairs_drop_if_either_excluded() -> None:
    trials = [
        _t("i1", cond="standard_none", is_correct=False, choice_id="conjunction"),
        _t("r1", cond="standard_none", attempt="revised", initial_trial_id="i1"),
        _t("i2", cond="standard_none", is_correct=True),
        _t(
            "r2",
            cond="standard_none",
            attempt="revised",
            initial_trial_id="i2",
            submitted_at_client_ms=1500.0,
        ),  # 見直し後が E3 → 対ごと除外
    ]
    [row] = revision_table(_frame([_p("p1")], trials)).to_dict("records")
    assert (row["対の数"], row["変更"], row["誤→正"], row["正→誤"]) == (1, 1, 1, 0)
