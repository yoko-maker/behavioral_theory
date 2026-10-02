"""AppTest から問題画面の部品（components v2）の送信を模擬する補助関数。

公開 API では部品の送信を模擬できないため、Streamlit の内部 API（AppTest._run・
部品の trigger 用ウィジェットID の形式）を使う。Streamlit 更新で壊れた場合はここだけ直す
（docs/plans/phase3.md 決定事項ログ）。
"""

from __future__ import annotations

import json
from typing import Any

from streamlit.runtime.state.session_state import STREAMLIT_INTERNAL_KEY_PREFIX
from streamlit.testing.v1 import AppTest

from cogexp.service import CONFIDENCE_SCREEN_SUFFIX
from tests.conftest import client_payload

SESSION = "participant_session"  # app/state.py と一致させる


def active_trial_id(at: AppTest) -> str:
    """表示中の部品の画面ID（確信度の画面は 評価対象の trial_id + 接尾辞）。"""
    s = at.session_state[SESSION]
    if str(s.flow.stage) == "confidence":
        return f"{s.last_trial_id}{CONFIDENCE_SCREEN_SUFFIX}"
    assert s.active is not None, "課題画面が表示されていない"
    return str(s.active.trial_id)


def send(at: AppTest, kind: str = "submit", **overrides: Any) -> AppTest:
    """表示中の部品から送信が届いたものとして再実行する。"""
    [panel] = [e for e in at.get("bidi_component") if "panel_" in str(e.id)]
    widgets = at._tree.get_widget_states()
    w = widgets.widgets.add()
    w.id = f"{STREAMLIT_INTERNAL_KEY_PREFIX}_{panel.id}__events"
    payload = client_payload(active_trial_id(at), kind=kind, **overrides)
    w.json_trigger_value = json.dumps([{"event": kind, "value": payload}])
    at._run(widgets)
    return at


def stage(at: AppTest) -> str:
    return str(at.session_state[SESSION].flow.stage)
