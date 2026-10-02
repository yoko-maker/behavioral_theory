"""参加者フローの画面。状態遷移と保存は cogexp.service に任せ、ここでは描画のみ行う。

課題画面は JavaScript の部品（components/trial_panel）で描画し、操作ログとともに送信を受け取る。
説明画面などのボタンは on_click コールバックで処理する。コールバックは次の再実行の前に走るため、
状態が先に進み、確定済みの画面が再描画されることはない（二重送信の防止）。
"""

from __future__ import annotations

from collections.abc import Callable

import resources
import state
import streamlit as st
from components.trial_panel import trial_panel

from cogexp.config.loader import Catalog
from cogexp.domain.flow import Stage
from cogexp.domain.models import Outcome, ResponseFormat, TaskVariant
from cogexp.service import ClientResult, InitialAnswer, ParticipantService, ParticipantSession


def _select_experiment(catalog: Catalog) -> str | None:
    requested = st.query_params.get("exp")
    if requested is not None:
        return requested if requested in catalog.experiments else None
    if len(catalog.experiments) == 1:
        return next(iter(catalog.experiments))
    return None


@st.fragment(run_every=0.5)
def _deadline_watch(svc: ParticipantService, s: ParticipantSession, item_index: int) -> None:
    """制限時間の監視（表示はしない）。時間切れを確定すべきときに画面全体を再実行する。

    残り時間の表示とブラウザ側の時間切れ通知は部品が行う。部品からの通知が届かない場合の保険。
    """
    if s.flow.stage is not Stage.TRIAL or s.flow.item_index != item_index:
        return
    if svc.timeout_due(s):
        st.rerun()


def _format_initial(variant: TaskVariant, initial: InitialAnswer) -> str:
    if initial.outcome is not Outcome.ANSWERED:
        return "時間切れ（未回答）"
    if initial.choice_id is not None:
        return {c.id: c.text for c in variant.choices}[initial.choice_id]
    unit = variant.unit or ""
    return f"{initial.value:g}{unit}"


def _panel_data(svc: ParticipantService, s: ParticipantSession) -> dict[str, object]:
    active = svc.ensure_shown(s)
    item, variant = svc.current(s)
    flow = s.flow
    if flow.reviewing:
        caption = f"見直し {flow.review_index + 1} / {flow.n_main}"
    elif item.is_practice:
        caption = f"練習 {flow.item_index + 1} / {flow.n_practice}"
    else:
        caption = f"問題 {flow.item_index - flow.n_practice + 1} / {flow.n_main}"

    # 見直しでは初回回答を表示し、既定値として入れておく
    initial = svc.initial_answer(s) if flow.reviewing else None
    answered_before = initial is not None and initial.outcome is Outcome.ANSWERED
    remaining = svc.remaining_sec(s)
    limit = active.deadline.time_limit_sec
    is_choice = variant.response_format is ResponseFormat.CHOICE
    return {
        "trial_id": active.trial_id,
        "caption": caption,
        "prompt": variant.prompt.strip(),
        "format": variant.response_format.value,
        "choices": [{"id": c.id, "text": c.text} for c in variant.choices],
        "input_label": f"回答（{variant.unit}）" if variant.unit else "回答",
        "initial_note": (
            f"最初の回答：{_format_initial(variant, initial)}" if initial is not None else None
        ),
        "initial_choice": initial.choice_id if answered_before and initial and is_choice else None,
        "initial_text": (
            f"{initial.value:g}"
            if answered_before and initial and initial.value is not None
            else ""
        ),
        "time_limit_ms": limit * 1000 if limit is not None else None,
        "remaining_ms": remaining * 1000 if remaining is not None else None,
        "show_countdown": bool(s.condition and s.condition.show_countdown and limit),
        "error": active.error,
        "error_seq": active.error_seq,
        "submit_label": "回答する",
    }


def _trial(svc: ParticipantService, s: ParticipantSession) -> None:
    """本課題・練習・見直しの画面。"""
    if s.flow.stage is Stage.TRIAL and svc.timeout_due(s):
        svc.timeout(s)
        st.rerun()

    submitted, timed_out = trial_panel(_panel_data(svc, s))
    for raw in (submitted, timed_out):
        if raw is None:
            continue
        result = svc.handle_client(s, raw)
        if result in (ClientResult.ACCEPTED, ClientResult.TIMEOUT, ClientResult.INVALID):
            st.rerun()

    if s.active is not None and s.active.deadline.time_limit_sec is not None:
        _deadline_watch(svc, s, s.flow.item_index)


def _confidence(svc: ParticipantService, s: ParticipantSession) -> None:
    """確信度の画面。問題画面と同じ部品で、段階を横に並べて操作ログも取る。"""
    levels = svc.experiment(s).confidence_levels
    captions = {1: "まったく自信がない", levels: "とても自信がある"}
    data = {
        "trial_id": svc.confidence_screen_id(s),
        "caption": "",
        "prompt": "いまの回答に、どのくらい自信がありますか。",
        "format": "scale",
        "choices": [
            {"id": str(v), "text": f"{v}\n{captions[v]}" if v in captions else str(v)}
            for v in range(1, levels + 1)
        ],
        "input_label": "",
        "initial_note": "回答を記録しました。",
        "initial_choice": None,
        "initial_text": "",
        "time_limit_ms": None,
        "remaining_ms": None,
        "show_countdown": False,
        "error": s.confidence_error,
        "error_seq": s.confidence_error_seq,
        "submit_label": "次へ",
    }
    submitted, _ = trial_panel(data)
    if submitted is not None and svc.handle_confidence(s, submitted) in (
        ClientResult.ACCEPTED,
        ClientResult.INVALID,
    ):
        st.rerun()


def _new_session(svc: ParticipantService, catalog: Catalog) -> ParticipantSession | None:
    """新しいセッション。URL に参加者IDがあれば再読み込み・別タブとみなす（再開はさせない）。"""
    pid = st.query_params.get("pid")
    if pid is not None:
        restored = svc.restore(pid)
        if restored is not None:
            return restored
        del st.query_params["pid"]
    exp_id = _select_experiment(catalog)
    return ParticipantSession(experiment_id=exp_id) if exp_id is not None else None


def _button(
    label: str, key: str, fn: Callable[[ParticipantSession], bool], s: ParticipantSession
) -> None:
    st.button(label, key=key, type="primary", on_click=fn, args=(s,))


def render() -> None:
    catalog = resources.catalog()
    svc = resources.service()
    s: ParticipantSession | None = st.session_state.get(state.SESSION)
    if s is None:
        s = _new_session(svc, catalog)
        if s is None:
            st.error("実験が指定されていません。案内されたURLから開いてください。")
            return
        st.session_state[state.SESSION] = s

    # 同意後は URL に参加者IDを付け、再読み込み・別タブを検知できるようにする
    if s.flow.consented and st.query_params.get("pid") != s.participant_id:
        st.query_params["pid"] = s.participant_id

    match s.flow.stage:
        case Stage.INTRO:
            if not svc.is_accepting(s.experiment_id):
                st.markdown(catalog.text("closed"))
                return
            st.markdown(catalog.text("intro"))
            _button("次へ", "btn_start", svc.start, s)
        case Stage.CONSENT:
            st.markdown(catalog.text("consent"))
            left, right = st.columns(2)
            left.button(
                "同意して参加する", key="btn_agree", type="primary", on_click=svc.agree, args=(s,)
            )
            right.button("同意しない", key="btn_decline", on_click=svc.decline, args=(s,))
        case Stage.DECLINED:
            st.markdown(catalog.text("declined"))
        case Stage.CLOSED:
            st.markdown(catalog.text("closed"))
        case Stage.INSTRUCTIONS:
            st.markdown(catalog.text("instructions"))
            _button("練習を始める", "btn_instructions", svc.proceed, s)
        case Stage.TRIAL | Stage.REVIEW:
            _trial(svc, s)
        case Stage.CONFIDENCE:
            _confidence(svc, s)
        case Stage.TRANSITION:
            st.markdown(catalog.text("transition"))
            _button("次へ", "btn_transition", svc.proceed, s)
        case Stage.REVIEW_INTRO:
            st.markdown(catalog.text("review_intro"))
            _button("見直しを始める", "btn_review", svc.proceed, s)
        case Stage.END:
            st.markdown(catalog.text("end"))
        case Stage.ABORTED:
            st.markdown(catalog.text("aborted"))
