"""実験者画面（概要書 §9）。パスワードで保護し、参加者フローからは到達できない URL に置く。"""

from __future__ import annotations

import hmac
import json

import resources
import state
import streamlit as st

from cogexp.analysis.summary import (
    answer_distribution,
    condition_summary,
    participation_summary,
    to_csv_bytes,
    to_frame,
    variant_summary,
)


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

    st.subheader("実施状況")
    for col, (label, value) in zip(
        st.columns(3), participation_summary(participants).items(), strict=True
    ):
        col.metric(label, value)

    st.subheader("条件別（練習を除く）")
    st.caption("正答率の分母は判定可能な回答。時間切れは誤答に含めず、時間切れ率として示す。")
    st.dataframe(condition_summary(trials), hide_index=True)

    st.subheader("問題・版別")
    st.dataframe(variant_summary(trials), hide_index=True)

    st.subheader("回答分布")
    st.dataframe(answer_distribution(trials), hide_index=True)

    st.subheader("エクスポート")
    st.caption("生データ（練習を含む）。直接識別情報は保存していない。")
    cols = st.columns(3)
    for col, (name, df) in zip(
        cols,
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
    for exp_id in catalog.experiments:
        st.download_button(
            f"条件設定・問題文の版（{exp_id}.json）",
            data=json.dumps(catalog.snapshot(exp_id), ensure_ascii=False, indent=2),
            file_name=f"{exp_id}_config.json",
            mime="application/json",
            key=f"dl_config_{exp_id}",
        )
