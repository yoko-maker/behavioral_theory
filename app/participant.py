"""参加者フローの画面。状態遷移と保存は cogexp.service に任せ、ここでは描画のみ行う。

ボタンは on_click コールバックで処理する。コールバックは次の再実行の前に走るため、
状態が先に進み、確定済みの課題画面が再描画されることはない（二重送信の防止）。
"""

from __future__ import annotations

import math

import resources
import state
import streamlit as st

from cogexp.config.loader import Catalog
from cogexp.domain.flow import Stage
from cogexp.domain.models import ResponseFormat
from cogexp.domain.scoring import parse_numeric
from cogexp.service import ParticipantService, ParticipantSession


def _select_experiment(catalog: Catalog) -> str | None:
    requested = st.query_params.get("exp")
    if requested is not None:
        return requested if requested in catalog.experiments else None
    if len(catalog.experiments) == 1:
        return next(iter(catalog.experiments))
    return None


def _prompt_markdown(text: str) -> str:
    # YAML の改行をそのまま表示する（Markdown の改行は行末スペース2つ）
    return "  \n".join(text.strip().splitlines())


def _submit_choice(svc: ParticipantService, s: ParticipantSession, key: str) -> None:
    choice = st.session_state.get(key)
    if choice is not None:
        svc.submit(s, choice_id=str(choice))


def _error_key(trial_id: str) -> str:
    # 試行ごとに分け、前の問題のエラー表示が次の問題に残らないようにする
    return f"{state.INPUT_ERROR}_{trial_id}"


def _submit_numeric(
    svc: ParticipantService, s: ParticipantSession, key: str, trial_id: str
) -> None:
    value = parse_numeric(str(st.session_state.get(key) or ""))
    if value is None and not svc.is_expired(s):
        st.session_state[_error_key(trial_id)] = "数字で入力してください。"
        return
    svc.submit(s, value=value)


def _rate(svc: ParticipantService, s: ParticipantSession, key: str) -> None:
    selected = st.session_state.get(key)
    if selected is not None:
        svc.rate(s, int(selected))


@st.fragment(run_every=0.5)
def _countdown(svc: ParticipantService, s: ParticipantSession, item_index: int) -> None:
    """制限時間の監視。表示の有無に関係なく、時間切れになったら画面全体を再実行する。"""
    if s.flow.stage is not Stage.TRIAL or s.flow.item_index != item_index:
        return
    remaining = svc.remaining_sec(s)
    cond = s.condition
    if remaining is None or cond is None or cond.time_limit_sec is None:
        return
    if remaining <= 0:
        st.rerun()
    if cond.show_countdown:
        st.progress(remaining / cond.time_limit_sec, text=f"残り {math.ceil(remaining)} 秒")


def _trial(svc: ParticipantService, s: ParticipantSession) -> None:
    active = svc.ensure_shown(s)
    if svc.is_expired(s):
        svc.timeout(s)
        st.rerun()

    item, variant = svc.current(s)
    n_practice = s.flow.n_practice
    if item.is_practice:
        st.caption(f"練習 {s.flow.item_index + 1} / {n_practice}")
    else:
        n_main = s.flow.n_items - n_practice
        st.caption(f"問題 {s.flow.item_index - n_practice + 1} / {n_main}")

    if s.condition is not None and s.condition.time_limit_sec is not None:
        _countdown(svc, s, s.flow.item_index)

    st.markdown(_prompt_markdown(variant.prompt))
    key = f"resp_{active.trial_id}"

    if variant.response_format is ResponseFormat.CHOICE:
        labels = {c.id: c.text for c in variant.choices}
        st.radio(
            "回答",
            list(labels),
            index=None,
            format_func=labels.__getitem__,
            key=key,
            on_change=svc.note_change,
            args=(s,),
            label_visibility="collapsed",
        )
        st.button(
            "回答する",
            key=f"submit_{active.trial_id}",
            type="primary",
            disabled=st.session_state.get(key) is None,
            on_click=_submit_choice,
            args=(svc, s, key),
        )
    else:
        # フォームにすると、入力欄で Enter を押したときに「回答する」と同じく送信される。
        # フォーム内の入力は送信までサーバーに届かないため、数値入力では変更回数を計測しない。
        label = f"回答（{variant.unit}）" if variant.unit else "回答"
        with st.form(key=f"form_{active.trial_id}", border=False):
            st.text_input(label, key=key)
            if err := st.session_state.get(_error_key(active.trial_id)):
                st.warning(err)
            st.form_submit_button(
                "回答する",
                type="primary",
                on_click=_submit_numeric,
                args=(svc, s, key, active.trial_id),
            )


def _confidence(svc: ParticipantService, s: ParticipantSession) -> None:
    levels = svc.experiment(s).confidence_levels
    captions = {1: "まったく自信がない", levels: "とても自信がある"}
    key = f"conf_{s.last_trial_id}"
    st.info("回答を記録しました。")
    st.radio(
        "いまの回答に、どのくらい自信がありますか。",
        list(range(1, levels + 1)),
        index=None,
        horizontal=True,
        format_func=lambda v: f"{v}（{captions[v]}）" if v in captions else str(v),
        key=key,
    )
    st.button(
        "次へ",
        key=f"rate_{s.last_trial_id}",
        type="primary",
        disabled=st.session_state.get(key) is None,
        on_click=_rate,
        args=(svc, s, key),
    )


def render() -> None:
    catalog = resources.catalog()
    s: ParticipantSession | None = st.session_state.get(state.SESSION)
    if s is None:
        exp_id = _select_experiment(catalog)
        if exp_id is None:
            st.error("実験が指定されていません。案内されたURLから開いてください。")
            return
        s = ParticipantSession(experiment_id=exp_id)
        st.session_state[state.SESSION] = s
    svc = resources.service()

    match s.flow.stage:
        case Stage.INTRO:
            st.markdown(catalog.text("intro"))
            st.button("次へ", key="btn_start", type="primary", on_click=svc.start, args=(s,))
        case Stage.CONSENT:
            st.markdown(catalog.text("consent"))
            left, right = st.columns(2)
            left.button(
                "同意して参加する", key="btn_agree", type="primary", on_click=svc.agree, args=(s,)
            )
            right.button("同意しない", key="btn_decline", on_click=svc.decline, args=(s,))
        case Stage.DECLINED:
            st.markdown(catalog.text("declined"))
        case Stage.INSTRUCTIONS:
            st.markdown(catalog.text("instructions"))
            st.button(
                "練習を始める",
                key="btn_instructions",
                type="primary",
                on_click=svc.proceed,
                args=(s,),
            )
        case Stage.TRIAL:
            _trial(svc, s)
        case Stage.CONFIDENCE:
            _confidence(svc, s)
        case Stage.TRANSITION:
            st.markdown(catalog.text("transition"))
            st.button("次へ", key="btn_transition", type="primary", on_click=svc.proceed, args=(s,))
        case Stage.END:
            st.markdown(catalog.text("end"))
