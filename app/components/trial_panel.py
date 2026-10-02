"""問題画面の部品（Streamlit components v2）の登録と呼び出し。

部品の挙動は trial_panel.js、送信値の検証は cogexp.domain.client_log を参照。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

_DIR = Path(__file__).resolve().parent

_CSS = (_DIR / "trial_panel.css").read_text(encoding="utf-8")
_JS = (_DIR / "trial_panel.js").read_text(encoding="utf-8")


def _noop() -> None:
    pass


def trial_panel(data: dict[str, Any]) -> tuple[object | None, object | None]:
    """部品を描画し、(submit, timeout) の送信値を返す（送信がなければ None）。"""
    # 登録は実行環境（ランタイム）ごとに必要なため毎回行う。同じ定義の再登録は無害
    panel = st.components.v2.component("cogexp_trial_panel", html="", css=_CSS, js=_JS)
    result = panel(
        key=f"panel_{data['trial_id']}",
        data=data,
        on_submit_change=_noop,
        on_timeout_change=_noop,
    )
    return getattr(result, "submit", None), getattr(result, "timeout", None)
