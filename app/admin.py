"""実験者画面（概要書 §9）。パスワードで保護し、参加者フローからは到達できない URL に置く。

条件そのものの変更は YAML で行う（版管理のため）。この画面では閲覧と受付の開始・停止のみ行う。
"""

from __future__ import annotations

import hmac
import json

import pandas as pd
import resources
import state
import streamlit as st

from cogexp.analysis.summary import (
    answer_distribution,
    cell_summary,
    condition_summary,
    participation_summary,
    revision_crosstab,
    revision_summary,
    to_csv_bytes,
    to_frame,
    variant_summary,
)
from cogexp.config.loader import Catalog
from cogexp.domain.assignment import cells
from cogexp.storage.repository import SqliteRepository


def _login(password: str) -> bool:
    if st.session_state.get(state.ADMIN_AUTHED):
        return True
    # フォームにして、パスワード欄で Enter を押してもログインできるようにする
    with st.form("admin_login_form"):
        entered = st.text_input("パスワード", type="password", key="admin_pw")
        submitted = st.form_submit_button("ログイン")
    if submitted:
        if hmac.compare_digest(entered.encode("utf-8"), password.encode("utf-8")):
            st.session_state[state.ADMIN_AUTHED] = True
            st.rerun()
        st.error("パスワードが違います。")
    return False


def _status_tab(participants: pd.DataFrame, trials: pd.DataFrame, events: pd.DataFrame) -> None:
    summary = participation_summary(participants)
    for col, (label, value) in zip(st.columns(len(summary)), summary.items(), strict=True):
        col.metric(label, value)

    st.subheader("条件別（練習を除く・初回回答）")
    st.caption("正答率の分母は判定可能な回答。時間切れは誤答に含めず、時間切れ率として示す。")
    st.dataframe(condition_summary(trials), hide_index=True)

    st.subheader("問題・版別")
    st.dataframe(variant_summary(trials), hide_index=True)

    st.subheader("回答分布")
    st.dataframe(answer_distribution(trials), hide_index=True)

    st.subheader("エクスポート")
    st.caption("生データ（練習・見直しを含む）。直接識別情報は保存していない。")
    for col, (name, df) in zip(
        st.columns(3),
        [("participants", participants), ("trials", trials), ("events", events)],
        strict=True,
    ):
        col.download_button(
            f"{name}.csv",
            data=to_csv_bytes(df),
            file_name=f"{name}.csv",
            mime="text/csv",
            key=f"dl_{name}",
        )


def _revision_tab(trials: pd.DataFrame) -> None:
    st.caption("見直しあり条件のみ。同一参加者の初回回答と見直し後の回答を対にしている。")
    st.subheader("回答変化率")
    st.dataframe(revision_summary(trials), hide_index=True)
    st.subheader("初回 × 見直し後（正誤）")
    st.dataframe(revision_crosstab(trials))


def _settings_tab(catalog: Catalog, repo: SqliteRepository, participants: pd.DataFrame) -> None:
    st.caption("条件の変更は experiments/ の YAML で行う（docs/plans/phase2.md）。")
    svc = resources.experimenter_service()
    for exp_id, exp in catalog.experiments.items():
        st.subheader(f"{exp.title}（{exp_id}）")
        accepting = repo.is_accepting(exp_id)
        left, right = st.columns([3, 1])
        left.markdown(f"受付状態：**{'受付中' if accepting else '停止中'}**")
        right.button(
            "受付を停止する" if accepting else "受付を開始する",
            key=f"toggle_{exp_id}",
            type="secondary" if accepting else "primary",
            on_click=svc.set_accepting,
            args=(exp_id, not accepting),
        )
        log = to_frame("experiment_status_log", repo.read_table("experiment_status_log"))
        log = log[log["experiment_id"] == exp_id].sort_values("changed_at", ascending=False)
        with st.expander("受付の切替履歴"):
            st.dataframe(log[["changed_at", "accepting"]], hide_index=True)

        st.markdown("**条件**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "condition_id": c.condition_id,
                        "制限時間(秒)": c.time_limit_sec,
                        "残り時間表示": c.show_countdown,
                        "確信度": c.collect_confidence,
                        "見直し": c.allow_revision,
                        "問題": ", ".join(c.variants),
                    }
                    for c in exp.conditions
                ]
            ),
            hide_index=True,
        )
        st.markdown(
            f"練習：{', '.join(exp.practice) or 'なし'} ／ "
            f"出題順の均等化：{'あり' if exp.counterbalance_order else 'なし'} ／ "
            f"放置とみなす時間：{exp.abandon_after_min} 分"
        )

        st.markdown("**セル（条件 × 出題順）別の人数**")
        planned = pd.DataFrame(
            [{"condition_id": c.condition_id, "order_index": c.order_index} for c in cells(exp)]
        )
        counts = cell_summary(participants[participants["experiment_id"] == exp_id])
        merged = planned.merge(counts, how="left", on=["condition_id", "order_index"])
        st.dataframe(merged.fillna(0), hide_index=True)

        refs = sorted(
            {*exp.practice_refs(), *(r for c in exp.conditions for r in c.variant_refs())},
            key=str,
        )
        with st.expander("問題文の版"):
            for ref in refs:
                v = catalog.variant(ref)
                st.markdown(f"**{ref}**（{v.response_format.value}）")
                st.text(v.prompt.strip())
                if v.choices:
                    st.text("選択肢: " + " / ".join(f"{c.id}: {c.text}" for c in v.choices))
        st.download_button(
            f"条件設定・問題文の版（{exp_id}.json）",
            data=json.dumps(catalog.snapshot(exp_id), ensure_ascii=False, indent=2),
            file_name=f"{exp_id}_config.json",
            mime="application/json",
            key=f"dl_config_{exp_id}",
        )


def render() -> None:
    st.title("実験者画面")
    password = resources.admin_password()
    if password is None:
        st.warning(
            "実験者パスワードが未設定です。環境変数 COGEXP_ADMIN_PASSWORD か "
            ".streamlit/secrets.toml の admin_password を設定してください。"
        )
        return
    if not _login(password):
        return

    repo = resources.repository()
    catalog = resources.catalog()
    participants = to_frame("participants", repo.read_table("participants"))
    trials = to_frame("trials", repo.read_table("trials"))
    events = to_frame("events", repo.read_table("events"))

    status_tab, revision_tab, settings_tab = st.tabs(["実施状況", "見直し", "条件設定"])
    with status_tab:
        _status_tab(participants, trials, events)
    with revision_tab:
        _revision_tab(trials)
    with settings_tab:
        _settings_tab(catalog, repo, participants)
