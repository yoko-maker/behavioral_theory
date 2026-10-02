from __future__ import annotations

import math

import pandas as pd
import pytest

from cogexp.analysis.summary import to_frame
from cogexp.analysis.trajectory import (
    choice_metrics,
    confidence_metrics,
    layout_of,
    log_quality,
    moves_of,
    numeric_metrics,
)


def _trial(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "trial_id": "t1",
        "client_log_status": "ok",
        "response_format": "choice",
        "outcome": "answered",
        "panel_w": 100,
        "panel_h": 50,
        "shown_at_client_ms": 1000.0,
        "choice_id": "single",
        "n_events": 0,
        "browser_family": "chrome",
        "os_family": "windows",
        "pointer_types": "mouse",
        "confidence": 4,
        "confidence_rt_client_ms": 2500.0,
        "confidence_revision_count": 1,
        "confidence_client_log_status": "ok",
    }
    return base | kw


def _ev(
    t: float,
    type_: str,
    x: float | None = None,
    y: float | None = None,
    target: str | None = None,
    payload: dict[str, object] | None = None,
    trial_id: str = "t1",
    phase: str = "answer",
) -> dict[str, object]:
    return {
        "trial_id": trial_id,
        "phase": phase,
        "event_type": type_,
        "t_client_ms": t,
        "x_norm": x,
        "y_norm": y,
        "target_id": target,
        "payload": payload,
    }


def test_metrics_definitions() -> None:
    events = to_frame(
        "events",
        [
            _ev(1001, "layout", payload={"rects": {"submit": [0, 0.8, 0.2, 0.9]}}),
            _ev(1200, "move", 0.0, 0.0),
            _ev(1300, "move", 0.3, 0.0),  # +x
            _ev(1400, "move", 0.3, 0.4),  # x 変化なし
            _ev(1500, "move", 0.1, 0.4),  # -x → 方向転換 1
            _ev(1550, "move", 0.105, 0.4),  # 0.01 未満は無視
            _ev(1600, "move", 0.5, 0.4),  # +x → 方向転換 2
            _ev(1700, "choice_enter", target="conjunction"),
            _ev(1800, "choice_enter", target="single"),
            _ev(2000, "visibility", payload={"state": "hidden"}),
            _ev(2500, "visibility", payload={"state": "visible"}),
            _ev(3000, "submit"),
        ],
    )
    [m] = choice_metrics(to_frame("trials", [_trial()]), events).to_dict("records")
    assert m["移動点数"] == 6
    assert m["x方向転換"] == 2
    assert m["初動時間_ms"] == 200.0
    assert (m["選択肢への進入"], m["最終回答以外への進入"]) == (2, 1)
    assert m["非表示時間_ms"] == 500.0
    # px に戻した距離: 30 + 20 + 20 + 0.5 + 39.5
    assert m["軌跡長_px"] == pytest.approx(30 + 20 + 20 + 0.5 + 39.5)


def test_missing_logs_are_excluded() -> None:
    trials = to_frame("trials", [_trial(client_log_status="missing")])
    assert choice_metrics(trials, to_frame("events", [])).empty


def test_hidden_until_end() -> None:
    events = to_frame(
        "events",
        [
            _ev(1500, "visibility", payload={"state": "hidden"}),
            _ev(2000, "timeout"),
        ],
    )
    [m] = choice_metrics(to_frame("trials", [_trial()]), events).to_dict("records")
    assert m["非表示時間_ms"] == 500.0
    assert math.isnan(m["初動時間_ms"])


def test_moves_and_layout_helpers() -> None:
    events = to_frame(
        "events",
        [
            _ev(5, "move", 0.2, 0.2),
            _ev(3, "move", 0.1, 0.1),
            _ev(4, "move", None, None),
            _ev(1, "layout", payload={"rects": {"input": [0, 0, 1, 1]}}),
            _ev(9, "move", 0.9, 0.9, trial_id="other"),
        ],
    )
    assert moves_of(events, "t1")["t_client_ms"].tolist() == [3, 5]
    assert layout_of(events, "t1") == {"input": [0, 0, 1, 1]}
    assert layout_of(events, "other") == {}


def test_log_quality_by_device() -> None:
    trials = to_frame(
        "trials",
        [
            _trial(n_events=100),
            _trial(
                n_events=50, client_log_status="missing", browser_family=None, pointer_types=None
            ),
            _trial(n_events=80, pointer_types="mouse,touch"),
        ],
    )
    q = log_quality(trials).set_index(["browser_family", "os_family", "pointer_types"])
    assert q.loc[("chrome", "windows", "mouse"), "ログ取得率"] == 1.0
    assert q.loc[("（不明）", "windows", "（不明）"), "ログ取得率"] == 0.0
    assert isinstance(q, pd.DataFrame)


def test_numeric_keystroke_metrics() -> None:
    events = to_frame(
        "events",
        [
            _ev(1001, "layout", payload={"rects": {"input": [0, 0.5, 0.4, 0.6]}}),
            _ev(1200, "move", 0.1, 0.5),
            _ev(1800, "input_edit", payload={"op": "insert"}),  # 最初の入力まで 800
            _ev(2000, "input_edit", payload={"op": "insert"}),
            _ev(2100, "input_edit", payload={"op": "insert"}),
            _ev(4100, "input_edit", payload={"op": "delete"}),  # 最長の間 2000
            _ev(4300, "input_edit", payload={"op": "insert"}),
            _ev(5300, "submit"),  # 最後の入力から確定まで 1000
        ],
    )
    trial = _trial(response_format="numeric", choice_id=None)
    [m] = numeric_metrics(to_frame("trials", [trial]), events).to_dict("records")
    assert m["最初の入力まで_ms"] == 800.0
    assert m["入力中の最長の間_ms"] == 2000.0
    assert m["最後の入力から確定まで_ms"] == 1000.0
    assert (m["入力操作数"], m["削除操作数"]) == (5, 1)
    # 数値入力式は軌跡の指標の対象外
    assert choice_metrics(to_frame("trials", [trial]), events).empty


def test_numeric_timeout_has_no_submit_gap() -> None:
    events = to_frame(
        "events", [_ev(1500, "input_edit", payload={"op": "insert"}), _ev(16000, "timeout")]
    )
    trial = _trial(response_format="numeric", outcome="timeout", choice_id=None)
    [m] = numeric_metrics(to_frame("trials", [trial]), events).to_dict("records")
    assert math.isnan(m["最後の入力から確定まで_ms"])
    assert math.isnan(m["入力中の最長の間_ms"])


def test_confidence_phase_is_separated() -> None:
    events = to_frame(
        "events",
        [
            _ev(1200, "move", 0.1, 0.1),
            _ev(1300, "move", 0.2, 0.1),
            # 確信度の画面（同じ trial_id）
            _ev(5000, "move", 0.1, 0.5, phase="confidence"),
            _ev(5100, "move", 0.6, 0.5, phase="confidence"),
            _ev(5200, "move", 0.3, 0.5, phase="confidence"),
            _ev(5300, "choice_enter", target="3", phase="confidence"),
            _ev(5400, "choice_enter", target="4", phase="confidence"),
            _ev(5500, "choice_enter", target="5", phase="confidence"),
        ],
    )
    trials = to_frame("trials", [_trial()])
    [m] = choice_metrics(trials, events).to_dict("records")
    assert (m["移動点数"], m["選択肢への進入"]) == (2, 0)  # 確信度の画面の操作は含めない
    assert moves_of(events, "t1")["t_client_ms"].tolist() == [1200, 1300]
    [c] = confidence_metrics(trials, events).to_dict("records")
    assert (c["確信度"], c["確信度の回答時間_ms"], c["選び直し"]) == (4, 2500.0, 1)
    assert (c["他の段階への進入"], c["移動点数"], c["x方向転換"]) == (2, 3, 1)


def test_confidence_metrics_skip_missing_logs() -> None:
    trials = to_frame("trials", [_trial(confidence_client_log_status="missing")])
    assert confidence_metrics(trials, to_frame("events", [])).empty
